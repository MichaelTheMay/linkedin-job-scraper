"""Integration tests — full pipeline with mocked Playwright.

These tests exercise the complete scrape flow (config → search → extract → clean
→ dedup → export) using mock browser interactions. No real LinkedIn session needed.
"""

from __future__ import annotations

import json
from pathlib import Path

from browser.interceptor import NetworkInterceptor
from config.settings import SearchProfile
from data.cleaner import clean_job
from data.deduplicator import Deduplicator
from data.exporter import Exporter
from data.models import ExtractionStrategy, Job
from monitor.health import HealthTracker
from scraper.job_detail import _extract_job_id
from scraper.job_search import _build_guest_search_url, build_search_url
from scraper.strategies.api_intercept import extract_from_api
from scraper.strategies.dom_fallback import extract_from_dom
from scraper.strategies.ld_json import extract_from_ld_json


class TestFullPipeline:
    """End-to-end pipeline: config → search → extract → clean → dedup → export."""

    def test_full_pipeline_with_dom_extraction(self, tmp_path):
        """Extract from HTML → clean → dedup → export CSV and JSON."""
        html = """
        <html><body><main>
            <h1>ML Engineer</h1>
            <a href="/company/techco/">TechCo</a>
            <span>Austin, TX (Remote)</span>
            <button>Easy Apply</button>
            <span>23 applicants</span>
            <div class="description">Build ML systems for production.</div>
        </main></body></html>
        """

        # Extract
        job = extract_from_dom(html, "999", "https://www.linkedin.com/jobs/view/999/")
        assert job.title == "ML Engineer"
        assert job.company == "TechCo"
        assert job.extraction_strategy == ExtractionStrategy.DOM_FALLBACK

        # Clean
        job = clean_job(job)
        assert job.title == "ML Engineer"
        assert not job.is_partial

        # Dedup
        dedup = Deduplicator()
        assert not dedup.is_duplicate(job)
        dedup.mark_seen(job)
        assert dedup.is_duplicate(job)

        # Export
        exporter = Exporter(str(tmp_path), "both")
        output_path = exporter.save_jobs([job], "test")
        assert output_path
        assert Path(output_path).exists()

        # Verify CSV content
        csv_files = list(tmp_path.glob("*.csv"))
        assert len(csv_files) == 1
        content = csv_files[0].read_text()
        assert "ML Engineer" in content
        assert "TechCo" in content

        # Verify JSON content
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data["metadata"]["total_jobs"] == 1
        assert data["jobs"][0]["title"] == "ML Engineer"

    def test_pipeline_with_ld_json_extraction(self, tmp_path):
        """Full pipeline using LD+JSON strategy."""
        ld_json_data = {
            "@type": "JobPosting",
            "title": "Data Scientist",
            "hiringOrganization": {"name": "DataCorp"},
            "jobLocation": {
                "address": {
                    "addressLocality": "NYC",
                    "addressRegion": "NY",
                    "addressCountry": "US",
                }
            },
            "baseSalary": {"value": {"minValue": 130000, "maxValue": 180000}},
            "employmentType": "FULL_TIME",
            "datePosted": "2026-03-10",
        }
        html = f"""
        <html><head>
        <script type="application/ld+json">{json.dumps(ld_json_data)}</script>
        </head><body></body></html>
        """

        job = extract_from_ld_json(html, "555", "https://www.linkedin.com/jobs/view/555/")
        job = clean_job(job)

        assert job.title == "Data Scientist"
        assert job.salary_min == 130000
        assert job.extraction_strategy == ExtractionStrategy.LD_JSON

        exporter = Exporter(str(tmp_path), "csv")
        path = exporter.save_jobs([job], "ld-test")
        assert Path(path).exists()

    def test_pipeline_with_api_intercept(self, tmp_path, mock_voyager_response):
        """Full pipeline using API intercept strategy."""
        api_data = mock_voyager_response["included"][0]
        job = extract_from_api(
            api_data, "4123456789", "https://www.linkedin.com/jobs/view/4123456789/"
        )
        job = clean_job(job)

        assert job.title == "Senior AI Engineer"
        assert job.company == "Acme Corp"
        assert job.extraction_strategy == ExtractionStrategy.API_INTERCEPT

        exporter = Exporter(str(tmp_path), "json")
        path = exporter.save_jobs([job], "api-test")
        data = json.loads(Path(path).read_text())
        assert data["jobs"][0]["extraction_strategy"] == "api_intercept"

    def test_dedup_across_strategies(self):
        """Same job extracted by different strategies should be deduped."""
        dedup = Deduplicator()

        job_api = Job(
            job_id="123",
            title="Engineer",
            company="Acme",
            location="TX",
            url="u",
            extraction_strategy=ExtractionStrategy.API_INTERCEPT,
        )
        dedup.mark_seen(job_api)

        job_dom = Job(
            job_id="123",
            title="Engineer",
            company="Acme",
            location="TX",
            url="u",
            extraction_strategy=ExtractionStrategy.DOM_FALLBACK,
        )
        assert dedup.is_duplicate(job_dom)

    def test_multiple_jobs_export(self, tmp_path):
        """Export multiple jobs and verify all appear."""
        jobs = []
        for i in range(10):
            jobs.append(
                Job(
                    job_id=str(i),
                    title=f"Job Title {i}",
                    company=f"Company {i}",
                    location="Dallas, TX",
                    url=f"https://www.linkedin.com/jobs/view/{i}/",
                )
            )

        exporter = Exporter(str(tmp_path), "both")
        exporter.save_jobs(jobs, "multi")

        csv_files = list(tmp_path.glob("*.csv"))
        json_files = list(tmp_path.glob("*.json"))
        assert len(csv_files) == 1
        assert len(json_files) == 1

        data = json.loads(json_files[0].read_text())
        assert data["metadata"]["total_jobs"] == 10


