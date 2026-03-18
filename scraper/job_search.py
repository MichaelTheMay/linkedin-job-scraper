"""Job search pagination — collect job URLs from LinkedIn search results.

Strategy:
  1. Try the authenticated /jobs/search/ endpoint (richer data, needs cookies)
  2. On rate limit (429), back off and retry up to RATE_LIMIT_RETRIES times
  3. If the authenticated endpoint is exhausted, fall back to the guest API
     (/jobs-guest/...) which is unauthenticated and far more durable
"""

from __future__ import annotations

import asyncio
import urllib.parse

from playwright.async_api import Page

from browser.stealth import exponential_backoff, gaussian_delay
from config.constants import (
    AUTHWALL_INDICATORS,
    BOT_DETECTED_STATUS,
    GUEST_JOB_SEARCH_API,
    JOBS_PER_PAGE,
    LINKEDIN_JOB_SEARCH,
    MAX_SCROLL_ATTEMPTS,
    RATE_LIMIT_RETRIES,
    RATE_LIMITED_STATUS,
    SELECTOR_JOB_CARD,
    SELECTOR_TIMEOUT_MS,
)
from config.settings import SearchProfile
from monitor.logger import get_logger
from scraper.exceptions import (
    AuthExpiredError,
    BotDetectedError,
    ChallengeError,
    EmptyPageError,
    PageLoadError,
)

log = get_logger("search")


def build_search_url(profile: SearchProfile, start: int = 0) -> str:
    """Build a LinkedIn job search URL from a search profile."""
    params = {
        "keywords": profile.keywords,
        "origin": "JOB_SEARCH_PAGE_JOB_FILTER",
    }
    if profile.location:
        params["location"] = profile.location
    if profile.geo_id:
        params["geoId"] = profile.geo_id
    if profile.distance:
        params["distance"] = str(profile.distance)
    if profile.time_filter:
        params["f_TPR"] = profile.time_filter
    if profile.experience_levels:
        params["f_E"] = ",".join(profile.experience_levels)
    if profile.job_types:
        params["f_JT"] = ",".join(profile.job_types)
    if start > 0:
        params["start"] = str(start)

    return f"{LINKEDIN_JOB_SEARCH}?{urllib.parse.urlencode(params)}"


def _build_guest_search_url(profile: SearchProfile, start: int = 0) -> str:
    """Build a guest API search URL (no auth required, more durable)."""
    params = {
        "keywords": profile.keywords,
    }
    if profile.location:
        params["location"] = profile.location
    if profile.geo_id:
        params["geoId"] = profile.geo_id
    if profile.distance:
        params["distance"] = str(profile.distance)
    if profile.time_filter:
        params["f_TPR"] = profile.time_filter
    if profile.experience_levels:
        params["f_E"] = ",".join(profile.experience_levels)
    if profile.job_types:
        params["f_JT"] = ",".join(profile.job_types)
    if start > 0:
        params["start"] = str(start)

    return f"{GUEST_JOB_SEARCH_API}?{urllib.parse.urlencode(params)}"


async def collect_job_urls(
    page: Page,
    profile: SearchProfile,
    *,
    prefer_guest_api: bool = False,
) -> list[str]:
    """Paginate through search results and collect unique job URLs.

    Tries authenticated search first. On rate limit, backs off and retries.
    If rate-limited repeatedly, falls back to the guest API.

    Args:
        prefer_guest_api: Start with guest API (e.g. when session is already rate-limited).
    """
    all_urls: set[str] = set()
    use_guest_api = prefer_guest_api

    if use_guest_api:
        log.info("Using guest API for URL collection (session rate-limited)")

    for page_num in range(profile.max_pages):
        start_val = page_num * JOBS_PER_PAGE

        log.info(
            f"Search page {page_num + 1}/{profile.max_pages}",
            extra={"ctx": {"start": start_val, "total_urls": len(all_urls)}},
        )

        # Try to load this search page with rate limit retry
        page_urls = await _load_search_page_with_retry(
            page, profile, page_num, start_val, use_guest_api
        )

        if page_urls is None:
            # Retry exhausted on authenticated — switch to guest API
            if not use_guest_api:
                log.warning("Switching to guest API after rate limit on authenticated search")
                use_guest_api = True
                page_urls = await _load_search_page_with_retry(
                    page, profile, page_num, start_val, use_guest_api
                )

        if page_urls is None:
            log.error("Rate limited on both authenticated and guest API — stopping")
            break

        if not page_urls:
            log.info(f"No URLs on page {page_num + 1}, stopping pagination")
            break

        new_urls = page_urls - all_urls
        log.info(
            f"Found {len(page_urls)} URLs ({len(new_urls)} new)",
            extra={"ctx": {"page": page_num + 1, "guest": use_guest_api}},
        )

        if not new_urls:
            log.info("No new URLs — reached end of unique results")
            break

        all_urls.update(new_urls)
        await asyncio.sleep(gaussian_delay(2.5, 0.8))

    log.info(f"URL collection complete: {len(all_urls)} unique job URLs")
    return sorted(all_urls)


