"""Job detail extraction — orchestrates the strategy chain.

Tries: API Intercept → LD+JSON → DOM Fallback
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from playwright.async_api import Page

from browser.interceptor import NetworkInterceptor
from browser.stealth import gaussian_delay
from config.constants import (
    AUTHWALL_INDICATORS,
    BOT_DETECTED_STATUS,
    RATE_LIMITED_STATUS,
)
from data.models import Job
from monitor.logger import get_logger
from scraper.exceptions import (
    AuthExpiredError,
    BotDetectedError,
    ChallengeError,
    ExtractionError,
    ExtractionFallbackError,
    PageLoadError,
    RateLimitError,
)
from scraper.strategies.api_intercept import extract_from_api
from scraper.strategies.dom_fallback import extract_from_dom
from scraper.strategies.ld_json import extract_from_ld_json

log = get_logger("job_detail")


async def extract_job(
    page: Page,
    url: str,
    interceptor: NetworkInterceptor,
) -> Job:
    """Visit a job detail page and extract data using the strategy chain.

    Raises:
        AuthExpiredError: Session expired during navigation.
        BotDetectedError: HTTP 999 received.
        RateLimitError: HTTP 429 received.
        ExtractionError: All strategies failed.
        PageLoadError: Page failed to load.
    """
    job_id = _extract_job_id(url)

    # Clear interceptor for fresh capture
    interceptor.clear()

    # Navigate to job page
    try:
        response = await page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        raise PageLoadError(f"Failed to load {url}: {e}", url=url)

    await asyncio.sleep(gaussian_delay(2.0, 0.6))

    # Check response status
    if response:
        status = response.status
        if status == BOT_DETECTED_STATUS:
            raise BotDetectedError(url=url, status_code=status)
        if status == RATE_LIMITED_STATUS:
            raise RateLimitError(url=url, status_code=status)
        if status == 404:
            raise ExtractionError(f"Job not found (404): {url}", url=url)

    # Check URL for auth problems
    current_url = page.url
    for indicator in AUTHWALL_INDICATORS:
        if indicator in current_url:
            if "checkpoint" in current_url:
                raise ChallengeError(url=current_url)
            raise AuthExpiredError(
                "Session expired mid-scrape", url=current_url
            )

    # Wait a moment for API responses to arrive
    await asyncio.sleep(gaussian_delay(1.0, 0.3))

    # Strategy chain: API Intercept → LD+JSON → DOM
    errors: list[str] = []

    # Strategy 1: API Intercept
    try:
        api_data = interceptor.find_job_data(job_id)
        if api_data:
            return extract_from_api(api_data, job_id, url)
        errors.append("No API data captured")
    except ExtractionFallbackError as e:
        errors.append(f"API: {e}")

    # Strategy 2: LD+JSON
    try:
        html = await page.content()
        return extract_from_ld_json(html, job_id, url)
    except ExtractionFallbackError as e:
        errors.append(f"LD+JSON: {e}")

    # Strategy 3: DOM Fallback
    try:
        if not html:
            html = await page.content()
        return extract_from_dom(html, job_id, url)
    except ExtractionFallbackError as e:
        errors.append(f"DOM: {e}")

    # All strategies failed
    error_summary = "; ".join(errors)
    raise ExtractionError(
        f"All extraction strategies failed for job {job_id}: {error_summary}",
        url=url,
    )


def _extract_job_id(url: str) -> str:
    """Extract numeric job ID from URL."""
    match = re.search(r"/view/(\d+)", url)
    if match:
        return match.group(1)
    # Try entity URN pattern
    match = re.search(r"jobPosting[:\-](\d+)", url)
    if match:
        return match.group(1)
    return "unknown"