class TestSearchUrlBuilder:
    """Test search URL construction."""

    def test_basic_url(self):
        profile = SearchProfile(name="test", keywords="python developer")
        url = build_search_url(profile)
        assert "keywords=python+developer" in url
        assert "linkedin.com/jobs/search" in url

    def test_url_with_all_params(self):
        profile = SearchProfile(
            name="full",
            keywords="ai engineer",
            location="Dallas, TX",
            geo_id="103644278",
            distance=50.0,
            time_filter="r86400",
            experience_levels=["3", "4"],
            job_types=["F", "C"],
        )
        url = build_search_url(profile, start=25)
        assert "keywords=ai+engineer" in url
        assert "location=Dallas" in url
        assert "geoId=103644278" in url
        assert "distance=50.0" in url
        assert "f_TPR=r86400" in url
        assert "f_E=3%2C4" in url
        assert "f_JT=F%2CC" in url
        assert "start=25" in url

    def test_guest_api_url(self):
        profile = SearchProfile(name="test", keywords="data scientist", location="NYC")
        url = _build_guest_search_url(profile, start=25)
        assert "jobs-guest/jobs/api/seeMoreJobPostings/search" in url
        assert "keywords=data+scientist" in url
        assert "location=NYC" in url
        assert "start=25" in url

    def test_guest_url_does_not_include_origin(self):
        profile = SearchProfile(name="test", keywords="engineer")
        url = _build_guest_search_url(profile)
        assert "origin=" not in url


class TestJobIdExtraction:
    """Test job ID parsing from various URL formats."""

    def test_standard_url(self):
        assert _extract_job_id("https://www.linkedin.com/jobs/view/4123456789/") == "4123456789"

    def test_url_with_query_params(self):
        url = "https://www.linkedin.com/jobs/view/4123456789/?trk=public_jobs"
        assert _extract_job_id(url) == "4123456789"

    def test_urn_format(self):
        assert _extract_job_id("urn:li:jobPosting:4123456789") == "4123456789"

    def test_unknown_format(self):
        assert _extract_job_id("https://example.com/unknown") == "unknown"