async def _load_search_page_with_retry(
    page: Page,
    profile: SearchProfile,
    page_num: int,
    start_val: int,
    use_guest_api: bool,
) -> set[str] | None:
    """Load a single search page, retrying on rate limit.

    Returns:
        set of URLs on success, empty set if no results, None if rate-limited out.
    """
    for attempt in range(RATE_LIMIT_RETRIES):
        if use_guest_api:
            url = _build_guest_search_url(profile, start=start_val)
            # Guest API must not send auth cookies — they cause redirect loops
            # when the session is flagged. Clear them before navigating.
            context = page.context
            await context.clear_cookies()
        else:
            url = build_search_url(profile, start=start_val)

        try:
            response = await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            raise PageLoadError(f"Search page load failed: {e}", url=url) from e

        await asyncio.sleep(gaussian_delay(3.5, 1.0))

        # Check response status
        if response:
            status = response.status
            if status == BOT_DETECTED_STATUS:
                raise BotDetectedError(url=page.url, status_code=status)
            if status == RATE_LIMITED_STATUS:
                delay = exponential_backoff(attempt, base=30.0)
                log.warning(
                    f"Rate limited (429) on search — backing off {delay:.0f}s "
                    f"(attempt {attempt + 1}/{RATE_LIMIT_RETRIES})",
                    extra={"ctx": {"url": url[:80]}},
                )
                await asyncio.sleep(delay)
                continue

        # Check URL for auth problems
        _check_url_for_auth(page.url)

        # For guest API, extract URLs from the simpler HTML
        if use_guest_api:
            return await _extract_guest_job_urls(page)

        # Wait for job cards to appear (authenticated search)
        try:
            await page.wait_for_selector(SELECTOR_JOB_CARD, timeout=SELECTOR_TIMEOUT_MS)
        except Exception as exc:
            if page_num == 0 and attempt == 0:
                raise EmptyPageError(
                    "No job cards found on first search page. "
                    "Search may be invalid or LinkedIn layout changed.",
                    url=page.url,
                ) from exc
            log.info(f"No more job cards on page {page_num + 1}, stopping pagination")
            return set()

        # Scroll to load all jobs in the sidebar
        await _scroll_job_list(page)

        # Extract job URLs from the page
        return await _extract_job_urls(page)

    # All retries exhausted
    return None


async def _scroll_job_list(page: Page) -> None:
    """Scroll the job list sidebar to trigger lazy loading of all cards."""
    try:
        for _attempt in range(MAX_SCROLL_ATTEMPTS):
            cards = await page.locator(SELECTOR_JOB_CARD).all()
            if len(cards) >= JOBS_PER_PAGE:
                break
            if cards:
                await cards[-1].scroll_into_view_if_needed()
                await cards[-1].focus()
                await page.keyboard.press("PageDown")
            await asyncio.sleep(gaussian_delay(1.0, 0.3))
    except Exception as e:
        log.debug(f"Scroll completed (possibly partial): {e}")


async def _extract_job_urls(page: Page) -> set[str]:
    """Extract job URLs from the authenticated search results page."""
    urls = await page.evaluate("""() => {
        const urls = new Set();

        // Method 1: data-entity-urn attributes (most stable)
        document.querySelectorAll('[data-entity-urn]').forEach(el => {
            const urn = el.getAttribute('data-entity-urn');
            if (urn && urn.includes('jobPosting')) {
                const match = urn.match(/jobPosting:(\\d+)/);
                if (match) {
                    urls.add(`https://www.linkedin.com/jobs/view/${match[1]}/`);
                }
            }
        });

        // Method 2: data-view-tracking-scope (fallback)
        if (urls.size === 0) {
            document.querySelectorAll('[data-view-tracking-scope]').forEach(el => {
                const scope = el.getAttribute('data-view-tracking-scope');
                if (scope && scope.includes('jobPosting')) {
                    const match = scope.match(/jobPosting:(\\d+)/);
                    if (match) {
                        urls.add(`https://www.linkedin.com/jobs/view/${match[1]}/`);
                    }
                }
            });
        }

        // Method 3: href links to /jobs/view/ (last resort)
        if (urls.size === 0) {
            document.querySelectorAll('a[href*="/jobs/view/"]').forEach(a => {
                const match = a.href.match(/\\/jobs\\/view\\/(\\d+)/);
                if (match) {
                    urls.add(`https://www.linkedin.com/jobs/view/${match[1]}/`);
                }
            });
        }

        return Array.from(urls);
    }""")

    return set(urls)


async def _extract_guest_job_urls(page: Page) -> set[str]:
    """Extract job URLs from the guest API HTML response.

    Guest API uses slugified URLs like:
      /jobs/view/python-gen-ai-developer-at-company-4377488555
    The numeric job ID is the trailing number after the last hyphen.
    """
    urls = await page.evaluate("""() => {
        const urls = new Set();

        // Guest API links use slugified hrefs with the job ID as trailing digits
        // e.g. /jobs/view/some-title-at-company-4377488555?position=1&...
        document.querySelectorAll('a[href*="/jobs/view/"]').forEach(a => {
            const href = a.href || a.getAttribute('href') || '';
            // Extract the numeric ID from the end of the slug (before query params)
            const path = href.split('?')[0];
            const match = path.match(/(\\d{5,})\\/?$/);
            if (match) {
                urls.add(`https://www.linkedin.com/jobs/view/${match[1]}/`);
            }
        });

        return Array.from(urls);
    }""")

    log.debug(f"Guest API extracted {len(urls)} URLs from page")
    return set(urls)


def _check_url_for_auth(url: str) -> None:
    """Check current URL for authentication problems."""
    for indicator in AUTHWALL_INDICATORS:
        if indicator in url:
            if "checkpoint" in url:
                raise ChallengeError(
                    "LinkedIn checkpoint challenge during search",
                    url=url,
                )
            raise AuthExpiredError(
                "Session expired during search pagination",
                url=url,
            )
