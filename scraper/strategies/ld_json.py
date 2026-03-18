"""Strategy 2: Extract job data from <script type="application/ld+json"> tags.

LinkedIn embeds Schema.org JobPosting structured data on public job pages.
This is more stable than CSS selectors and doesn't require API intercept.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from data.models import ExtractionStrategy, Job, JobType
from monitor.logger import get_logger
from scraper.exceptions import ExtractionFallbackError

log = get_logger("extract.ldjson")


def extract_from_ld_json(html: str, job_id: str, url: str) -> Job:
    """Parse ld+json structured data from page HTML.

    Raises ExtractionFallbackError if no suitable ld+json is found.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find all ld+json script tags
    scripts = soup.find_all("script", type="application/ld+json")
    if not scripts:
        raise ExtractionFallbackError("No ld+json scripts found", url=url)

    job_posting = None
    for script in scripts:
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                job_posting = data
                break
            # Sometimes it's wrapped in a list
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        job_posting = item
                        break
        except json.JSONDecodeError:
            continue

    if not job_posting:
        raise ExtractionFallbackError("No JobPosting ld+json found", url=url)

    try:
        title = job_posting.get("title", "")
        company = _extract_company(job_posting)
        location = _extract_location(job_posting)

        if not title:
            raise ExtractionFallbackError("ld+json missing title", url=url)

        job = Job(
            job_id=job_id,
            title=title,
            company=company or "",
            location=location or "",
            url=url,
            extraction_strategy=ExtractionStrategy.LD_JSON,
        )

        job.description = _clean_html(job_posting.get("description", ""))[:10_000]
        job.posted_date = job_posting.get("datePosted", "")
        job.job_type = _parse_employment_type(job_posting.get("employmentType"))
        job.salary_min, job.salary_max = _parse_salary(job_posting)
        job.industries = _parse_list(job_posting.get("industry"))

        log.info(
            f"LD+JSON: {title} @ {company}",
            extra={"ctx": {"job_id": job_id}},
        )
        return job

    except ExtractionFallbackError:
        raise
    except Exception as e:
        raise ExtractionFallbackError(f"ld+json parse error: {e}", url=url) from e


def _extract_company(data: dict) -> str:
    org = data.get("hiringOrganization", {})
    if isinstance(org, dict):
        return org.get("name", "")
    if isinstance(org, str):
        return org
    return ""


def _extract_location(data: dict) -> str:
    loc = data.get("jobLocation", {})
    if isinstance(loc, dict):
        address = loc.get("address", {})
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality", ""),
                address.get("addressRegion", ""),
                address.get("addressCountry", ""),
            ]
            return ", ".join(p for p in parts if p)
    if isinstance(loc, str):
        return loc
    return ""


def _parse_employment_type(val) -> JobType:
    if not val:
        return JobType.UNKNOWN
    mapping = {
        "FULL_TIME": JobType.FULL_TIME,
        "PART_TIME": JobType.PART_TIME,
        "CONTRACT": JobType.CONTRACT,
        "INTERN": JobType.INTERNSHIP,
        "TEMPORARY": JobType.TEMPORARY,
    }
    val_upper = str(val).upper()
    for pattern, jt in mapping.items():
        if pattern in val_upper:
            return jt
    return JobType.UNKNOWN


def _parse_salary(data: dict) -> tuple[float | None, float | None]:
    salary = data.get("baseSalary", {})
    if isinstance(salary, dict):
        value = salary.get("value", {})
        if isinstance(value, dict):
            return (
                _to_float(value.get("minValue")),
                _to_float(value.get("maxValue")),
            )
    return None, None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_list(val) -> list[str]:
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        return [val]
    return []


def _clean_html(text: str) -> str:
    """Strip HTML tags from description text."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()
