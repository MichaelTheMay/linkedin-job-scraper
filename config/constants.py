"""Stable constants for LinkedIn scraping — selectors, URLs, limits."""

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_FEED = f"{LINKEDIN_BASE}/feed/"
LINKEDIN_LOGIN = f"{LINKEDIN_BASE}/login"
LINKEDIN_JOB_VIEW = f"{LINKEDIN_BASE}/jobs/view"
LINKEDIN_JOB_SEARCH = f"{LINKEDIN_BASE}/jobs/search/"

# Guest API (no auth required — most durable scraping surface)
GUEST_JOB_SEARCH_API = (
    f"{LINKEDIN_BASE}/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

# Voyager internal API prefix
VOYAGER_API_PREFIX = "/voyager/api/"

# ---------------------------------------------------------------------------
# Selectors (ordered by stability: data-* attrs > semantic > CSS class)
# ---------------------------------------------------------------------------

# Job search results page — data attributes are more stable than CSS classes
SELECTOR_JOB_CARD = '[data-view-name="job-search-job-card"]'

# data-entity-urn is the most stable identifier (urn:li:jobPosting:XXXXX)
SELECTOR_ENTITY_URN = "[data-entity-urn]"

# Guest API selectors (simpler HTML, more stable)
GUEST_SELECTOR_JOB_CARD = "li"  # direct children of results list
GUEST_SELECTOR_TITLE = "h3.base-search-card__title"
GUEST_SELECTOR_COMPANY = "h4.base-search-card__subtitle"
GUEST_SELECTOR_LOCATION = "span.job-search-card__location"
GUEST_SELECTOR_DATE = "time.job-search-card__listdate"
GUEST_SELECTOR_SALARY = "span.job-search-card__salary-info"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
JOBS_PER_PAGE = 25
MAX_TOTAL_RESULTS = 1000  # LinkedIn caps at 1000 for regular accounts
DEFAULT_MAX_PAGES = 10

# ---------------------------------------------------------------------------
# Timing (seconds) — human-like behavior
# ---------------------------------------------------------------------------
DELAY_PAGE_LOAD_MIN = 3.0
DELAY_PAGE_LOAD_MAX = 6.0
DELAY_JOB_DETAIL_MIN = 1.5
DELAY_JOB_DETAIL_MAX = 3.5
DELAY_SCROLL_MIN = 0.8
DELAY_SCROLL_MAX = 2.0
DELAY_SESSION_WARMUP_MIN = 2.0
DELAY_SESSION_WARMUP_MAX = 4.0

# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 480  # 8 minutes
RATE_LIMIT_RETRIES = 5

# ---------------------------------------------------------------------------
# Timeouts (ms)
# ---------------------------------------------------------------------------
PAGE_LOAD_TIMEOUT_MS = 30_000
SELECTOR_TIMEOUT_MS = 10_000

# ---------------------------------------------------------------------------
# Scrape limits
# ---------------------------------------------------------------------------
MAX_SCROLL_ATTEMPTS = 12
PROGRESS_SAVE_INTERVAL = 5  # save every N jobs
BROWSER_RESTART_INTERVAL = 50  # restart browser every N job detail pages
DESCRIPTION_MAX_LENGTH = 10_000

# ---------------------------------------------------------------------------
# Browser config
# ---------------------------------------------------------------------------
DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Resource types to block for performance
BLOCKED_RESOURCE_PATTERNS = [
    "**/*.{png,jpg,jpeg,gif,svg,webp,ico}",
    "**/*.{woff,woff2,ttf,eot}",
    "**/li/track/**",
    "**/platform.linkedin.com/litms/**",
    "**/www.google-analytics.com/**",
]

# ---------------------------------------------------------------------------
# LinkedIn error signals
# ---------------------------------------------------------------------------
AUTHWALL_INDICATORS = ["/login", "/authwall", "checkpoint/challenge"]
BOT_DETECTED_STATUS = 999
RATE_LIMITED_STATUS = 429
