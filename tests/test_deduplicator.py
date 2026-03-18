"""Tests for the deduplication logic."""

from data.deduplicator import Deduplicator
from data.models import Job


def _make_job(job_id: str, title: str = "Engineer", company: str = "Acme") -> Job:
    return Job(
        job_id=job_id,
        title=title,
        company=company,
        location="TX",
        url=f"https://example.com/{job_id}",
    )


class TestDeduplicator:
    def test_no_duplicate_on_first_see(self):
        dedup = Deduplicator()
        job = _make_job("123")
        assert dedup.is_duplicate(job) is False

    def test_detects_exact_id_duplicate(self):
        dedup = Deduplicator()
        job1 = _make_job("123")
        dedup.mark_seen(job1)
        job2 = _make_job("123", title="Different Title")
        assert dedup.is_duplicate(job2) is True
        assert dedup.duplicates_skipped == 1

    def test_detects_signature_duplicate(self):
        dedup = Deduplicator()
        job1 = _make_job("100", title="AI Engineer", company="Acme")
        dedup.mark_seen(job1)
        # Same title+company but different ID (reposted by same company)
        job2 = _make_job("200", title="AI Engineer", company="Acme")
        assert dedup.is_duplicate(job2) is True

    def test_different_jobs_not_duplicate(self):
        dedup = Deduplicator()
        job1 = _make_job("100", title="AI Engineer", company="Acme")
        dedup.mark_seen(job1)
        job2 = _make_job("200", title="ML Engineer", company="Acme")
        assert dedup.is_duplicate(job2) is False

    def test_total_seen_count(self):
        dedup = Deduplicator()
        for i in range(5):
            dedup.mark_seen(_make_job(str(i)))
        assert dedup.total_seen == 5
