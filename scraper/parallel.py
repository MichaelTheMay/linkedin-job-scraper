"""Parallel guest API scraping — probe total results, dispatch N workers.

The guest API returns ~10 results per page, no auth needed, and each worker
runs in its own browser context. This module:
  1. Probes total result count via binary search (~6 requests)
  2. Launches N parallel browser contexts (one per page chunk)
  3. Each worker extracts URLs + card metadata (title, company, location, date)
  4. Merges and deduplicates results
"""

from __future__ import annotations

import asyncio
import math
import urllib.parse
from dataclasses import dataclass, field

from playwright.async_api import Page, async_playwright

from browser.stealth import STEALTH_ARGS, gaussian_delay
from config.constants import (
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
    GUEST_JOB_SEARCH_API,
    MAX_TOTAL_RESULTS,
)
from config.settings import SearchProfile
from monitor.logger import get_logger

log = get_logger("parallel")

# Guest API returns 10 results per page (not 25 like authenticated search)
GUEST_RESULTS_PER_PAGE = 10

# Max parallel browser contexts
MAX_WORKERS = 8


@dataclass
class JobCard:
    """Job data extracted from search card + optional detail enrichment."""

    job_id: str
    url: str
    title: str = ""
    company: str = ""
    location: str = ""
    posted_date: str = ""
    salary: str = ""
    badge: str = ""  # "Actively Hiring", "Be an early applicant", etc.

    # Enriched from detail page (populated by enrich_cards)
    description: str = ""
    applicant_count: int | None = None
    seniority_level: str = ""
    employment_type: str = ""
    job_function: str = ""
    industries: str = ""


@dataclass
class ParallelResult:
    """Result from parallel URL collection."""

    cards: list[JobCard] = field(default_factory=list)
    total_results_probed: int = 0
    pages_scraped: int = 0
    workers_used: int = 0
    elapsed_seconds: float = 0.0


def _build_guest_url(profile: SearchProfile, start: int = 0) -> str:
    """Build a guest API search URL."""
    params: dict[str, str] = {"keywords": profile.keywords}
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


