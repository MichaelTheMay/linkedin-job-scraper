"""Job search pagination — collect job URLs from LinkedIn search results."""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Optional

from playwright.async_api import Page

from browser.stealth import gaussian_delay
from config.constants import (
    AUTHWALL_INDICATORS,
    BOT_DETECTED_STATUS,
    JOBS_PER_PAGE,
    LINKEDIN_JOB_SEARCH,
    MAX_SCROLL_ATTEMPTS,
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
    RateLimitError,
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


async def collect_job_urls(
    page: Page,
    profile: SearchProfile,
) -> list[str]:
    """Paginate through search results and collect unique job URLs.

    Returns a deduplicated list of job detail URLs.
    """
    all_urls: set[str] = set()

    for page_num in range(profile.max_pages):
        start_val = page_num * JOBS_PER_PAGE
        url = build_search_url(profile, start=start_val)

        log.info(
            f"Search page {page_num + 1}/{profile.max_pages}",
            extra={"ctx": {"start": start_val, "total_urls": len(all_urls)}},
        )

        # Navigate to search results
        try:
            response = await page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            raise PageLoadError(f"Search page load failed: {e}", url=url)

        await asyncio.sleep(gaussian_delay(3.5, 1.0))

        # Check response for errors
        if response:
            _check_response_status(response.status, page.url)

        # Check URL for auth problems
        _check_url_for_auth(page.url)

        # Wait for job cards to appear
        try:
            await page.wait_for_selector(
                SELECTOR_JOB_CARD, timeout=SELECTOR_TIMEOUT_MS
            )
        except Exception:
            if page_num == 0:
                raise EmptyPageError(
                    "No job cards found on first search page. "
                    "Search may be invalid or LinkedIn layout changed.",
                    url=page.url,
                )
            log.info(f"No more job cards on page {page_num + 1}, stopping pagination")
            break

        # Scroll to load all jobs in the sidebar
        await _scroll_job_list(page)

        # Extract job URLs from the page
        page_urls = await _extract_job_urls(page)

        if not page_urls:
            log.info(f"No new URLs on page {page_num + 1}, stopping pagination")
            break

        new_urls = page_urls - all_urls
        log.info(
            f"Found {len(page_urls)} URLs ({len(new_urls)} new)",
            extra={"ctx": {"page": page_num + 1}},
        )

        if not new_urls:
            log.info("No new URLs — reached end of unique results")
            break

        all_urls.update(new_urls)
        await asyncio.sleep(gaussian_delay(2.5, 0.8))

    log.info(f"URL collection complete: {len(all_urls)} unique job URLs")
    return sorted(all_urls)


async def _scroll_job_list(page: Page) -> None:
    """Scroll the job list sidebar to trigger lazy loading of all cards."""
    try:
        for attempt in range(MAX_SCROLL_ATTEMPTS):
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
    """Extract job URLs from the current search results page.

    Uses data-entity-urn (most stable) and data-view-tracking-scope as fallback.
    """
    urls = await page.evaluate('''() => {
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
    }''')

    return set(urls)


def _check_response_status(status: int, url: str) -> None:
    """Check HTTP status for rate limiting or bot detection."""
    if status == BOT_DETECTED_STATUS:
        raise BotDetectedError(url=url, status_code=status)
    if status == RATE_LIMITED_STATUS:
        raise RateLimitError(url=url, status_code=status)


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
