"""Tests for the data cleaning pipeline."""

from data.cleaner import _clean_description, clean_job
from data.models import Job


class TestCleanJob:
    def test_strips_whitespace(self):
        job = Job(
            job_id="1",
            title="  AI Engineer  ",
            company="  Acme Corp  ",
            location="  Dallas, TX  ",
            url="https://example.com",
        )
        cleaned = clean_job(job)
        assert cleaned.title == "AI Engineer"
        assert cleaned.company == "Acme Corp"
        assert cleaned.location == "Dallas, TX"

    def test_marks_partial_on_missing_title(self):
        job = Job(
            job_id="1",
            title="",
            company="Acme",
            location="TX",
            url="u",
        )
        cleaned = clean_job(job)
        assert cleaned.is_partial is True

    def test_marks_partial_on_missing_company(self):
        job = Job(
            job_id="1",
            title="Engineer",
            company="",
            location="TX",
            url="u",
        )
        cleaned = clean_job(job)
        assert cleaned.is_partial is True


class TestCleanDescription:
    def test_removes_ui_noise(self):
        text = (
            "About the job\n"
            "We are looking for an AI Engineer.\n"
            "Easy Apply\n"
            "Save\n"
            "Requirements:\n"
            "Use AI to assess how you fit\n"
            "Python, TensorFlow"
        )
        cleaned = _clean_description(text)
        assert "Easy Apply" not in cleaned
        assert "Save" not in cleaned
        assert "Use AI to assess" not in cleaned
        assert "AI Engineer" in cleaned
        assert "Requirements" in cleaned
        assert "Python, TensorFlow" in cleaned

    def test_removes_premium_upsell(self):
        text = (
            "Get AI-powered advice on this job and more exclusive features"
            " with Premium.\nReal content here."
        )
        cleaned = _clean_description(text)
        assert "Premium" not in cleaned
        assert "Real content here" in cleaned

    def test_preserves_empty_string(self):
        assert _clean_description("") == ""

    def test_truncates_long_descriptions(self):
        text = "x" * 20_000
        cleaned = _clean_description(text)
        assert len(cleaned) <= 10_000
