"""HTML page routes — served via Jinja2 templates."""

from __future__ import annotations

from fastapi import APIRouter, Request

from db.repository import JobRepository
from server.app import scrape_status, templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    """Main search configuration page."""
    repo = JobRepository()
    profiles = repo.list_profiles()
    status_counts = repo.get_status_counts()
    total = repo.count_jobs()
    recent_runs = repo.list_scrape_runs(limit=5)
    repo.close()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "profiles": profiles,
            "status_counts": status_counts,
            "total_jobs": total,
            "recent_runs": recent_runs,
            "scrape_status": scrape_status,
        },
    )


@router.get("/jobs")
async def jobs_page(
    request: Request,
    status: str = "all",
    search: str = "",
    sort: str = "first_seen_at",
    dir: str = "DESC",
    page: int = 1,
):
    """Job listing table with filters."""
    repo = JobRepository()
    per_page = 50
    offset = (page - 1) * per_page
    jobs = repo.list_jobs(
        status=status if status != "all" else None,
        search=search or None,
        sort_by=sort,
        sort_dir=dir,
        limit=per_page,
        offset=offset,
    )
    total = repo.count_jobs(status=status if status != "all" else None)
    status_counts = repo.get_status_counts()
    repo.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        "jobs.html",
        {
            "request": request,
            "jobs": jobs,
            "status_filter": status,
            "search": search,
            "sort": sort,
            "dir": dir,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "status_counts": status_counts,
        },
    )


@router.get("/pipeline")
async def pipeline_page(request: Request):
    """Pipeline / Kanban board view."""
    repo = JobRepository()
    status_counts = repo.get_status_counts()
    statuses = ["discovered", "interested", "applied", "interviewing", "offer", "rejected"]
    columns: dict[str, list] = {}
    for s in statuses:
        columns[s] = repo.list_jobs(status=s, limit=100)
    repo.close()
    return templates.TemplateResponse(
        "pipeline.html",
        {
            "request": request,
            "columns": columns,
            "statuses": statuses,
            "status_counts": status_counts,
        },
    )
