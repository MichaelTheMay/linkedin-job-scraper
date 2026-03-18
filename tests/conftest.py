"""Shared test fixtures and mock infrastructure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import ScraperConfig, SearchProfile
from data.models import ExtractionStrategy, Job, JobType, WorkplaceType

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_job() -> Job:
    """A fully populated Job object for testing."""
    return Job(
        job_id="4123456789",
        title="Senior AI Engineer",
        company="Acme Corp",
        location="Dallas, TX (Remote)",
        url="https://www.linkedin.com/jobs/view/4123456789/",
        description="We are looking for a Senior AI Engineer to join our team.",
        salary_min=150000.0,
        salary_max=220000.0,
        salary_currency="USD",
        job_type=JobType.FULL_TIME,
        workplace_type=WorkplaceType.REMOTE,
        seniority_level="Mid-Senior level",
        applicant_count=47,
        posted_date="2026-03-15",
        is_easy_apply=True,
        is_promoted=False,
        industries=["Technology", "Artificial Intelligence"],
        extraction_strategy=ExtractionStrategy.API_INTERCEPT,
    )


@pytest.fixture
def sample_config() -> ScraperConfig:
    """A ScraperConfig with sensible test values."""
    return ScraperConfig(
        li_at_cookie="test_li_at_value",
        jsessionid_cookie="ajax:test_jsessionid",
        headless=True,
        user_data_dir="./test_browser_data",
        output_dir="./test_output",
        output_format="both",
        search_profiles=[
            SearchProfile(
                name="test-search",
                keywords="ai engineer",
                location="Dallas, TX",
                max_pages=2,
            ),
        ],
    )


@pytest.fixture
def mock_page() -> AsyncMock:
    """An async mock of a Playwright Page with common methods stubbed."""
    page = AsyncMock()
    page.url = "https://www.linkedin.com/feed/"
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.content = AsyncMock(return_value="<html><body>mock</body></html>")
    page.evaluate = AsyncMock(return_value=[])
    page.wait_for_selector = AsyncMock()
    page.locator = MagicMock()
    page.locator.return_value.all = AsyncMock(return_value=[])
    page.screenshot = AsyncMock()
    page.close = AsyncMock()
    page.add_init_script = AsyncMock()
    page.route = AsyncMock()
    page.mouse = MagicMock()
    page.mouse.wheel = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    return page


@pytest.fixture
def mock_voyager_response() -> dict:
    """A realistic Voyager API JSON response for a job posting."""
    return {
        "data": {
            "entityUrn": "urn:li:fs_normalized_jobPosting:4123456789",
        },
        "included": [
            {
                "entityUrn": "urn:li:fs_normalized_jobPosting:4123456789",
                "$type": "com.linkedin.voyager.jobs.JobPosting",
                "title": "Senior AI Engineer",
                "companyName": "Acme Corp",
                "formattedLocation": "Dallas, TX",
                "description": {"text": "Build cutting-edge AI systems."},
                "formattedEmploymentStatus": "Full-time",
                "workplaceType": "Remote",
                "formattedExperienceLevel": "Mid-Senior level",
                "applicantCount": 47,
                "listedAt": "2026-03-15",
                "applyMethod": {"easyApplyUrl": "https://linkedin.com/easy-apply/123"},
            },
        ],
    }


@pytest.fixture
def job_detail_html() -> str:
    """Load the job detail HTML fixture."""
    path = FIXTURES_DIR / "job_detail.html"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return "<html><body><h1>Test Job</h1></body></html>"


@pytest.fixture
def search_page_html() -> str:
    """Load the search page HTML fixture."""
    path = FIXTURES_DIR / "search_page.html"
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return "<html><body><div>No results</div></body></html>"
