"""Tests for LD+JSON extraction strategy."""

import json

import pytest
from data.models import ExtractionStrategy, JobType
from scraper.exceptions import ExtractionFallbackError
from scraper.strategies.ld_json import extract_from_ld_json


def _make_html(ld_json_data: dict) -> str:
    """Create minimal HTML with an embedded ld+json script tag."""
    return f"""
    <html><head>
    <script type="application/ld+json">{json.dumps(ld_json_data)}</script>
    </head><body></body></html>
    """


class TestLdJsonExtraction:
    def test_extracts_basic_fields(self):
        data = {
            "@type": "JobPosting",
            "title": "Senior AI Engineer",
            "hiringOrganization": {"name": "TechCorp"},
            "jobLocation": {
                "address": {
                    "addressLocality": "Dallas",
                    "addressRegion": "TX",
                    "addressCountry": "US",
                }
            },
            "datePosted": "2026-03-01",
        }
        html = _make_html(data)
        job = extract_from_ld_json(html, "12345", "https://example.com/jobs/view/12345/")

        assert job.title == "Senior AI Engineer"
        assert job.company == "TechCorp"
        assert job.location == "Dallas, TX, US"
        assert job.posted_date == "2026-03-01"
        assert job.extraction_strategy == ExtractionStrategy.LD_JSON

    def test_extracts_salary(self):
        data = {
            "@type": "JobPosting",
            "title": "Engineer",
            "hiringOrganization": {"name": "Co"},
            "baseSalary": {
                "value": {"minValue": 120000, "maxValue": 180000}
            },
        }
        job = extract_from_ld_json(_make_html(data), "1", "u")
        assert job.salary_min == 120000
        assert job.salary_max == 180000

    def test_extracts_employment_type(self):
        data = {
            "@type": "JobPosting",
            "title": "Engineer",
            "hiringOrganization": {"name": "Co"},
            "employmentType": "FULL_TIME",
        }
        job = extract_from_ld_json(_make_html(data), "1", "u")
        assert job.job_type == JobType.FULL_TIME

    def test_cleans_html_description(self):
        data = {
            "@type": "JobPosting",
            "title": "Engineer",
            "hiringOrganization": {"name": "Co"},
            "description": "<p>We need an <strong>AI</strong> engineer.</p>",
        }
        job = extract_from_ld_json(_make_html(data), "1", "u")
        assert "<" not in job.description
        assert "AI" in job.description

    def test_raises_on_no_ld_json(self):
        html = "<html><body>No scripts here</body></html>"
        with pytest.raises(ExtractionFallbackError, match="No ld.json"):
            extract_from_ld_json(html, "1", "u")

    def test_raises_on_non_job_posting_ld_json(self):
        data = {"@type": "Organization", "name": "Acme"}
        with pytest.raises(ExtractionFallbackError, match="No JobPosting"):
            extract_from_ld_json(_make_html(data), "1", "u")

    def test_raises_on_missing_title(self):
        data = {
            "@type": "JobPosting",
            "hiringOrganization": {"name": "Co"},
        }
        with pytest.raises(ExtractionFallbackError, match="missing title"):
            extract_from_ld_json(_make_html(data), "1", "u")
