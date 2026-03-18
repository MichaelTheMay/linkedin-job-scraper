"""Strategy 3 (last resort): Extract job data from DOM using data-* attributes.

Uses stable attributes (data-entity-urn) rather than volatile CSS classes.
Logs when used as a canary for broken primary extraction.
"""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from data.models import ExtractionStrategy, Job, JobType, WorkplaceType
from monitor.logger import get_logger
from scraper.exceptions import ExtractionFallbackError

log = get_logger("extract.dom")


def extract_from_dom(html: str, job_id: str, url: str) -> Job:
    """Extract job data from page DOM as a last-resort fallback.

    Uses semantic elements and data-* attributes rather than obfuscated CSS classes.
    Raises ExtractionFallbackError if critical fields can't be found.
    """
    soup = BeautifulSoup(html, "html.parser")

    title = _find_title(soup)
    company = _find_company(soup)
    location = _find_location(soup)

    if not title:
        raise ExtractionFallbackError("DOM: could not find job title", url=url)

    job = Job(
        job_id=job_id,
        title=title,
        company=company or "",
        location=location or "",
        url=url,
        extraction_strategy=ExtractionStrategy.DOM_FALLBACK,
        is_partial=not company,
    )

    job.description = _find_description(soup)
    job.workplace_type = _find_workplace_type(soup)
    job.job_type = _find_job_type(soup)
    job.is_easy_apply = _has_easy_apply(soup)
    job.applicant_count = _find_applicant_count(soup)

    log.warning(
        f"DOM fallback used: {title} @ {company}",
        extra={"ctx": {"job_id": job_id}},
    )
    return job


# ---------------------------------------------------------------------------
# Selector helpers — ordered by stability
# ---------------------------------------------------------------------------

# Title selectors (try multiple approaches)
_TITLE_SELECTORS = [
    "h1",  # most job detail pages use h1
    "h2.job-details-jobs-unified-top-card__job-title",
    "[data-test-id='job-title']",
]

# Company selectors
_COMPANY_PATTERNS = [
    lambda s: s.find("a", href=re.compile(r"/company/")),
    lambda s: s.find(attrs={"data-test-id": "job-company-name"}),
]


def _find_title(soup: BeautifulSoup) -> str:
    for selector in _TITLE_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            # Filter out non-title h1s (e.g., "LinkedIn" header)
            if text and len(text) > 3 and text.lower() != "linkedin":
                return text[:200]
    return ""


def _find_company(soup: BeautifulSoup) -> str:
    for pattern_fn in _COMPANY_PATTERNS:
        el = pattern_fn(soup)
        if el:
            text = el.get_text(strip=True)
            if text:
                return text[:200]

    # Fallback: look for company links near the title
    main = soup.find("main")
    if main:
        company_links = main.find_all("a", href=re.compile(r"/company/"))
        for link in company_links:
            text = link.get_text(strip=True)
            if text and len(text) > 1:
                return text[:200]
    return ""


def _find_location(soup: BeautifulSoup) -> str:
    # Look for location patterns in the job details area
    main = soup.find("main")
    if not main:
        return ""

    # Location is often in a span near the company name with city/state pattern
    for span in main.find_all("span"):
        text = span.get_text(strip=True)
        # Match patterns like "Dallas, TX", "Remote", "New York, NY (On-site)"
        if re.match(
            r"^[A-Z][a-zA-Z\s\-]+,?\s*[A-Z]{0,2}\s*(\(.*\))?$", text
        ):
            return text[:200]
        if text.lower() in ("remote", "hybrid", "on-site"):
            return text

    return ""


def _find_description(soup: BeautifulSoup) -> str:
    # Job description is usually in an article or specific div
    desc_el = (
        soup.find("article")
        or soup.find(attrs={"data-test-id": "job-description"})
        or soup.find("div", class_=re.compile(r"description"))
    )
    if desc_el:
        return desc_el.get_text(separator="\n", strip=True)[:10_000]
    return ""


def _find_workplace_type(soup: BeautifulSoup) -> WorkplaceType:
    text = soup.get_text().lower()
    if "remote" in text[:2000]:
        return WorkplaceType.REMOTE
    if "hybrid" in text[:2000]:
        return WorkplaceType.HYBRID
    if "on-site" in text[:2000]:
        return WorkplaceType.ON_SITE
    return WorkplaceType.UNKNOWN


def _find_job_type(soup: BeautifulSoup) -> JobType:
    text = soup.get_text().lower()[:2000]
    mapping = {
        "full-time": JobType.FULL_TIME,
        "part-time": JobType.PART_TIME,
        "contract": JobType.CONTRACT,
        "internship": JobType.INTERNSHIP,
    }
    for pattern, jt in mapping.items():
        if pattern in text:
            return jt
    return JobType.UNKNOWN


def _has_easy_apply(soup: BeautifulSoup) -> bool:
    return bool(soup.find(string=re.compile(r"Easy Apply", re.I)))


def _find_applicant_count(soup: BeautifulSoup) -> Optional[int]:
    for el in soup.find_all(string=re.compile(r"\d+\s*applicant")):
        nums = re.findall(r"(\d[\d,]*)", str(el))
        if nums:
            return int(nums[0].replace(",", ""))
    return None
