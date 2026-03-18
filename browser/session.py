"""Session management — cookie injection, health checks, expiry detection."""

from __future__ import annotations

import asyncio

from browser.manager import BrowserManager
from browser.stealth import gaussian_delay
from config.constants import (
    AUTHWALL_INDICATORS,
    BOT_DETECTED_STATUS,
    LINKEDIN_FEED,
    RATE_LIMITED_STATUS,
)
from config.settings import ScraperConfig
from monitor.logger import get_logger
from scraper.exceptions import (
    AuthExpiredError,
    BotDetectedError,
    ChallengeError,
    RateLimitError,
    SessionError,
)

log = get_logger("session")


class SessionManager:
    """Handles LinkedIn cookie injection and session validation."""

    def __init__(self, config: ScraperConfig, browser: BrowserManager):
        self.config = config
        self.browser = browser

    async def inject_cookies(self) -> None:
        """Inject LinkedIn authentication cookies into the browser context."""
        if not self.config.li_at_cookie:
            raise SessionError(
                "LI_AT_COOKIE not found in .env file.\n"
                "  1. Log into LinkedIn in your regular browser\n"
                "  2. Open DevTools → Application → Cookies → linkedin.com\n"
                "  3. Copy the 'li_at' cookie value\n"
                "  4. Add to .env: LI_AT_COOKIE=<value>"
            )

        cookies = [
            {
                "name": "li_at",
                "value": self.config.li_at_cookie.strip('"'),
                "domain": ".linkedin.com",
                "path": "/",
            }
        ]

        # JSESSIONID is needed for Voyager API calls (sent as csrf-token header)
        if self.config.jsessionid_cookie:
            cookies.append(
                {
                    "name": "JSESSIONID",
                    "value": self.config.jsessionid_cookie.strip('"'),
                    "domain": ".linkedin.com",
                    "path": "/",
                }
            )
        else:
            log.warning(
                "JSESSIONID_COOKIE not set — Voyager API intercept may not work. "
                "API intercept will still be attempted via browser-generated session."
            )

        await self.browser.context.add_cookies(cookies)
        log.info(
            "Cookies injected",
            extra={"ctx": {
                "li_at": f"...{self.config.li_at_cookie[-8:]}",
                "jsessionid": "set" if self.config.jsessionid_cookie else "not set",
            }},
        )

    async def validate(self) -> bool:
        """Validate the session by visiting LinkedIn feed and checking for redirects.

        Returns True if session is valid.
        Raises specific exceptions for different failure modes.
        """
        log.info("Validating session...")
        page = self.browser.page

        try:
            response = await page.goto(LINKEDIN_FEED, wait_until="domcontentloaded")
        except Exception as e:
            raise SessionError(f"Failed to load LinkedIn: {e}", url=LINKEDIN_FEED)

        await asyncio.sleep(gaussian_delay(2.5, 0.8))

        current_url = page.url

        # Check response status
        if response:
            status = response.status
            if status == BOT_DETECTED_STATUS:
                await self.browser.screenshot("error_bot_detected.png")
                raise BotDetectedError(url=current_url, status_code=status)
            if status == RATE_LIMITED_STATUS:
                raise RateLimitError(url=current_url, status_code=status)

        # Check URL for auth problems
        for indicator in AUTHWALL_INDICATORS:
            if indicator in current_url:
                await self.browser.screenshot("error_auth_expired.png")
                if "checkpoint" in current_url:
                    raise ChallengeError(
                        "LinkedIn checkpoint challenge detected. "
                        "Log in manually and complete the challenge, then update cookies.",
                        url=current_url,
                    )
                raise AuthExpiredError(
                    "Session expired or invalid. Update your LI_AT_COOKIE in .env.\n"
                    f"  Current URL: {current_url}",
                    url=current_url,
                )

        log.info(
            "Session valid",
            extra={"ctx": {"url": current_url}},
        )
        return True

    async def warmup(self) -> None:
        """Visit a couple pages to warm up the session (mimics normal user behavior).

        This reduces the chance of detection by making the scraping traffic
        look like it follows a normal browsing session.
        """
        log.info("Warming up session...")
        page = self.browser.page

        # Just pause briefly on the feed page (we're already there from validate())
        await asyncio.sleep(gaussian_delay(3.0, 1.0))

        # Scroll down a bit on the feed to simulate engagement
        await page.mouse.wheel(0, random_scroll_distance())
        await asyncio.sleep(gaussian_delay(1.5, 0.5))

        log.info("Session warm-up complete")

    def check_url_for_errors(self, url: str) -> None:
        """Check a URL after navigation for auth/bot issues. Raises on problems."""
        for indicator in AUTHWALL_INDICATORS:
            if indicator in url:
                if "checkpoint" in url:
                    raise ChallengeError(
                        "LinkedIn checkpoint challenge during scrape",
                        url=url,
                    )
                raise AuthExpiredError(
                    "Session expired mid-scrape. Progress has been saved.",
                    url=url,
                )


def random_scroll_distance() -> int:
    """Random scroll distance for session warmup."""
    import random
    return random.randint(300, 800)
