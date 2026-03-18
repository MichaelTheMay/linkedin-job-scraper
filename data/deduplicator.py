"""Deduplication — by job ID (exact) and title+company (fuzzy)."""

from __future__ import annotations

from data.models import Job
from monitor.logger import get_logger

log = get_logger("dedup")


class Deduplicator:
    """Track seen jobs and detect duplicates."""

    def __init__(self):
        self._seen_ids: set[str] = set()
        self._seen_signatures: set[str] = set()
        self.duplicates_skipped = 0

    def is_duplicate(self, job: Job) -> bool:
        """Check if this job has been seen before.

        Uses exact job ID match first, then title+company signature.
        """
        # Exact ID match
        if job.job_id in self._seen_ids:
            self.duplicates_skipped += 1
            log.debug(
                f"Duplicate (ID): {job.job_id}",
                extra={"ctx": {"title": job.title}},
            )
            return True

        # Fuzzy signature match (same title + company = likely same job)
        signature = _job_signature(job)
        if signature in self._seen_signatures:
            self.duplicates_skipped += 1
            log.debug(
                f"Duplicate (signature): {job.title} @ {job.company}",
                extra={"ctx": {"job_id": job.job_id}},
            )
            return True

        return False

    def mark_seen(self, job: Job) -> None:
        """Record this job as seen."""
        self._seen_ids.add(job.job_id)
        self._seen_signatures.add(_job_signature(job))

    @property
    def total_seen(self) -> int:
        return len(self._seen_ids)


def _job_signature(job: Job) -> str:
    """Normalize title + company into a dedup signature."""
    title = job.title.lower().strip()
    company = job.company.lower().strip()
    return f"{title}|||{company}"
