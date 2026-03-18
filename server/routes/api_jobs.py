"""API routes for job CRUD, pipeline updates, export, and AI stubs."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from db.repository import JobRepository
from monitor.logger import get_logger
from server.app import templates

log = get_logger("api.jobs")

router = APIRouter(tags=["jobs"])


@router.patch("/jobs/{pk}/status", response_class=HTMLResponse)
async def update_status(pk: int, request: Request):
    """Update a job's pipeline status. Returns the updated row partial."""
    form = await request.form()
    status = str(form.get("status", "discovered"))
    notes = form.get("notes")

    repo = JobRepository()
    repo.update_job_status(pk, status, notes=str(notes) if notes else None)
    job = repo.get_job_by_pk(pk)
    repo.close()

    if not job:
        return HTMLResponse('<tr><td colspan="8">Job not found</td></tr>', status_code=404)

    return templates.TemplateResponse("partials/job_row.html", {"request": request, "job": job})


@router.get("/jobs/{pk}/detail", response_class=HTMLResponse)
async def job_detail(pk: int, request: Request):
    """Get the expandable detail panel for a job."""
    repo = JobRepository()
    job = repo.get_job_by_pk(pk)
    repo.close()

    if not job:
        return HTMLResponse("<div>Job not found</div>", status_code=404)

    return templates.TemplateResponse("partials/job_detail.html", {"request": request, "job": job})


@router.get("/jobs/export")
async def export_csv(status: str = "all", search: str = ""):
    """Export jobs as CRM-friendly CSV with tracking columns."""
    repo = JobRepository()
    jobs = repo.list_jobs(
        status=status if status != "all" else None,
        search=search or None,
        limit=10000,
    )
    repo.close()

    output = io.StringIO()
    writer = csv.writer(output)

    # CRM-friendly headers
    writer.writerow(
        [
            "Job ID",
            "Title",
            "Company",
            "Location",
            "URL",
            "Job Type",
            "Seniority Level",
            "Applicant Count",
            "Posted Date",
            "Salary",
            "Status",
            "Notes",
            "Applied Date",
            "Response Date",
            "Description",
            "Industries",
            "Badge",
            "Hiring Manager",
            "Apply URL",
            "Easy Apply",
            "First Seen",
            "Last Seen",
        ]
    )

    for job in jobs:
        writer.writerow(
            [
                job["job_id"],
                job["title"],
                job["company"],
                job["location"],
                job["url"],
                job["job_type"],
                job["seniority_level"],
                job["applicant_count"] or "",
                job["posted_date"] or "",
                job["salary_raw"],
                job["status"],
                job["notes"],
                job["applied_date"] or "",
                job["response_date"] or "",
                job["description"][:5000],
                job["industries"],
                job["badge"],
                job["hiring_manager"],
                job["apply_url"],
                job["is_easy_apply"],
                job["first_seen_at"],
                job["last_seen_at"],
            ]
        )

    output.seek(0)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=jobs_export_{timestamp}.csv"},
    )


# ------------------------------------------------------------------
# AI Generator Stubs (wired but no logic)
# ------------------------------------------------------------------


def _ai_stub(title: str, description: str, job_id: str) -> str:
    """Render a placeholder HTML card for an unimplemented AI feature."""
    return (
        '<div class="p-4 bg-gray-100 rounded border">'
        f'<p class="font-semibold text-gray-600">{title}</p>'
        f'<p class="text-gray-500 text-sm mt-2">{description}</p>'
        f'<p class="text-xs text-gray-400 mt-2">Job ID: {job_id}</p>'
        "</div>"
    )


@router.post("/ai/cover-letter", response_class=HTMLResponse)
async def generate_cover_letter(request: Request):
    """Stub: Generate a cover letter based on job description."""
    form = await request.form()
    return HTMLResponse(
        _ai_stub(
            "Cover Letter Generator",
            "AI cover letter generation is not yet implemented. "
            "When built, this will analyze the job description and "
            "generate a personalized cover letter based on your resume.",
            str(form.get("job_id", "")),
        )
    )


@router.post("/ai/hiring-email", response_class=HTMLResponse)
async def generate_hiring_email(request: Request):
    """Stub: Generate a cold email to the hiring manager."""
    form = await request.form()
    return HTMLResponse(
        _ai_stub(
            "Hiring Manager Email Generator",
            "AI email generation is not yet implemented. "
            "When built, this will draft a personalized cold email "
            "to the hiring manager referencing specific job requirements.",
            str(form.get("job_id", "")),
        )
    )


@router.post("/ai/linkedin-dm", response_class=HTMLResponse)
async def generate_linkedin_dm(request: Request):
    """Stub: Generate a LinkedIn DM to the hiring manager."""
    form = await request.form()
    return HTMLResponse(
        _ai_stub(
            "LinkedIn DM Generator",
            "AI LinkedIn message generation is not yet implemented. "
            "When built, this will create a concise, professional "
            "LinkedIn connection request or InMail referencing the role.",
            str(form.get("job_id", "")),
        )
    )
