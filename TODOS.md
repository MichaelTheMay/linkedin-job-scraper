# TODOS

## P1 — High Priority

### Nodriver/Patchright Migration
**What:** Evaluate and migrate from Playwright to Nodriver (eliminates CDP entirely) or Patchright (Playwright fork with fingerprint patches).
**Why:** Playwright's CDP communication creates detectable serialization side effects. Nodriver avoids CDP entirely, making it the most effective open-source anti-detect option (2025).
**Effort:** M
**Depends on:** Phase 1 complete, stable test suite to validate migration.

## P2 — Medium Priority

### Guest API Fallback
**What:** Add support for LinkedIn's public guest API endpoint (`/jobs-guest/jobs/api/seeMoreJobPostings/search`) as a fallback when authenticated session expires.
**Why:** The guest API requires no auth, returns structured HTML, and is the most durable scraping surface. Provides resilience against cookie expiration.
**Effort:** S
**Depends on:** Core scraper working.

### Cookie Extraction Automation
**What:** Add `python main.py --import-cookies` command that extracts LinkedIn cookies directly from the user's Chrome/Edge/Firefox browser profile using browser-cookie3 or rookiepy.
**Why:** Eliminates the most annoying manual step (copying cookies from DevTools). Cookies auto-refresh when the user logs into LinkedIn normally.
**Effort:** S
**Depends on:** Nothing.

## P3 — Nice to Have

### Rich Terminal UI
**What:** Replace plain log output with `rich` library for live progress bars, color-coded status, live job table, and beautiful summary report.
**Why:** Transforms the scraping experience from "watching text scroll" to "watching a live dashboard."
**Effort:** S

### Salary Intelligence
**What:** Regex-based salary extraction from job description text. Parse patterns like "$120K-$150K", "$120,000/year", etc. into normalized min/max range.
**Why:** Many jobs hide salary in description text. Extracting it adds high value for job seekers.
**Effort:** S

### Cross-Run Duplicate Detection
**What:** Persist seen job IDs to SQLite across runs. Skip already-seen jobs on subsequent scrapes.
**Why:** Avoids re-scraping the same jobs daily. Enables "new jobs only" mode.
**Effort:** M
**Depends on:** SQLite persistence layer.

### Applied Job Tracking
**What:** Mark jobs as "applied" in a local database. Skip them on future scrapes.
**Why:** Prevents re-processing jobs you've already acted on.
**Effort:** S
**Depends on:** SQLite persistence layer.

### New Jobs Diff Mode
**What:** `python main.py --diff` that only shows jobs posted since the last scrape run.
**Why:** For daily use — see only what's new without re-reviewing old listings.
**Effort:** M
**Depends on:** Cross-run duplicate detection.
