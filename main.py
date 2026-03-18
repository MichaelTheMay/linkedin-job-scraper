"""LinkedIn Job Scraper — CLI entry point.

Usage:
    python main.py                          # scrape with default config
    python main.py --config custom.yaml     # use custom search profiles
    python main.py --validate               # check session health only
    python main.py --login                  # interactive cookie setup
    python main.py --max-pages 5            # override max pages
    python main.py --no-headless            # run with visible browser
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from browser.interceptor import NetworkInterceptor
from browser.manager import BrowserManager
from browser.session import SessionManager, interactive_login
from browser.stealth import exponential_backoff
from config.constants import PROGRESS_SAVE_INTERVAL
from config.settings import ScraperConfig, SearchProfile, load_config
from data.cleaner import clean_job
from data.deduplicator import Deduplicator
from data.exporter import Exporter
from data.models import Job, ScrapeResult
from monitor.health import HealthTracker
from monitor.logger import get_logger, setup_logging
from scraper.exceptions import (
    AuthExpiredError,
    BotDetectedError,
    ChallengeError,
    ExtractionError,
    PageLoadError,
    RateLimitError,
    ScraperError,
    SessionError,
)
from scraper.job_detail import extract_job
from scraper.job_search import collect_job_urls

log = get_logger()

# Graceful shutdown event — set by signal handler, checked by async loops
_shutdown_event = asyncio.Event()


def _signal_handler(sig, frame):
    _shutdown_event.set()
    log.warning("Shutdown requested (Ctrl+C) — saving progress and exiting...")


async def run_scrape(config: ScraperConfig) -> None:
    """Main scrape orchestration loop."""
    if not config.search_profiles:
        log.error(
            "No search profiles configured. "
            "Add profiles to config/search_profiles.yaml or set SEARCH_KEYWORDS env var."
        )
        return

    browser = BrowserManager(config)
    session = SessionManager(config, browser)
    interceptor = NetworkInterceptor()
    health = HealthTracker()

    try:
        # --- Launch browser ---
        page = await browser.launch()

        # --- Inject cookies and validate session ---
        session_rate_limited = False
        await session.inject_cookies()
        try:
            await session.validate()
            await session.warmup()
        except RateLimitError:
            session_rate_limited = True
            log.warning(
                "Session rate-limited during validation — "
                "will use guest API for URL collection. "
                "Job detail extraction may be limited."
            )

        # --- Start network interceptor ---
        await interceptor.start_listening(page)

        # --- Run each search profile ---
        for profile in config.search_profiles:
            if _shutdown_event.is_set():
                break
            await _run_profile(
                profile,
                page,
                browser,
                session,
                interceptor,
                health,
                config,
                prefer_guest_api=session_rate_limited,
            )

    except SessionError as e:
        log.error(f"Session error: {e}")
    except AuthExpiredError as e:
        log.error(f"Auth expired: {e}")
        await browser.screenshot("error_auth.png")
    except BotDetectedError as e:
        log.error(f"Bot detected: {e}")
        await browser.screenshot("error_bot.png")
        log.error("Wait at least 24 hours before retrying.")
    except ChallengeError as e:
        log.error(f"Challenge: {e}")
        await browser.screenshot("error_challenge.png")
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        await interceptor.stop_listening(browser.page if browser._page else None)
        await browser.close()

    # Final health summary
    log.info(
        "Scraper finished",
        extra={"ctx": health.summary()},
    )


async def _run_profile(
    profile: SearchProfile,
    page: Page,
    browser: BrowserManager,
    session: SessionManager,
    interceptor: NetworkInterceptor,
    health: HealthTracker,
    config: ScraperConfig,
    *,
    prefer_guest_api: bool = False,
) -> None:
    """Run a single search profile: collect URLs → extract details → export."""
    log.info(
        f"=== Starting profile: {profile.name} ===",
        extra={"ctx": {"keywords": profile.keywords, "max_pages": profile.max_pages}},
    )

    result = ScrapeResult(search_profile=profile.name)
    exporter = Exporter(config.output_dir, config.output_format)
    dedup = Deduplicator()
    all_jobs: list[Job] = []

    start_time = time.time()

    # Phase 1: Collect job URLs
    try:
        urls = await collect_job_urls(page, profile, prefer_guest_api=prefer_guest_api)
    except (AuthExpiredError, BotDetectedError, ChallengeError):
        raise  # Let the outer handler deal with fatal errors
    except ScraperError as e:
        log.error(f"URL collection failed: {e}")
        return

    result.total_urls_found = len(urls)
    log.info(f"Phase 1 complete: {len(urls)} URLs collected")

    if not urls:
        log.warning("No job URLs found — check search parameters")
        return

    # Phase 2: Extract job details
    log.info(f"=== Phase 2: Extracting {len(urls)} jobs ===")

    for i, url in enumerate(urls):
        if _shutdown_event.is_set():
            log.warning("Shutdown requested — saving progress")
            break

        if health.should_abort():
            log.error("Too many errors — aborting to protect session")
            break

        log.info(
            f"Job {i + 1}/{len(urls)}",
            extra={"ctx": {"url": url[:80]}},
        )

        # Try extraction with retry for recoverable errors
        job = await _extract_with_retry(page, url, interceptor, health, browser, session)

        if job is None:
            result.total_errors += 1
            continue

        # Clean the data
        job = clean_job(job)

        # Deduplicate
        if dedup.is_duplicate(job):
            result.total_duplicates_skipped += 1
            continue

        dedup.mark_seen(job)
        all_jobs.append(job)
        health.record_request()

        # Track extraction strategy usage
        strategy = job.extraction_strategy.value
        result.extraction_strategy_counts[strategy] = (
            result.extraction_strategy_counts.get(strategy, 0) + 1
        )
        if job.is_partial:
            result.partial_extractions += 1

        # Periodic progress save
        if len(all_jobs) % PROGRESS_SAVE_INTERVAL == 0:
            exporter.save_progress(all_jobs)

        # Browser restart for memory management
        browser.record_page_visit()
        if browser.needs_restart:
            page = await browser.restart()
            await interceptor.start_listening(page)

    # Phase 3: Export results
    result.total_jobs_extracted = len(all_jobs)
    result.total_duplicates_skipped = dedup.duplicates_skipped
    result.elapsed_seconds = time.time() - start_time

    if all_jobs:
        result.output_file = exporter.save_jobs(all_jobs, profile.name)
        exporter.save_summary(result)

    _print_summary(result)


async def _extract_with_retry(
    page,
    url: str,
    interceptor: NetworkInterceptor,
    health: HealthTracker,
    browser: BrowserManager,
    session: SessionManager,
    max_retries: int = 3,
) -> Job | None:
    """Extract a job with retry logic for recoverable errors."""
    for attempt in range(max_retries):
        try:
            return await extract_job(page, url, interceptor)

        except (AuthExpiredError, BotDetectedError, ChallengeError):
            raise  # Fatal — don't retry

        except RateLimitError:
            health.record_error("RateLimitError")
            delay = exponential_backoff(attempt, base=30.0)
            log.warning(
                f"Rate limited — backing off {delay:.0f}s (attempt {attempt + 1})",
                extra={"ctx": {"url": url[:60]}},
            )
            await asyncio.sleep(delay)

        except PageLoadError:
            health.record_error("PageLoadError")
            if attempt < max_retries - 1:
                delay = exponential_backoff(attempt, base=5.0, cap=30.0)
                log.warning(f"Page load failed, retrying in {delay:.0f}s")
                await asyncio.sleep(delay)
            else:
                log.error(f"Page load failed after {max_retries} attempts: {url}")
                return None

        except ExtractionError as e:
            health.record_error("ExtractionError")
            log.warning(f"Extraction failed: {e}")
            return None  # Don't retry extraction failures

        except Exception as e:
            health.record_error("UnexpectedError")
            log.error(f"Unexpected error extracting {url}: {e}", exc_info=True)
            return None

    return None


def _print_summary(result: ScrapeResult) -> None:
    """Print a human-readable run summary."""
    log.info("=" * 60)
    log.info(f"  Profile:     {result.search_profile}")
    log.info(f"  URLs found:  {result.total_urls_found}")
    log.info(f"  Extracted:   {result.total_jobs_extracted}")
    log.info(f"  Duplicates:  {result.total_duplicates_skipped}")
    log.info(f"  Errors:      {result.total_errors}")
    log.info(f"  Partial:     {result.partial_extractions}")
    log.info(f"  Time:        {result.elapsed_seconds:.1f}s")
    if result.extraction_strategy_counts:
        log.info(f"  Strategies:  {result.extraction_strategy_counts}")
    if result.output_file:
        log.info(f"  Output:      {result.output_file}")
    log.info("=" * 60)


async def validate_session(config: ScraperConfig) -> None:
    """Validate session health without scraping."""
    browser = BrowserManager(config)
    session = SessionManager(config, browser)

    try:
        await browser.launch()
        await session.inject_cookies()
        await session.validate()
        log.info("Session is healthy and ready to scrape.")
    except ScraperError as e:
        log.error(f"Session validation failed: {e}")
    finally:
        await browser.close()


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Job Scraper — production-grade job data extraction"
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to YAML config file (default: config/search_profiles.yaml)",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Interactive login — opens a visible browser for cookie capture",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate session health only (no scraping)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Override max pages per search profile",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run with visible browser window",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    args = parser.parse_args()

    # Load config
    config = load_config(config_path=args.config)

    # CLI overrides
    if args.no_headless:
        config.headless = False
    if args.verbose:
        config.verbose = True
        config.log_level = "DEBUG"
    if args.max_pages:
        for profile in config.search_profiles:
            profile.max_pages = args.max_pages

    # Setup logging
    setup_logging(
        log_dir=config.log_dir,
        level=config.log_level,
        verbose=config.verbose,
    )

    # Setup signal handler for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)

    # Run
    if args.login:
        asyncio.run(interactive_login(config))
    elif args.validate:
        asyncio.run(validate_session(config))
    else:
        asyncio.run(run_scrape(config))


if __name__ == "__main__":
    main()
