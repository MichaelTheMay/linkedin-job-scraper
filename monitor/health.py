"""Session health and rate limit tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from monitor.logger import get_logger

log = get_logger("health")


@dataclass
class HealthTracker:
    """Tracks session health and rate limit state during a scrape run."""

    requests_made: int = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    last_request_time: float = 0.0
    rate_limit_hits: int = 0
    consecutive_errors: int = 0
    _start_time: float = field(default_factory=time.time)

    def record_request(self) -> None:
        self.requests_made += 1
        self.last_request_time = time.time()
        self.consecutive_errors = 0

    def record_error(self, error_type: str) -> None:
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1
        self.consecutive_errors += 1
        if error_type == "RateLimitError":
            self.rate_limit_hits += 1

    def should_abort(self) -> bool:
        """Abort if too many consecutive errors suggest the session is dead."""
        if self.consecutive_errors >= 5:
            log.warning(
                "5 consecutive errors — session may be compromised",
                extra={"ctx": {"consecutive_errors": self.consecutive_errors}},
            )
            return True
        if self.rate_limit_hits >= 3:
            log.warning("Hit rate limit 3 times — backing off aggressively")
            return True
        return False

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def requests_per_minute(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return (self.requests_made / elapsed) * 60

    def summary(self) -> dict:
        return {
            "requests_made": self.requests_made,
            "errors_by_type": self.errors_by_type,
            "rate_limit_hits": self.rate_limit_hits,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "requests_per_minute": round(self.requests_per_minute, 1),
        }
