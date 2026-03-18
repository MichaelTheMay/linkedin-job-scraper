"""Custom exception hierarchy for typed error handling.

Every exception carries context (url, status_code, etc.) so error handlers
can make informed decisions about retry, fallback, or abort.
"""

from __future__ import annotations


class ScraperError(Exception):
    """Base exception for all scraper errors."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        status_code: int | None = None,
    ):
        self.url = url
        self.status_code = status_code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Fatal errors — stop the run, save progress
# ---------------------------------------------------------------------------


class AuthExpiredError(ScraperError):
    """LinkedIn session cookie has expired or been invalidated."""


class ChallengeError(ScraperError):
    """LinkedIn is presenting a CAPTCHA or verification challenge."""


class BotDetectedError(ScraperError):
    """LinkedIn returned HTTP 999 — bot detection triggered."""

    def __init__(self, message: str = "Bot detection triggered (HTTP 999)", **kwargs):
        super().__init__(message, **kwargs)


class SessionError(ScraperError):
    """Cookie missing, malformed, or session cannot be established."""


# ---------------------------------------------------------------------------
# Recoverable errors — retry with backoff
# ---------------------------------------------------------------------------


class RateLimitError(ScraperError):
    """LinkedIn returned HTTP 429 — rate limited."""

    def __init__(
        self,
        message: str = "Rate limited (HTTP 429)",
        *,
        retry_after: int | None = None,
        **kwargs,
    ):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class PageLoadError(ScraperError):
    """Page failed to load (timeout, network error)."""


class EmptyPageError(ScraperError):
    """Search page loaded but contained no job cards."""


# ---------------------------------------------------------------------------
# Extraction errors — try next strategy or skip job
# ---------------------------------------------------------------------------


class ExtractionFallbackError(ScraperError):
    """Current extraction strategy failed — try the next one."""


class ExtractionError(ScraperError):
    """All extraction strategies failed for this job."""
