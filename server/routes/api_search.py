"""API routes for search operations — preview count, trigger scrape."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from config.settings import SearchProfile
from db.repository import JobRepository
from monitor.logger import get_logger
from scraper.parallel import parallel_collect
from server.app import scrape_lock, scrape_status, templates

log = get_logger("api.search")

router = APIRouter(tags=["search"])


@router.post("/search/preview", response_class=HTMLResponse)
async def preview_count(request: Request):
    """Binary search to count total results for given search parameters.

    Returns an HTML partial with the count badge.
    """
    form = await request.form()
    profile = _form_to_profile(form)

    from scraper.parallel import _probe_total_results

    total = await _probe_total_results(profile)

    return templates.TemplateResponse(
        "partials/count_badge.html",
        {"request": request, "count": total, "profile": profile},
    )


@router.post("/search/scrape", response_class=HTMLResponse)
async def trigger_scrape(request: Request):
    """Trigger a parallel scrape for the given search parameters.

    Returns an HTML partial with the result summary.
    """
    if scrape_lock.locked():
        return HTMLResponse(
            '<div class="p-4 bg-yellow-100 text-yellow-800 rounded">'
            "A scrape is already running. Please wait.</div>"
        )

    form = await request.form()
    profile = _form_to_profile(form)
    save_profile = form.get("save_profile") == "on"
    enrich = form.get("enrich", "on") == "on"

    # Run in background so we can return immediately
    asyncio.create_task(_run_scrape_task(profile, save_profile, enrich))

    return HTMLResponse(
        '<div id="scrape-status" class="p-4 bg-blue-100 text-blue-800 rounded" '
        'hx-get="/api/search/status" hx-trigger="every 2s" hx-swap="outerHTML">'
        f"Scraping <strong>{profile.keywords}</strong>... "
        "Workers are collecting jobs in parallel.</div>"
    )


@router.get("/search/status", response_class=HTMLResponse)
async def scrape_status_check(request: Request):
    """Poll endpoint for scrape progress."""
    if scrape_status["running"]:
        return HTMLResponse(
            '<div id="scrape-status" class="p-4 bg-blue-100 text-blue-800 rounded" '
            'hx-get="/api/search/status" hx-trigger="every 2s" hx-swap="outerHTML">'
            f"{scrape_status['message']}</div>"
        )
    msg = scrape_status.get("message", "Scrape complete.")
    return HTMLResponse(
        f'<div id="scrape-status" class="p-4 bg-green-100 text-green-800 rounded">{msg}</div>'
    )


async def _run_scrape_task(profile: SearchProfile, save_profile: bool, enrich: bool) -> None:
    """Background task: run parallel scrape and persist results to DB."""
    async with scrape_lock:
        scrape_status["running"] = True
        scrape_status["message"] = f"Scraping {profile.keywords}..."

        repo = JobRepository()

        try:
            # Optionally save the search profile
            if save_profile:
                repo.save_profile(
                    {
                        "name": profile.name,
                        "keywords": profile.keywords,
                        "location": profile.location,
                        "geo_id": profile.geo_id,
                        "distance": profile.distance,
                        "time_filter": profile.time_filter,
                        "experience_levels": ",".join(profile.experience_levels),
                        "job_types": ",".join(profile.job_types),
                        "max_pages": profile.max_pages,
                    }
                )

            # Create scrape run record
            run_id = repo.create_scrape_run(profile.name, profile.keywords, profile.location)

            # Run parallel collection
            scrape_status["message"] = f"Probing result count for '{profile.keywords}'..."
            result = await parallel_collect(profile, enrich=enrich)

            # Persist results to DB
            new_count = 0
            updated_count = 0
            scrape_status["message"] = f"Saving {len(result.cards)} jobs to database..."

            for card in result.cards:
                _, is_new = repo.upsert_job(
                    {
                        "job_id": card.job_id,
                        "title": card.title,
                        "company": card.company,
                        "location": card.location,
                        "url": card.url,
                        "description": card.description,
                        "salary_raw": card.salary,
                        "job_type": card.employment_type or "Unknown",
                        "workplace_type": card.workplace_type or "Unknown",
                        "seniority_level": card.seniority_level,
                        "applicant_count": card.applicant_count,
                        "posted_date": card.posted_date,
                        "badge": card.badge,
                        "job_function": card.job_function,
                        "industries": card.industries,
                        "hiring_manager": (
                            f"{card.hiring_manager_name}|{card.hiring_manager_url}"
                            if card.hiring_manager_name
                            else ""
                        ),
                        "enriched": bool(card.description),
                        "extraction_strategy": "parallel_guest",
                        "scrape_run_id": run_id,
                    }
                )
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1

            # Complete the run record
            repo.complete_scrape_run(
                run_id,
                total_found=result.total_results_probed,
                new_jobs=new_count,
                updated_jobs=updated_count,
                workers_used=result.workers_used,
                elapsed_seconds=result.elapsed_seconds,
            )

            scrape_status["message"] = (
                f"Done! {new_count} new jobs, {updated_count} updated "
                f"({result.elapsed_seconds:.0f}s, {result.workers_used} workers). "
                '<a href="/jobs" class="underline font-bold">View jobs</a>'
            )
            log.info(
                f"Scrape complete: {new_count} new, {updated_count} updated",
                extra={"ctx": {"run_id": run_id}},
            )

        except Exception as e:
            scrape_status["message"] = f"Scrape failed: {e}"
            log.error(f"Scrape task failed: {e}", exc_info=True)

        finally:
            scrape_status["running"] = False
            repo.close()


def _form_to_profile(form) -> SearchProfile:
    """Convert form data to a SearchProfile."""
    keywords = str(form.get("keywords", "")).strip()
    location = str(form.get("location", "")).strip()
    name = keywords.lower().replace(" ", "-")
    if location:
        name += f"-{location.lower().split(',')[0].strip().replace(' ', '-')}"

    exp_levels = [v for v in str(form.get("experience_levels", "")).split(",") if v.strip()]
    job_types = [v for v in str(form.get("job_types", "")).split(",") if v.strip()]

    return SearchProfile(
        name=name,
        keywords=keywords,
        location=location,
        geo_id=str(form.get("geo_id", "")).strip(),
        distance=float(form.get("distance", 25.0) or 25.0),
        time_filter=str(form.get("time_filter", "r2592000")),
        experience_levels=exp_levels,
        job_types=job_types,
        max_pages=int(form.get("max_pages", 10) or 10),
    )