async def parallel_collect(
    profile: SearchProfile,
    *,
    max_workers: int = MAX_WORKERS,
    enrich: bool = True,
) -> ParallelResult:
    """Probe total results, then dispatch parallel workers to collect all URLs.

    Each worker is an independent headless browser context (no cookies, no
    shared state). Returns deduplicated JobCards with metadata.

    If enrich=True (default), hits guest detail pages in parallel to grab
    full description, applicant count, seniority level, and employment type.
    """
    import time

    start_time = time.time()

    # Phase 1: Probe total result count
    total = await _probe_total_results(profile)
    if total == 0:
        log.warning("No results found for this search profile")
        return ParallelResult(total_results_probed=0)

    total_pages = math.ceil(total / GUEST_RESULTS_PER_PAGE)
    # Cap by profile's max_pages (converted to guest page count)
    max_guest_pages = profile.max_pages * (25 // GUEST_RESULTS_PER_PAGE)
    total_pages = min(total_pages, max_guest_pages)

    log.info(
        f"Probed ~{total} results across {total_pages} pages",
        extra={"ctx": {"total": total, "pages": total_pages}},
    )

    # Phase 2: Determine worker count and page assignments
    num_workers = min(max_workers, total_pages)
    pages_per_worker = math.ceil(total_pages / num_workers)

    # Build page assignments: [(start_page, end_page), ...]
    assignments: list[tuple[int, int]] = []
    for i in range(num_workers):
        page_start = i * pages_per_worker
        page_end = min(page_start + pages_per_worker, total_pages)
        if page_start < total_pages:
            assignments.append((page_start, page_end))

    log.info(
        f"Dispatching {len(assignments)} parallel workers",
        extra={
            "ctx": {
                "workers": len(assignments),
                "pages_per_worker": pages_per_worker,
                "total_pages": total_pages,
            }
        },
    )

    # Phase 3: Launch parallel workers
    tasks = [
        _worker(profile, worker_id, page_start, page_end)
        for worker_id, (page_start, page_end) in enumerate(assignments)
    ]
    worker_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Phase 4: Merge and deduplicate
    all_cards: dict[str, JobCard] = {}
    total_pages_scraped = 0

    for i, result in enumerate(worker_results):
        if isinstance(result, Exception):
            log.error(f"Worker {i} failed: {result}")
            continue
        cards, pages = result
        total_pages_scraped += pages
        for card in cards:
            if card.job_id not in all_cards:
                all_cards[card.job_id] = card

    card_list = list(all_cards.values())
    collect_elapsed = time.time() - start_time
    log.info(
        f"URL collection complete: {len(card_list)} unique jobs "
        f"from {total_pages_scraped} pages in {collect_elapsed:.1f}s",
    )

    # Phase 5: Enrich with detail pages (parallel)
    if enrich and card_list:
        log.info(f"Enriching {len(card_list)} jobs with detail pages...")
        await _enrich_cards_parallel(card_list, max_workers=max_workers)

    elapsed = time.time() - start_time
    log.info(f"Total parallel scrape: {len(card_list)} jobs in {elapsed:.1f}s")

    return ParallelResult(
        cards=card_list,
        total_results_probed=total,
        pages_scraped=total_pages_scraped,
        workers_used=len(assignments),
        elapsed_seconds=elapsed,
    )


async def _probe_total_results(profile: SearchProfile) -> int:
    """Binary search to find how many results exist.

    The guest API returns empty HTML when start exceeds total results.
    We binary search to find the last page with data. ~6 HTTP requests.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        # First check if there are any results at all
        count = await _count_results_on_page(page, profile, start=0)
        if count == 0:
            return 0

        # Binary search for the last page with results
        lo, hi = 0, MAX_TOTAL_RESULTS
        while lo < hi - GUEST_RESULTS_PER_PAGE:
            mid = ((lo + hi) // 2 // GUEST_RESULTS_PER_PAGE) * GUEST_RESULTS_PER_PAGE
            count = await _count_results_on_page(page, profile, start=mid)
            if count > 0:
                lo = mid
            else:
                hi = mid

        # lo is the last start value with results
        last_count = await _count_results_on_page(page, profile, start=lo)
        total = lo + last_count
        log.info(f"Binary search complete: ~{total} total results (last page start={lo})")
        return total

    finally:
        await browser.close()
        await pw.stop()


async def _count_results_on_page(page: Page, profile: SearchProfile, start: int) -> int:
    """Load a guest API page and count how many job cards it has."""
    url = _build_guest_url(profile, start=start)
    try:
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(0.5)
        count = await page.evaluate("document.querySelectorAll('[data-entity-urn]').length")
        return count or 0
    except Exception as e:
        log.debug(f"Probe failed at start={start}: {e}")
        return 0


async def _worker(
    profile: SearchProfile,
    worker_id: int,
    page_start: int,
    page_end: int,
) -> tuple[list[JobCard], int]:
    """A single parallel worker — own browser, scrapes assigned page range.

    Returns (cards, pages_scraped).
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=STEALTH_ARGS,
    )
    context = await browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport=DEFAULT_VIEWPORT,  # type: ignore[arg-type]
    )
    page = await context.new_page()

    cards: list[JobCard] = []
    pages_scraped = 0

    try:
        for page_num in range(page_start, page_end):
            start_val = page_num * GUEST_RESULTS_PER_PAGE
            url = _build_guest_url(profile, start=start_val)

            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as e:
                log.warning(f"Worker {worker_id}: page {page_num} load failed: {e}")
                break

            await asyncio.sleep(gaussian_delay(1.0, 0.3))

            # Extract all card data from this page
            page_cards = await _extract_cards(page)
            pages_scraped += 1

            if not page_cards:
                log.debug(f"Worker {worker_id}: no cards on page {page_num}, stopping")
                break

            cards.extend(page_cards)

            log.debug(
                f"Worker {worker_id}: page {page_num + 1} — "
                f"{len(page_cards)} cards (total {len(cards)})"
            )

            # Brief delay between pages
            if page_num < page_end - 1:
                await asyncio.sleep(gaussian_delay(0.8, 0.2))

    finally:
        await context.close()
        await browser.close()
        await pw.stop()

    log.info(
        f"Worker {worker_id} done: {len(cards)} cards from {pages_scraped} pages "
        f"(range {page_start}-{page_end})"
    )
    return cards, pages_scraped


