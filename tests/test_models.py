"""Tests for data models."""

import pytest
from data.models import ExtractionStrategy, Job, JobType, ScrapeResult, WorkplaceType


class TestJob:
    def test_default_values(self):
        job = Job(
            job_id="123",
            title="Engineer",
            company="Acme",
            location="Dallas, TX",
            url="https://linkedin.com/jobs/view/123/",
        )
        assert job.job_type == JobType.UNKNOWN
        assert job.workplace_type == WorkplaceType.UNKNOWN
        assert job.extraction_strategy == ExtractionStrategy.UNKNOWN
        assert job.is_partial is False
        assert job.salary_min is None

    def test_to_dict(self):
        job = Job(
            job_id="456",
            title="AI Engineer",
            company="OpenAI",
            location="SF",
            url="https://linkedin.com/jobs/view/456/",
            salary_min=150000,
            salary_max=200000,
            job_type=JobType.FULL_TIME,
            workplace_type=WorkplaceType.REMOTE,
            extraction_strategy=ExtractionStrategy.API_INTERCEPT,
        )
        d = job.to_dict()
        assert d["job_id"] == "456"
        assert d["salary_min"] == 150000
        assert d["job_type"] == "Full-time"
        assert d["workplace_type"] == "Remote"
        assert d["extraction_strategy"] == "api_intercept"

    def test_to_dict_has_all_expected_keys(self):
        job = Job(
            job_id="1", title="T", company="C", location="L",
            url="https://example.com",
        )
        d = job.to_dict()
        expected_keys = {
            "job_id", "title", "company", "location", "url", "description",
            "salary_min", "salary_max", "salary_currency", "job_type",
            "workplace_type", "seniority_level", "applicant_count",
            "posted_date", "is_easy_apply", "is_promoted", "industries",
            "extraction_strategy", "extracted_at",
        }
        assert set(d.keys()) == expected_keys

    def test_industries_serialization(self):
        job = Job(
            job_id="1", title="T", company="C", location="L",
            url="u", industries=["AI", "Tech"],
        )
        assert job.to_dict()["industries"] == "AI; Tech"


class TestScrapeResult:
    def test_default_values(self):
        result = ScrapeResult(search_profile="test")
        assert result.total_urls_found == 0
        assert result.total_jobs_extracted == 0
        assert result.extraction_strategy_counts == {}
