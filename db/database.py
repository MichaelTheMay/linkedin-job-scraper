"""SQLite database connection and schema initialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path("jobs.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    location        TEXT DEFAULT '',
    url             TEXT NOT NULL,
    description     TEXT DEFAULT '',
    salary_raw      TEXT DEFAULT '',
    salary_min      REAL,
    salary_max      REAL,
    job_type        TEXT DEFAULT 'Unknown',
    workplace_type  TEXT DEFAULT 'Unknown',
    seniority_level TEXT DEFAULT '',
    applicant_count INTEGER,
    posted_date     TEXT,
    badge           TEXT DEFAULT '',
    job_function    TEXT DEFAULT '',
    industries      TEXT DEFAULT '',

    -- Auth-gated fields (populated when cookies available)
    hiring_manager  TEXT DEFAULT '',
    apply_url       TEXT DEFAULT '',
    is_easy_apply   BOOLEAN DEFAULT FALSE,

    -- CRM / pipeline tracking
    status          TEXT DEFAULT 'discovered',
    notes           TEXT DEFAULT '',
    applied_date    TEXT,
    response_date   TEXT,

    -- Metadata
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    enriched        BOOLEAN DEFAULT FALSE,
    extraction_strategy TEXT DEFAULT '',
    scrape_run_id   INTEGER REFERENCES scrape_runs(id),

    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_name    TEXT NOT NULL,
    keywords        TEXT NOT NULL,
    location        TEXT DEFAULT '',
    total_found     INTEGER DEFAULT 0,
    new_jobs        INTEGER DEFAULT 0,
    updated_jobs    INTEGER DEFAULT 0,
    workers_used    INTEGER DEFAULT 0,
    elapsed_seconds REAL DEFAULT 0,
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS search_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    keywords        TEXT NOT NULL,
    location        TEXT DEFAULT '',
    geo_id          TEXT DEFAULT '',
    distance        REAL DEFAULT 25.0,
    time_filter     TEXT DEFAULT 'r2592000',
    experience_levels TEXT DEFAULT '',
    job_types       TEXT DEFAULT '',
    max_pages       INTEGER DEFAULT 10,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
"""


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they don't exist."""
    conn = get_db(db_path)
    conn.executescript(SCHEMA)
    conn.close()
