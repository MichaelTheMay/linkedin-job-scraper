# LinkedIn Job Scraper

Production-grade LinkedIn job scraper with anti-detection, multi-strategy extraction, and structured data export.

## Features

- **Multi-strategy extraction chain**: API Intercept → LD+JSON → DOM Fallback — tries the most reliable method first, falls back gracefully
- **Anti-detection**: Stealth browser configuration, human-like delays, resource blocking, session warmup
- **Typed exception hierarchy**: Fatal vs recoverable vs extraction errors with automatic retry/backoff
- **Structured logging**: Console (human-readable) + JSON-lines file log
- **Deduplication**: By job ID (exact) and title+company signature (fuzzy)
- **Data cleaning**: Strips LinkedIn UI noise, normalizes whitespace, truncates overlong fields
- **Progress saving**: Periodic CSV checkpoint so interrupted runs don't lose data
- **YAML search profiles**: Configure multiple searches with different keywords, locations, filters
- **CSV + JSON export**: Both formats with run summaries

## Quick Start

### 1. Install

```bash
# Clone and install
git clone https://github.com/your-username/linkedin-job-scraper.git
cd linkedin-job-scraper
pip install -e ".[dev]"
playwright install chromium
```

Or use Make:

```bash
make install
```

### 2. Set Up Cookies

**Option A: Interactive login (recommended)**

```bash
python main.py --login
```

This opens a visible browser window. Log into LinkedIn manually, and the scraper captures your session cookies automatically.

**Option B: Manual setup**

1. Log into LinkedIn in your regular browser
2. Open DevTools (F12) → Application → Cookies → linkedin.com
3. Copy `li_at` and `JSESSIONID` values
4. Create `.env` from the example:

```bash
cp .env.example .env
# Edit .env with your cookie values
```

### 3. Configure Search

Edit `config/search_profiles.yaml`:

```yaml
search_profiles:
  - name: ai-engineer
    keywords: "AI engineer"
    location: "Dallas, TX"
    max_pages: 5
    time_filter: "r604800"  # past week
    experience_levels: ["3", "4"]  # mid-senior
```

### 4. Run

```bash
# Validate session first
python main.py --validate

# Scrape
python main.py

# Or with options
python main.py --config custom.yaml --max-pages 3 --no-headless --verbose
```

## Configuration

### Search Profiles (YAML)

| Field | Description | Default |
|-------|-------------|---------|
| `name` | Profile identifier | required |
| `keywords` | Search query | required |
| `location` | Location filter | `""` |
| `geo_id` | LinkedIn geo ID | `""` |
| `distance` | Search radius (miles) | `25.0` |
| `time_filter` | Time filter (`r86400`=day, `r604800`=week, `r2592000`=month) | `r2592000` |
| `experience_levels` | List of level codes (`1`=Intern, `2`=Entry, `3`=Associate, `4`=Mid-Senior, `5`=Director, `6`=Executive) | `[]` |
| `job_types` | List of type codes (`F`=Full-time, `P`=Part-time, `C`=Contract, `I`=Internship) | `[]` |
| `max_pages` | Max search result pages | `10` |

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `LI_AT_COOKIE` | LinkedIn `li_at` session cookie | Yes (unless using `--login`) |
| `JSESSIONID_COOKIE` | LinkedIn `JSESSIONID` for Voyager API | Recommended |
| `SEARCH_KEYWORDS` | Fallback search keywords (if no YAML) | No |
| `SEARCH_LOCATION` | Fallback location | No |
| `HEADLESS` | Run headless (`true`/`false`) | No (default: `true`) |

## Architecture

```
main.py                     # CLI entry point + orchestration loop
browser/
  manager.py                # Browser lifecycle (launch, restart, close)
  session.py                # Cookie injection, session validation, warmup
  stealth.py                # Anti-detection: launch args, JS patches, delays
  interceptor.py            # Captures Voyager API network responses
config/
  settings.py               # YAML + env config loading
  constants.py              # URLs, selectors, timing, limits
data/
  models.py                 # Job, ScrapeResult dataclasses
  cleaner.py                # Text normalization, UI noise removal
  deduplicator.py           # ID + signature dedup
  exporter.py               # CSV/JSON export with progress saves
monitor/
  logger.py                 # Structured logging (console + JSON-lines)
  health.py                 # Rate limit tracking, abort logic
scraper/
  job_search.py             # Search pagination, URL collection
  job_detail.py             # Strategy chain orchestration
  strategies/
    api_intercept.py        # Strategy 1: Parse Voyager API JSON
    ld_json.py              # Strategy 2: Parse LD+JSON from HTML
    dom_fallback.py         # Strategy 3: BeautifulSoup DOM parsing
```

### Extraction Strategy Chain

Each job detail page is extracted using a priority chain:

1. **API Intercept** — Captures LinkedIn's internal Voyager API responses from browser network traffic. Most reliable, structured JSON data.
2. **LD+JSON** — Parses structured `<script type="application/ld+json">` data from HTML. Schema.org standard format.
3. **DOM Fallback** — BeautifulSoup parsing of the rendered HTML. Least reliable but catches edge cases.

If a strategy fails, it raises `ExtractionFallbackError` and the next strategy is tried.

## Development

```bash
make install     # Install with dev dependencies + Playwright
make test        # Run all tests
make test-ci     # Run tests without integration tests
make lint        # Check with ruff
make format      # Auto-format with ruff
make typecheck   # Run mypy
```

## License

MIT
