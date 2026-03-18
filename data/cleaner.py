"""Data cleaning — normalize fields, strip UI noise, validate."""

from __future__ import annotations

import re

from data.models import Job
from monitor.logger import get_logger

log = get_logger("cleaner")

# UI text that gets mixed into descriptions via DOM extraction
UI_NOISE_PATTERNS = [
    r"Easy Apply",
    r"Save",
    r"Use AI to assess how you fit",
    r"Get AI-powered advice.*?Premium\.",
    r"Reactivate Premium.*?Off",
    r"Show match details",
    r"Tailor my resume",
    r"Help me stand out",
    r"People you can reach out to",
    r"School alumni from.*",
    r"Show all",
    r"Meet the hiring team",
    r"Job poster",
    r"Message",
    r"About the job",
    r"How you match",
    r"Skills.*associated with this job",
    r"^\d+ applicants?\s*$",
    r"^Promoted by hirer\s*[·]?\s*$",
    r"^Actively reviewing applicants\s*$",
    r"^BETA.*helpful\?\s*$",
]


def clean_job(job: Job) -> Job:
    """Clean and normalize a job's fields in-place."""
    job.title = _clean_text(job.title)
    job.company = _clean_text(job.company)
    job.location = _clean_text(job.location)
    job.description = _clean_description(job.description)

    # Validate required fields
    if not job.title:
        log.warning(f"Job {job.job_id}: missing title after cleaning")
        job.is_partial = True
    if not job.company:
        log.warning(f"Job {job.job_id}: missing company after cleaning")
        job.is_partial = True

    return job


def _clean_text(text: str) -> str:
    """Basic text normalization."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text[:500]


def _clean_description(text: str) -> str:
    """Remove LinkedIn UI noise from description text."""
    if not text:
        return ""

    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip UI noise lines
        is_noise = False
        for pattern in UI_NOISE_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                is_noise = True
                break
        if not is_noise:
            cleaned_lines.append(stripped)

    result = "\n".join(cleaned_lines)
    return result[:10_000]
