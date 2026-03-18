"""Typed data models for scraped job data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ExtractionStrategy(str, Enum):
    """Which strategy successfully extracted this job's data."""

    API_INTERCEPT = "api_intercept"
    LD_JSON = "ld_json"
    DOM_FALLBACK = "dom_fallback"
    UNKNOWN = "unknown"


class JobType(str, Enum):
    FULL_TIME = "Full-time"
    PART_TIME = "Part-time"
    CONTRACT = "Contract"
    INTERNSHIP = "Internship"
    TEMPORARY = "Temporary"
    VOLUNTEER = "Volunteer"
    OTHER = "Other"
    UNKNOWN = "Unknown"


class WorkplaceType(str, Enum):
    ON_SITE = "On-site"
    REMOTE = "Remote"
    HYBRID = "Hybrid"
    UNKNOWN = "Unknown"


@dataclass
class Job:
    """A single scraped job listing."""

    job_id: str
    title: str
    company: str
    location: str
    url: str

    # Optional enriched fields
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "USD"
    job_type: JobType = JobType.UNKNOWN
    workplace_type: WorkplaceType = WorkplaceType.UNKNOWN
    seniority_level: str = ""
    applicant_count: int | None = None
    posted_date: str | None = None
    is_easy_apply: bool = False
    is_promoted: bool = False
    company_logo_url: str = ""
    industries: list[str] = field(default_factory=list)

    # Metadata
    extraction_strategy: ExtractionStrategy = ExtractionStrategy.UNKNOWN
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    is_partial: bool = False  # True if some fields failed extraction

    def to_dict(self) -> dict:
        """Serialize to a flat dict suitable for CSV/JSON export."""
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "job_type": self.job_type.value,
            "workplace_type": self.workplace_type.value,
            "seniority_level": self.seniority_level,
            "applicant_count": self.applicant_count,
            "posted_date": self.posted_date,
            "is_easy_apply": self.is_easy_apply,
            "is_promoted": self.is_promoted,
            "industries": "; ".join(self.industries) if self.industries else "",
            "extraction_strategy": self.extraction_strategy.value,
            "extracted_at": self.extracted_at,
        }

    @property
    def csv_headers(self) -> list[str]:
        return list(self.to_dict().keys())


@dataclass
class ScrapeResult:
    """Summary of a scrape run."""

    search_profile: str
    total_urls_found: int = 0
    total_jobs_extracted: int = 0
    total_duplicates_skipped: int = 0
    total_errors: int = 0
    extraction_strategy_counts: dict[str, int] = field(default_factory=dict)
    partial_extractions: int = 0
    elapsed_seconds: float = 0.0
    output_file: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
