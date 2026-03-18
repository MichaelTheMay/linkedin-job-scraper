"""Session management — cookie injection, health checks, expiry detection."""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

from browser.manager import BrowserManager
from browser.stealth import gaussian_delay
from config.constants import (
    AUTHWALL_INDICATORS,
    BOT_DETECTED_STATUS,
    LINKEDIN_FEED,
    LINKEDIN_LOGIN,
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

        await self.browser.context.add_cookies(cookies)  # type: ignore[arg-type]
        log.info(
            "Cookies injected",
            extra={
                "ctx": {
                    "li_at": f"...{self.config.li_at_cookie[-8:]}",
                    "jsessionid": "set" if self.config.jsessionid_cookie else "not set",
                }
            },
        )

    async def validate(self, max_retries: int = 2) -> bool:
        """Validate the session by visiting LinkedIn feed and checking for redirects.

        Retries on rate limit (429) with shorter backoff (validation shouldn't
        block the run for minutes — the guest API fallback handles it).
        Returns True if session is valid.
        Raises specific exceptions for different failure modes.
        """
        from browser.stealth import exponential_backoff

        log.info("Validating session...")
        page = self.browser.page

        for attempt in range(max_retries):
            try:
                response = await page.goto(LINKEDIN_FEED, wait_until="domcontentloaded")
            except Exception as e:
                raise SessionError(f"Failed to load LinkedIn: {e}", url=LINKEDIN_FEED) from e

            await asyncio.sleep(gaussian_delay(2.5, 0.8))

            current_url = page.url

            # Check response status
            if response:
                status = response.status
                if status == BOT_DETECTED_STATUS:
                    await self.browser.screenshot("error_bot_detected.png")
                    raise BotDetectedError(url=current_url, status_code=status)
                if status == RATE_LIMITED_STATUS:
                    if attempt < max_retries - 1:
                        delay = exponential_backoff(attempt, base=10.0, cap=30.0)
                        log.warning(
                            f"Rate limited (429) during validation — "
                            f"backing off {delay:.0f}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise RateLimitError(
                        "Rate limited after retries. LinkedIn may have flagged this "
                        "session — wait 15-30 minutes before retrying, or refresh "
                        "your cookies with: python main.py --login",
                        url=current_url,
                        status_code=status,
                    )

            # Check URL for auth problems
            for indicator in AUTHWALL_INDICATORS:
                if indicator in current_url:
                    await self.browser.screenshot("error_auth_expired.png")
                    if "checkpoint" in current_url:
                        raise ChallengeError(
                            "LinkedIn checkpoint challenge detected. "
                            "Log in manually and complete the challenge, "
                            "then update cookies.",
                            url=current_url,
                        )
                    raise AuthExpiredError(
                        "Session expired or invalid. Update your LI_AT_COOKIE "
                        "in .env or run: python main.py --login\n"
                        f"  Current URL: {current_url}",
                        url=current_url,
                    )

            log.info(
                "Session valid",
                extra={"ctx": {"url": current_url}},
            )
            return True

        return False

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
    return random.randint(300, 800)


async def interactive_login(config: ScraperConfig) -> None:
    """Launch a visible browser for manual LinkedIn login, then capture cookies.

    After login is detected (URL changes from /login to /feed), extracts
    li_at and JSESSIONID cookies and saves them to .env.

    Uses a separate user-data-dir so the login browser doesn't conflict
    with an existing scraper session.
    """
    from playwright.async_api import async_playwright

    log.info("Starting interactive login — a browser window will open.")
    log.info("Log in to LinkedIn manually. The scraper will detect when you're done.")

    pw = None
    context = None
    try:
        pw = await async_playwright().start()

        # Use a separate dir for login to avoid locking the scraper's browser_data
        login_data_dir = Path(config.user_data_dir) / "_login"
        login_data_dir.mkdir(parents=True, exist_ok=True)

        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(login_data_dir),
            headless=False,
            no_viewport=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        log.info("Navigating to LinkedIn login page...")
        await page.goto(LINKEDIN_LOGIN, wait_until="domcontentloaded")

        # Poll until the user logs in (URL leaves /login)
        log.info("Waiting for login... (sign in to LinkedIn in the browser window)")
        for _ in range(600):  # 10 minute timeout
            await asyncio.sleep(1)
            try:
                url = page.url
            except Exception:
                # Page might have been closed by user
                log.error("Browser was closed before login completed.")
                return
            if "/feed" in url or ("/in/" in url and "/login" not in url):
                log.info("Login detected!")
                break
        else:
            log.error("Login timed out after 10 minutes.")
            return

        # Give the page a moment to settle cookies
        await asyncio.sleep(3)

        # Extract cookies
        cookies = await context.cookies("https://www.linkedin.com")
        li_at = ""
        jsessionid = ""
        for cookie in cookies:
            if cookie["name"] == "li_at":
                li_at = cookie["value"]
            elif cookie["name"] == "JSESSIONID":
                jsessionid = cookie["value"]

        if not li_at:
            log.error(
                "Could not find li_at cookie after login. "
                "Try the manual DevTools method instead (see README)."
            )
            return

        # Save to .env
        _save_cookies_to_env(li_at, jsessionid)
        log.info("Cookies saved to .env successfully!")
        log.info("You can now run: python main.py --validate")

    except Exception as e:
        log.error(f"Login failed: {e}", exc_info=True)
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass


def _save_cookies_to_env(li_at: str, jsessionid: str) -> None:
    """Write or update cookie values in the .env file."""
    env_path = Path(".env")
    lines: list[str] = []

    if env_path.exists():
        lines = env_path.read_text().splitlines()

    # Update or append each cookie
    li_at_found = False
    jsessionid_found = False
    for i, line in enumerate(lines):
        if line.startswith("LI_AT_COOKIE="):
            lines[i] = f"LI_AT_COOKIE={li_at}"
            li_at_found = True
        elif line.startswith("JSESSIONID_COOKIE="):
            lines[i] = f"JSESSIONID_COOKIE={jsessionid}"
            jsessionid_found = True

    if not li_at_found:
        lines.append(f"LI_AT_COOKIE={li_at}")
    if not jsessionid_found and jsessionid:
        lines.append(f"JSESSIONID_COOKIE={jsessionid}")

    env_path.write_text("\n".join(lines) + "\n")
