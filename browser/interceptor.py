"""Network interceptor — capture LinkedIn's Voyager API responses.

Instead of parsing brittle DOM, we intercept the structured JSON responses
that LinkedIn's own frontend uses to render job data. This is the most
reliable extraction method.
"""

from __future__ import annotations

import json
from typing import Any

from playwright.async_api import Page, Response

from config.constants import VOYAGER_API_PREFIX
from monitor.logger import get_logger

log = get_logger("interceptor")


class NetworkInterceptor:
    """Captures Voyager API responses from the browser's network traffic."""

    def __init__(self):
        self._captured_responses: list[dict[str, Any]] = []
        self._is_listening = False

    @property
    def responses(self) -> list[dict[str, Any]]:
        return list(self._captured_responses)

    def clear(self) -> None:
        """Clear captured responses for the next page."""
        self._captured_responses.clear()

    async def start_listening(self, page: Page) -> None:
        """Attach response listener to the page."""
        if self._is_listening:
            return

        page.on("response", self._on_response)
        self._is_listening = True
        log.debug("Network interceptor listening for Voyager API responses")

    async def stop_listening(self, page: Page | None) -> None:
        """Detach response listener."""
        if page:
            try:
                page.remove_listener("response", self._on_response)
            except Exception:
                pass
        self._is_listening = False

    async def _on_response(self, response: Response) -> None:
        """Handle each network response — capture Voyager API JSON."""
        url = response.url

        if VOYAGER_API_PREFIX not in url:
            return

        # Only capture successful JSON responses
        if response.status != 200:
            return

        content_type = response.headers.get("content-type", "")
        if "json" not in content_type and "javascript" not in content_type:
            return

        try:
            body = await response.text()
            data = json.loads(body)
            self._captured_responses.append(
                {
                    "url": url,
                    "data": data,
                    "status": response.status,
                }
            )
            log.debug(
                "Captured Voyager API response",
                extra={"ctx": {"url": _truncate_url(url), "keys": _top_keys(data)}},
            )
        except json.JSONDecodeError:
            log.debug(f"Non-JSON Voyager response: {_truncate_url(url)}")
        except Exception as e:
            log.debug(f"Error capturing response: {e}")

    def find_job_data(self, job_id: str) -> dict[str, Any] | None:
        """Search captured responses for data about a specific job ID.

        LinkedIn's Voyager API returns job data in various nested structures.
        We search for the job ID in common locations.
        """
        for resp in self._captured_responses:
            data = resp.get("data", {})
            result = _find_in_voyager(data, job_id)
            if result:
                return result
        return None

    def find_job_search_results(self) -> list[dict[str, Any]]:
        """Extract job card data from search results API responses."""
        results = []
        for resp in self._captured_responses:
            data = resp.get("data", {})
            # Voyager search results are typically in `included` array
            included = data.get("included", [])
            for item in included:
                entity_urn = item.get("entityUrn", "")
                if "jobPosting" in entity_urn or "fs_miniJob" in str(item.get("$type", "")):
                    results.append(item)
        return results


def _find_in_voyager(data: Any, job_id: str) -> dict | None:
    """Recursively search Voyager response for job data matching an ID."""
    if isinstance(data, dict):
        # Check if this dict itself contains the job ID
        entity_urn = data.get("entityUrn", "")
        if job_id in entity_urn:
            return data

        # Check inside common Voyager response structures
        for key in ("included", "elements", "data"):
            if key in data:
                result = _find_in_voyager(data[key], job_id)
                if result:
                    return result

    elif isinstance(data, list):
        for item in data:
            result = _find_in_voyager(item, job_id)
            if result:
                return result

    return None


def _truncate_url(url: str, max_len: int = 80) -> str:
    return url[:max_len] + "..." if len(url) > max_len else url


def _top_keys(data: Any) -> str:
    if isinstance(data, dict):
        keys = list(data.keys())[:5]
        return ", ".join(keys)
    return type(data).__name__
