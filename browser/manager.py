"""Browser lifecycle management with stealth configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from browser.stealth import (
    STEALTH_ARGS,
    STEALTH_INIT_SCRIPT,
    block_unnecessary_resources,
    set_stealth_headers,
)
from config.constants import DEFAULT_USER_AGENT, DEFAULT_VIEWPORT
from config.settings import ScraperConfig
from monitor.logger import get_logger

log = get_logger("browser")


class BrowserManager:
    """Manages browser lifecycle: launch, configure stealth, restart, close."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._pages_visited = 0

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Browser not launched. Call launch() first.")
        return self._context

    async def launch(self) -> Page:
        """Launch browser with full stealth configuration."""
        user_data_dir = Path(self.config.user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        log.info(
            "Launching browser",
            extra={"ctx": {
                "headless": self.config.headless,
                "user_data_dir": str(user_data_dir),
            }},
        )

        self._playwright = await async_playwright().start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=self.config.headless,
            args=STEALTH_ARGS,
            user_agent=DEFAULT_USER_AGENT,
            viewport=self.config.viewport or DEFAULT_VIEWPORT,
            locale="en-US",
            timezone_id="America/Chicago",
            ignore_https_errors=True,
        )

        # Apply stealth headers
        await set_stealth_headers(self._context)

        # Create page and apply JS stealth patches
        self._page = await self._context.new_page()
        await self._page.add_init_script(STEALTH_INIT_SCRIPT)

        # Block heavy resources if configured
        if self.config.block_resources:
            await block_unnecessary_resources(self._page)

        self._pages_visited = 0
        log.info("Browser launched with stealth configuration")
        return self._page

    async def new_page(self) -> Page:
        """Create a new page within the existing context (for restarts)."""
        if self._context is None:
            return await self.launch()

        # Close old page if it exists
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass

        self._page = await self._context.new_page()
        await self._page.add_init_script(STEALTH_INIT_SCRIPT)
        if self.config.block_resources:
            await block_unnecessary_resources(self._page)
        self._pages_visited = 0
        return self._page

    def record_page_visit(self) -> None:
        """Track page visits for memory-leak-based browser restarts."""
        self._pages_visited += 1

    @property
    def needs_restart(self) -> bool:
        """True if we've visited enough pages to warrant a browser restart."""
        from config.constants import BROWSER_RESTART_INTERVAL
        return self._pages_visited >= BROWSER_RESTART_INTERVAL

    async def restart(self) -> Page:
        """Restart with a fresh page to avoid Chromium memory leaks."""
        log.info(
            "Restarting browser page (memory management)",
            extra={"ctx": {"pages_visited": self._pages_visited}},
        )
        return await self.new_page()

    async def screenshot(self, path: str = "debug_screenshot.png") -> str:
        """Take a debug screenshot and return the path."""
        if self._page:
            await self._page.screenshot(path=path)
            log.debug(f"Screenshot saved: {path}")
        return path

    async def close(self) -> None:
        """Shut down browser and Playwright."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        log.info("Browser closed")
