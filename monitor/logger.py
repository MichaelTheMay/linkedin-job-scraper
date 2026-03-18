"""Structured logging — replaces all print() calls.

Console: human-readable colored output.
File:    JSON-lines for programmatic parsing.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for the file handler."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra context passed via `extra={"ctx": {...}}`
        ctx = getattr(record, "ctx", None)
        if ctx:
            entry["ctx"] = ctx
        return json.dumps(entry, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console output with level prefixes."""

    LEVEL_PREFIXES = {
        "DEBUG": "\033[90m[DBG]\033[0m",
        "INFO": "\033[36m[INF]\033[0m",
        "WARNING": "\033[33m[WRN]\033[0m",
        "ERROR": "\033[31m[ERR]\033[0m",
        "CRITICAL": "\033[31;1m[CRT]\033[0m",
    }

    def format(self, record: logging.LogRecord) -> str:
        prefix = self.LEVEL_PREFIXES.get(record.levelname, f"[{record.levelname}]")
        msg = record.getMessage()
        ctx = getattr(record, "ctx", None)
        if ctx:
            ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items())
            msg = f"{msg}  ({ctx_str})"
        return f"{prefix} {msg}"


def setup_logging(
    log_dir: str = "./logs",
    level: str = "INFO",
    verbose: bool = False,
) -> logging.Logger:
    """Configure the root scraper logger with console + file handlers."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("scraper")
    logger.setLevel(logging.DEBUG if verbose else getattr(logging, level.upper()))
    logger.handlers.clear()

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else getattr(logging, level.upper()))
    console.setFormatter(ConsoleFormatter())
    logger.addHandler(console)

    # File handler — JSON lines
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = logging.FileHandler(
        log_path / f"scrape_{timestamp}.jsonl", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Get a child logger under the scraper namespace."""
    base = "scraper"
    return logging.getLogger(f"{base}.{name}" if name else base)
