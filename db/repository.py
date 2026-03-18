"""Job repository — CRUD, dedup, filtering, CRM export."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from db.database import get_db


class JobRepository:
    """Data access layer for jobs, scrape runs, and search profiles."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_db()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def upsert_job(self, data: dict[str, Any]) -> tuple[int, bool]:
        """Insert or update a job. Returns (row_id, is_new).

        On conflict (same job_id), updates last_seen_at and enriches
        empty fields without overwriting user-set fields like status/notes.
        """
        now = datetime.now(UTC).isoformat()
        job_id = data["job_id"]

        existing = self.conn.execute(
            "SELECT id, status, notes, applied_date, response_date FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        if existing:
            # Update: preserve user fields, enrich empty scraper fields
            self.conn.execute(
                """UPDATE jobs SET
                    title = COALESCE(NULLIF(?, ''), title),
                    company = COALESCE(NULLIF(?, ''), company),
                    location = COALESCE(NULLIF(?, ''), location),
                    description = COALESCE(NULLIF(?, ''), description),
                    salary_raw = COALESCE(NULLIF(?, ''), salary_raw),
                    salary_min = COALESCE(?, salary_min),
                    salary_max = COALESCE(?, salary_max),
                    job_type = COALESCE(NULLIF(?, 'Unknown'), job_type),
                    seniority_level = COALESCE(NULLIF(?, ''), seniority_level),
                    applicant_count = COALESCE(?, applicant_count),
                    posted_date = COALESCE(NULLIF(?, ''), posted_date),
                    badge = COALESCE(NULLIF(?, ''), badge),
                    job_function = COALESCE(NULLIF(?, ''), job_function),
                    industries = COALESCE(NULLIF(?, ''), industries),
                    enriched = COALESCE(?, enriched),
                    last_seen_at = ?,
                    updated_at = ?
                WHERE job_id = ?""",
                (
                    data.get("title", ""),
                    data.get("company", ""),
                    data.get("location", ""),
                    data.get("description", ""),
                    data.get("salary_raw", ""),
                    data.get("salary_min"),
                    data.get("salary_max"),
                    data.get("job_type", "Unknown"),
                    data.get("seniority_level", ""),
                    data.get("applicant_count"),
                    data.get("posted_date", ""),
                    data.get("badge", ""),
                    data.get("job_function", ""),
                    data.get("industries", ""),
                    data.get("enriched", False),
                    now,
                    now,
                    job_id,
                ),
            )
            self.conn.commit()
            return existing["id"], False

        # Insert new job
        cursor = self.conn.execute(
            """INSERT INTO jobs (
                job_id, title, company, location, url, description,
                salary_raw, salary_min, salary_max, job_type, workplace_type,
                seniority_level, applicant_count, posted_date, badge,
                job_function, industries, enriched, extraction_strategy,
                first_seen_at, last_seen_at, scrape_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                data.get("title", ""),
                data.get("company", ""),
                data.get("location", ""),
                data.get("url", ""),
                data.get("description", ""),
                data.get("salary_raw", ""),
                data.get("salary_min"),
                data.get("salary_max"),
                data.get("job_type", "Unknown"),
                data.get("workplace_type", "Unknown"),
                data.get("seniority_level", ""),
                data.get("applicant_count"),
                data.get("posted_date", ""),
                data.get("badge", ""),
                data.get("job_function", ""),
                data.get("industries", ""),
                data.get("enriched", False),
                data.get("extraction_strategy", ""),
                now,
                now,
                data.get("scrape_run_id"),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid, True  # type: ignore[return-value]

    def get_job(self, job_id: str) -> dict | None:
        """Get a single job by LinkedIn job_id."""
        row = self.conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def get_job_by_pk(self, pk: int) -> dict | None:
        """Get a single job by primary key."""
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (pk,)).fetchone()
        return dict(row) if row else None

    def list_jobs(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "first_seen_at",
        sort_dir: str = "DESC",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """List jobs with optional filtering and sorting."""
        conditions = []
        params: list[Any] = []

        if status and status != "all":
            conditions.append("status = ?")
            params.append(status)
        if search:
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Whitelist sort columns
        allowed_sorts = {
            "first_seen_at",
            "title",
            "company",
            "location",
            "applicant_count",
            "posted_date",
            "status",
            "updated_at",
        }
        if sort_by not in allowed_sorts:
            sort_by = "first_seen_at"
        if sort_dir not in ("ASC", "DESC"):
            sort_dir = "DESC"

        rows = self.conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY {sort_by} {sort_dir} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_jobs(self, *, status: str | None = None) -> int:
        """Count jobs with optional status filter."""
        if status and status != "all":
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) as cnt FROM jobs").fetchone()
        return row["cnt"] if row else 0

    def update_job_status(self, pk: int, status: str, notes: str | None = None) -> bool:
        """Update a job's pipeline status."""
        now = datetime.now(UTC).isoformat()
        fields = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]

        if notes is not None:
            fields.append("notes = ?")
            params.append(notes)

        if status == "applied":
            fields.append("applied_date = COALESCE(applied_date, ?)")
            params.append(now)

        params.append(pk)
        self.conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", params)
        self.conn.commit()
        return self.conn.total_changes > 0

    def get_status_counts(self) -> dict[str, int]:
        """Get count of jobs by status."""
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    # ------------------------------------------------------------------
    # Scrape runs
    # ------------------------------------------------------------------

    def create_scrape_run(self, profile_name: str, keywords: str, location: str = "") -> int:
        """Create a new scrape run record. Returns the run ID."""
        cursor = self.conn.execute(
            "INSERT INTO scrape_runs (profile_name, keywords, location) VALUES (?, ?, ?)",
            (profile_name, keywords, location),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def complete_scrape_run(
        self,
        run_id: int,
        total_found: int,
        new_jobs: int,
        updated_jobs: int,
        workers_used: int,
        elapsed_seconds: float,
    ) -> None:
        """Mark a scrape run as complete."""
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """UPDATE scrape_runs SET
                total_found = ?, new_jobs = ?, updated_jobs = ?,
                workers_used = ?, elapsed_seconds = ?, completed_at = ?
            WHERE id = ?""",
            (total_found, new_jobs, updated_jobs, workers_used, elapsed_seconds, now, run_id),
        )
        self.conn.commit()

    def list_scrape_runs(self, limit: int = 20) -> list[dict]:
        """List recent scrape runs."""
        rows = self.conn.execute(
            "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Search profiles
    # ------------------------------------------------------------------

    def save_profile(self, data: dict[str, Any]) -> int:
        """Insert or update a search profile. Returns profile ID."""
        existing = self.conn.execute(
            "SELECT id FROM search_profiles WHERE name = ?", (data["name"],)
        ).fetchone()

        if existing:
            self.conn.execute(
                """UPDATE search_profiles SET
                    keywords = ?, location = ?, geo_id = ?, distance = ?,
                    time_filter = ?, experience_levels = ?, job_types = ?, max_pages = ?
                WHERE name = ?""",
                (
                    data["keywords"],
                    data.get("location", ""),
                    data.get("geo_id", ""),
                    data.get("distance", 25.0),
                    data.get("time_filter", "r2592000"),
                    data.get("experience_levels", ""),
                    data.get("job_types", ""),
                    data.get("max_pages", 10),
                    data["name"],
                ),
            )
            self.conn.commit()
            return existing["id"]

        cursor = self.conn.execute(
            """INSERT INTO search_profiles
                (name, keywords, location, geo_id, distance,
                 time_filter, experience_levels, job_types, max_pages)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                data["keywords"],
                data.get("location", ""),
                data.get("geo_id", ""),
                data.get("distance", 25.0),
                data.get("time_filter", "r2592000"),
                data.get("experience_levels", ""),
                data.get("job_types", ""),
                data.get("max_pages", 10),
            ),
        )
        self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def list_profiles(self) -> list[dict]:
        """List all saved search profiles."""
        rows = self.conn.execute("SELECT * FROM search_profiles ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def delete_profile(self, name: str) -> bool:
        """Delete a search profile by name."""
        self.conn.execute("DELETE FROM search_profiles WHERE name = ?", (name,))
        self.conn.commit()
        return self.conn.total_changes > 0