async def _extract_cards(page: Page) -> list[JobCard]:
    """Extract all job cards with metadata from a guest API search page."""
    raw_cards = await page.evaluate("""() => {
        const cards = [];
        document.querySelectorAll('[data-entity-urn]').forEach(el => {
            const urn = el.getAttribute('data-entity-urn') || '';
            const idMatch = urn.match(/jobPosting:(\\d+)/);
            if (!idMatch) return;

            const jobId = idMatch[1];

            // URL from the full-link anchor
            let url = '';
            const link = el.querySelector('a.base-card__full-link');
            if (link) {
                const href = link.href || link.getAttribute('href') || '';
                url = `https://www.linkedin.com/jobs/view/${jobId}/`;
            }

            // Title
            const titleEl = el.querySelector('h3.base-search-card__title');
            const title = titleEl ? titleEl.textContent.trim() : '';

            // Company
            const companyEl = el.querySelector('h4.base-search-card__subtitle');
            const company = companyEl ? companyEl.textContent.trim() : '';

            // Location
            const locationEl = el.querySelector('span.job-search-card__location');
            const location = locationEl ? locationEl.textContent.trim() : '';

            // Posted date (datetime attribute is ISO format)
            const timeEl = el.querySelector('time.job-search-card__listdate');
            const postedDate = timeEl
                ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim())
                : '';

            // Salary (not always present)
            const salaryEl = el.querySelector('span.job-search-card__salary-info');
            const salary = salaryEl ? salaryEl.textContent.trim() : '';

            // Badge text ("Actively Hiring", "Be an early applicant", etc.)
            const badgeEl = el.querySelector('.job-posting-benefits__text');
            const badge = badgeEl ? badgeEl.textContent.trim() : '';

            cards.push({
                jobId, url, title, company, location, postedDate, salary, badge
            });
        });
        return cards;
    }""")

    return [
        JobCard(
            job_id=c["jobId"],
            url=c["url"] or f"https://www.linkedin.com/jobs/view/{c['jobId']}/",
            title=c.get("title", ""),
            company=c.get("company", ""),
            location=c.get("location", ""),
            posted_date=c.get("postedDate", ""),
            salary=c.get("salary", ""),
            badge=c.get("badge", ""),
        )
        for c in raw_cards
    ]


# ---------------------------------------------------------------------------
# Phase 5: Detail enrichment (parallel)
# ---------------------------------------------------------------------------

ENRICH_BATCH_SIZE = 40  # cards per enrichment worker


async def _enrich_cards_parallel(cards: list[JobCard], *, max_workers: int = MAX_WORKERS) -> None:
    """Hit guest detail pages in parallel to enrich cards with full data.

    Modifies cards in-place. Each worker gets a batch of cards and its own
    browser context.
    """
    batches: list[list[JobCard]] = []
    for i in range(0, len(cards), ENRICH_BATCH_SIZE):
        batches.append(cards[i : i + ENRICH_BATCH_SIZE])

    num_workers = min(max_workers, len(batches))
    log.info(f"Enriching with {num_workers} workers ({len(batches)} batches, {len(cards)} jobs)")

    tasks = [_enrich_worker(worker_id, batch) for worker_id, batch in enumerate(batches)]
    await asyncio.gather(*tasks, return_exceptions=True)

    enriched = sum(1 for c in cards if c.applicant_count or c.seniority_level)
    log.info(f"Enrichment complete: {enriched}/{len(cards)} jobs with detail data")


async def _enrich_worker(worker_id: int, cards: list[JobCard]) -> int:
    """Enrich a batch of cards by visiting their guest detail pages."""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True, args=STEALTH_ARGS)
    context = await browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport=DEFAULT_VIEWPORT,  # type: ignore[arg-type]
    )
    page = await context.new_page()
    enriched = 0

    try:
        for card in cards:
            try:
                await page.goto(card.url, wait_until="domcontentloaded")
                await asyncio.sleep(gaussian_delay(0.8, 0.2))
                detail = await _extract_detail(page)

                card.description = detail.get("description", "")
                card.applicant_count = detail.get("applicant_count")
                card.seniority_level = detail.get("seniority_level", "")
                card.employment_type = detail.get("employment_type", "")
                card.job_function = detail.get("job_function", "")
                card.industries = detail.get("industries", "")
                enriched += 1

            except Exception as e:
                log.debug(f"Enrich failed for {card.job_id}: {e}")

    finally:
        await context.close()
        await browser.close()
        await pw.stop()

    log.info(f"Enrich worker {worker_id}: {enriched}/{len(cards)} enriched")
    return enriched


async def _extract_detail(page: Page) -> dict:
    """Extract full detail data from a guest job detail page."""
    return await page.evaluate("""() => {
        const result = {};

        // Description
        const descEl = document.querySelector('.description__text, .show-more-less-html__markup');
        if (descEl) {
            result.description = descEl.textContent.trim().substring(0, 10000);
        }

        // Applicant count ("138 applicants")
        const appEl = document.querySelector('.num-applicants__caption');
        if (appEl) {
            const m = appEl.textContent.match(/(\\d[\\d,]*)/);
            if (m) result.applicant_count = parseInt(m[1].replace(/,/g, ''));
        }

        // Job criteria (seniority, employment type, job function, industries)
        const criteria = document.querySelectorAll('.description__job-criteria-item');
        criteria.forEach(item => {
            const label = item.querySelector('.description__job-criteria-subheader');
            const value = item.querySelector('.description__job-criteria-text');
            if (!label || !value) return;
            const l = label.textContent.trim().toLowerCase();
            const v = value.textContent.trim();
            if (l.includes('seniority')) result.seniority_level = v;
            else if (l.includes('employment')) result.employment_type = v;
            else if (l.includes('function')) result.job_function = v;
            else if (l.includes('industr')) result.industries = v;
        });

        return result;
    }""")
