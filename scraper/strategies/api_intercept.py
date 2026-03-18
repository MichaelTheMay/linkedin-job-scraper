"""Strategy 1: Extract job data from captured Voyager API responses.

This is the most reliable method — structured JSON with stable field names.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from data.models import ExtractionStrategy, Job, JobType, WorkplaceType
from monitor.logger import get_logger
from scraper.exceptions import ExtractionFallbackError

log = get_logger("extract.api")


def extract_from_api(api_data: dict[str, Any], job_id: str, url: str) -> Job:
    """Parse a Voyager API response dict into a Job model.

    Raises ExtractionFallbackError if the data is insufficient.
    """
    if not api_data:
        raise ExtractionFallbackError("No API data available", url=url)

    try:
        title = _extract_field(api_data, ["title", "jobPostingTitle"])
        company = _extract_company(api_data)
        location = _extract_field(api_data, [
            "formattedLocation", "locationName", "location",
        ])

        if not title or not company:
            raise ExtractionFallbackError(
                f"Missing required fields: title={title!r}, company={company!r}",
                url=url,
            )

        job = Job(
            job_id=job_id,
            title=title,
            company=company,
            location=location or "",
            url=url,
            extraction_strategy=ExtractionStrategy.API_INTERCEPT,
        )

        # Enrich with optional fields
        job.description = _extract_description(api_data)
        job.job_type = _extract_job_type(api_data)
        job.workplace_type = _extract_workplace_type(api_data)
        job.seniority_level = _extract_field(api_data, [
            "formattedExperienceLevel", "experienceLevel",
        ]) or ""
        job.applicant_count = _extract_applicant_count(api_data)
        job.posted_date = _extract_field(api_data, [
            "listedAt", "originalListedAt", "postedDate",
        ]) or ""
        job.is_easy_apply = _extract_bool(api_data, [
            "applyMethod", "easyApplyUrl",
        ])
        job.is_promoted = _extract_bool(api_data, ["isPromoted", "promoted"])
        job.salary_min, job.salary_max = _extract_salary(api_data)

        industries_raw = api_data.get("formattedIndustries") or api_data.get(
            "industries", []
        )
        if isinstance(industries_raw, list):
            job.industries = [str(i) for i in industries_raw]

        log.info(
            f"API intercept: {title} @ {company}",
            extra={"ctx": {"job_id": job_id}},
        )
        return job

    except ExtractionFallbackError:
        raise
    except Exception as e:
        raise ExtractionFallbackError(
            f"API parse error: {e}", url=url
        ) from e


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------


def _extract_field(data: dict, keys: list[str]) -> Optional[str]:
    """Try multiple possible keys, return first non-empty string value."""
    for key in keys:
        val = _deep_get(data, key)
        if val and isinstance(val, str):
            return val.strip()
        # Handle nested dicts with text field
        if isinstance(val, dict) and "text" in val:
            return val["text"].strip()
    return None


def _extract_company(data: dict) -> str:
    """Extract company name from various Voyager response structures."""
    # Direct field
    for key in ["companyName", "companyResolutionResult"]:
        val = data.get(key)
        if isinstance(val, str) and val:
            return val.strip()
        if isinstance(val, dict):
            name = val.get("name") or val.get("companyName")
            if name:
                return name.strip()

    # Nested in company resolve
    company_data = data.get("companyDetails", {})
    if isinstance(company_data, dict):
        resolved = company_data.get("company") or company_data.get(
            "companyResolutionResult"
        )
        if isinstance(resolved, dict):
            name = resolved.get("name")
            if name:
                return name.strip()

    return ""


def _extract_description(data: dict) -> str:
    """Extract job description text."""
    desc = data.get("description") or data.get("jobPostingDescription")
    if isinstance(desc, dict):
        return desc.get("text", "")[:10_000]
    if isinstance(desc, str):
        return desc[:10_000]
    return ""


def _extract_job_type(data: dict) -> JobType:
    mapping = {
        "full-time": JobType.FULL_TIME,
        "part-time": JobType.PART_TIME,
        "contract": JobType.CONTRACT,
        "internship": JobType.INTERNSHIP,
        "temporary": JobType.TEMPORARY,
    }
    for key in ["formattedEmploymentStatus", "employmentStatus", "jobType"]:
        val = _deep_get(data, key)
        if val:
            val_lower = str(val).lower()
            for pattern, jt in mapping.items():
                if pattern in val_lower:
                    return jt
    return JobType.UNKNOWN


def _extract_workplace_type(data: dict) -> WorkplaceType:
    mapping = {
        "remote": WorkplaceType.REMOTE,
        "on-site": WorkplaceType.ON_SITE,
        "hybrid": WorkplaceType.HYBRID,
    }
    for key in ["workplaceType", "formattedWorkplaceType", "workRemoteAllowed"]:
        val = _deep_get(data, key)
        if val is True:
            return WorkplaceType.REMOTE
        if val:
            val_lower = str(val).lower()
            for pattern, wt in mapping.items():
                if pattern in val_lower:
                    return wt
    return WorkplaceType.UNKNOWN


def _extract_applicant_count(data: dict) -> Optional[int]:
    for key in ["applicantCount", "formattedApplicantCount"]:
        val = data.get(key)
        if isinstance(val, int):
            return val
        if isinstance(val, str):
            nums = re.findall(r"\d+", val.replace(",", ""))
            if nums:
                return int(nums[0])
    return None


def _extract_salary(data: dict) -> tuple[Optional[float], Optional[float]]:
    """Extract salary range from API data."""
    salary_data = data.get("salaryInsights") or data.get("salary") or {}
    if isinstance(salary_data, dict):
        min_val = salary_data.get("minSalary") or salary_data.get("compensationMin")
        max_val = salary_data.get("maxSalary") or salary_data.get("compensationMax")
        if min_val or max_val:
            return (
                float(min_val) if min_val else None,
                float(max_val) if max_val else None,
            )
    return None, None


def _extract_bool(data: dict, keys: list[str]) -> bool:
    for key in keys:
        val = _deep_get(data, key)
        if val:
            return True
    return False


def _deep_get(data: dict, key: str) -> Any:
    """Get a value by key, searching nested dicts one level deep."""
    if key in data:
        return data[key]
    for v in data.values():
        if isinstance(v, dict) and key in v:
            return v[key]
    return None
