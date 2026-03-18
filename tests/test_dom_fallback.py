"""Tests for DOM fallback extraction strategy."""

import pytest
from data.models import ExtractionStrategy, JobType, WorkplaceType
from scraper.exceptions import ExtractionFallbackError
from scraper.strategies.dom_fallback import extract_from_dom


class TestDomFallback:
    def test_extracts_h1_title(self):
        html = """
        <html><body><main>
            <h1>Senior ML Engineer</h1>
            <a href="/company/acme/">Acme Corp</a>
            <span>Dallas, TX</span>
        </main></body></html>
        """
        job = extract_from_dom(html, "123", "https://example.com/jobs/view/123/")
        assert job.title == "Senior ML Engineer"
        assert job.company == "Acme Corp"
        assert job.extraction_strategy == ExtractionStrategy.DOM_FALLBACK

    def test_extracts_company_from_link(self):
        html = """
        <html><body><main>
            <h1>Data Scientist</h1>
            <a href="/company/openai/">OpenAI</a>
        </main></body></html>
        """
        job = extract_from_dom(html, "1", "u")
        assert job.company == "OpenAI"

    def test_detects_remote_workplace(self):
        html = """
        <html><body><main>
            <h1>Engineer</h1>
            <a href="/company/x/">X Corp</a>
            <span>Remote</span>
        </main></body></html>
        """
        job = extract_from_dom(html, "1", "u")
        assert job.workplace_type == WorkplaceType.REMOTE

    def test_detects_easy_apply(self):
        html = """
        <html><body><main>
            <h1>Engineer</h1>
            <a href="/company/x/">X</a>
            <button>Easy Apply</button>
        </main></body></html>
        """
        job = extract_from_dom(html, "1", "u")
        assert job.is_easy_apply is True

    def test_detects_applicant_count(self):
        html = """
        <html><body><main>
            <h1>Engineer</h1>
            <a href="/company/x/">X</a>
            <span>47 applicants</span>
        </main></body></html>
        """
        job = extract_from_dom(html, "1", "u")
        assert job.applicant_count == 47

    def test_raises_on_no_title(self):
        html = "<html><body><main><p>No title here</p></main></body></html>"
        with pytest.raises(ExtractionFallbackError, match="could not find"):
            extract_from_dom(html, "1", "u")

    def test_marks_partial_when_no_company(self):
        html = """
        <html><body><main>
            <h1>Engineer</h1>
        </main></body></html>
        """
        job = extract_from_dom(html, "1", "u")
        assert job.is_partial is True

    def test_ignores_linkedin_h1(self):
        """The LinkedIn logo/header should not be treated as the job title."""
        html = """
        <html><body>
            <h1>LinkedIn</h1>
            <main><h2>Real Job Title</h2></main>
        </body></html>
        """
        # Should not return "LinkedIn" as the title
        # This tests the filter in _find_title
        with pytest.raises(ExtractionFallbackError):
            extract_from_dom(html, "1", "u")
