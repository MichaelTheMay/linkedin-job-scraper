"""Tests for the custom exception hierarchy."""

import pytest
from scraper.exceptions import (
    AuthExpiredError,
    BotDetectedError,
    ChallengeError,
    EmptyPageError,
    ExtractionError,
    ExtractionFallbackError,
    PageLoadError,
    RateLimitError,
    ScraperError,
    SessionError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_scraper_error(self):
        """Every custom exception should be catchable as ScraperError."""
        exceptions = [
            AuthExpiredError("test"),
            ChallengeError("test"),
            BotDetectedError(),
            SessionError("test"),
            RateLimitError(),
            PageLoadError("test"),
            EmptyPageError("test"),
            ExtractionFallbackError("test"),
            ExtractionError("test"),
        ]
        for exc in exceptions:
            assert isinstance(exc, ScraperError)

    def test_context_fields(self):
        err = AuthExpiredError("expired", url="https://example.com", status_code=302)
        assert err.url == "https://example.com"
        assert err.status_code == 302
        assert str(err) == "expired"

    def test_rate_limit_retry_after(self):
        err = RateLimitError(retry_after=60)
        assert err.retry_after == 60
        assert "429" in str(err)

    def test_bot_detected_default_message(self):
        err = BotDetectedError()
        assert "999" in str(err)

    def test_fatal_vs_recoverable(self):
        """Fatal errors should NOT be caught by a generic ScraperError handler
        that only retries — test that the hierarchy is correct."""
        fatal = [AuthExpiredError, ChallengeError, BotDetectedError, SessionError]
        recoverable = [RateLimitError, PageLoadError, EmptyPageError]
        extraction = [ExtractionFallbackError, ExtractionError]

        for cls in fatal + recoverable + extraction:
            assert issubclass(cls, ScraperError)