class TestHealthTracker:
    """Test health monitoring and abort logic."""

    def test_records_requests(self):
        h = HealthTracker()
        h.record_request()
        h.record_request()
        assert h.requests_made == 2
        assert h.consecutive_errors == 0

    def test_records_errors(self):
        h = HealthTracker()
        h.record_error("PageLoadError")
        h.record_error("PageLoadError")
        assert h.errors_by_type["PageLoadError"] == 2
        assert h.consecutive_errors == 2

    def test_resets_consecutive_on_success(self):
        h = HealthTracker()
        h.record_error("PageLoadError")
        h.record_error("PageLoadError")
        h.record_request()
        assert h.consecutive_errors == 0

    def test_aborts_on_consecutive_errors(self):
        h = HealthTracker()
        for _ in range(5):
            h.record_error("PageLoadError")
        assert h.should_abort()

    def test_aborts_on_rate_limits(self):
        h = HealthTracker()
        for _ in range(3):
            h.record_error("RateLimitError")
        assert h.should_abort()

    def test_no_abort_on_mixed_errors(self):
        h = HealthTracker()
        h.record_error("PageLoadError")
        h.record_request()
        h.record_error("ExtractionError")
        h.record_request()
        assert not h.should_abort()


class TestProgressSaveResume:
    """Test that progress saving works correctly."""

    def test_progress_save(self, tmp_path):
        exporter = Exporter(str(tmp_path), "csv")
        jobs = [
            Job(job_id="1", title="Job 1", company="Co", location="TX", url="u1"),
            Job(job_id="2", title="Job 2", company="Co", location="TX", url="u2"),
        ]
        exporter.save_progress(jobs)

        progress_file = tmp_path / "jobs_partial.csv"
        assert progress_file.exists()
        content = progress_file.read_text()
        assert "Job 1" in content
        assert "Job 2" in content

    def test_progress_overwrites(self, tmp_path):
        exporter = Exporter(str(tmp_path), "csv")

        # Save 2 jobs
        jobs1 = [
            Job(job_id="1", title="Job 1", company="Co", location="TX", url="u1"),
            Job(job_id="2", title="Job 2", company="Co", location="TX", url="u2"),
        ]
        exporter.save_progress(jobs1)

        # Save 3 jobs (should overwrite)
        jobs2 = jobs1 + [
            Job(job_id="3", title="Job 3", company="Co", location="TX", url="u3"),
        ]
        exporter.save_progress(jobs2)

        progress_file = tmp_path / "jobs_partial.csv"
        content = progress_file.read_text()
        assert "Job 3" in content


class TestNetworkInterceptor:
    """Test API response capture and search."""

    def test_find_job_data(self):
        interceptor = NetworkInterceptor()
        interceptor._captured_responses.append(
            {
                "url": "https://www.linkedin.com/voyager/api/jobs/123",
                "data": {
                    "included": [
                        {"entityUrn": "urn:li:fs_normalized_jobPosting:123", "title": "Test Job"}
                    ]
                },
                "status": 200,
            }
        )

        result = interceptor.find_job_data("123")
        assert result is not None
        assert result["title"] == "Test Job"

    def test_find_job_data_not_found(self):
        interceptor = NetworkInterceptor()
        assert interceptor.find_job_data("999") is None

    def test_clear(self):
        interceptor = NetworkInterceptor()
        interceptor._captured_responses.append({"url": "test", "data": {}, "status": 200})
        interceptor.clear()
        assert len(interceptor.responses) == 0

    def test_find_search_results(self):
        interceptor = NetworkInterceptor()
        interceptor._captured_responses.append(
            {
                "url": "https://www.linkedin.com/voyager/api/search",
                "data": {
                    "included": [
                        {
                            "entityUrn": "urn:li:fs_miniJob:111",
                            "$type": "com.linkedin.voyager.jobs.fs_miniJob",
                        },
                        {
                            "entityUrn": "urn:li:fs_company:222",
                            "$type": "com.linkedin.voyager.entities.Company",
                        },
                    ]
                },
                "status": 200,
            }
        )

        results = interceptor.find_job_search_results()
        assert len(results) == 1
        assert "111" in results[0]["entityUrn"]
