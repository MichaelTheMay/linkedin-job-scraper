"""FastAPI application — serves the web UI and API endpoints."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db.database import init_db
from monitor.logger import get_logger

log = get_logger("server")

# Scrape lock — prevents concurrent scrapes
scrape_lock = asyncio.Lock()
scrape_status: dict = {"running": False, "message": ""}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    init_db()
    log.info("Database initialized")
    yield


app = FastAPI(title="LinkedIn Job Scraper", lifespan=lifespan)

# Static files and templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def register_routes() -> None:
    """Register all route modules. Called after app is created."""
    from server.routes.api_jobs import router as jobs_router  # noqa: E402
    from server.routes.api_search import router as search_router  # noqa: E402
    from server.routes.pages import router as pages_router  # noqa: E402

    app.include_router(pages_router)
    app.include_router(search_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")


register_routes()
