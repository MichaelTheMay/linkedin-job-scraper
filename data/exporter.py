"""Export scraped jobs to CSV and/or JSON."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from data.models import Job, ScrapeResult
from monitor.logger import get_logger

log = get_logger("exporter")


class Exporter:
    """Handles saving job data to files with progress saves."""

    def __init__(self, output_dir: str, output_format: str = "both"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.output_format = output_format
        self._timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    @property
    def csv_path(self) -> Path:
        return self.output_dir / f"jobs_{self._timestamp}.csv"

    @property
    def json_path(self) -> Path:
        return self.output_dir / f"jobs_{self._timestamp}.json"

    def save_jobs(self, jobs: list[Job], profile_name: str = "") -> str:
        """Save all jobs to configured format(s). Returns primary output path."""
        if not jobs:
            log.warning("No jobs to export")
            return ""

        paths = []

        if self.output_format in ("csv", "both"):
            path = self._save_csv(jobs, profile_name)
            paths.append(str(path))

        if self.output_format in ("json", "both"):
            path = self._save_json(jobs, profile_name)
            paths.append(str(path))

        primary = paths[0] if paths else ""
        log.info(
            f"Exported {len(jobs)} jobs",
            extra={"ctx": {"files": paths}},
        )
        return primary

    def save_progress(self, jobs: list[Job]) -> None:
        """Save partial progress (overwrites previous progress file)."""
        if not jobs:
            return

        progress_path = self.output_dir / "jobs_partial.csv"
        self._write_csv(jobs, progress_path)
        log.debug(f"Progress saved: {len(jobs)} jobs to {progress_path}")

    def _save_csv(self, jobs: list[Job], profile_name: str) -> Path:
        suffix = f"_{profile_name}" if profile_name else ""
        path = self.output_dir / f"jobs{suffix}_{self._timestamp}.csv"
        self._write_csv(jobs, path)
        return path

    def _write_csv(self, jobs: list[Job], path: Path) -> None:
        rows = [job.to_dict() for job in jobs]
        if not rows:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def _save_json(self, jobs: list[Job], profile_name: str) -> Path:
        suffix = f"_{profile_name}" if profile_name else ""
        path = self.output_dir / f"jobs{suffix}_{self._timestamp}.json"

        data = {
            "metadata": {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "total_jobs": len(jobs),
                "profile": profile_name,
            },
            "jobs": [job.to_dict() for job in jobs],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

        return path

    def save_summary(self, result: ScrapeResult) -> None:
        """Save run summary alongside the data."""
        summary_path = self.output_dir / f"summary_{self._timestamp}.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "search_profile": result.search_profile,
                    "total_urls_found": result.total_urls_found,
                    "total_jobs_extracted": result.total_jobs_extracted,
                    "total_duplicates_skipped": result.total_duplicates_skipped,
                    "total_errors": result.total_errors,
                    "extraction_strategy_counts": result.extraction_strategy_counts,
                    "partial_extractions": result.partial_extractions,
                    "elapsed_seconds": round(result.elapsed_seconds, 1),
                    "output_file": result.output_file,
                    "started_at": result.started_at,
                },
                f,
                indent=2,
            )
