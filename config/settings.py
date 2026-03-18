"""Load scraper configuration from YAML + environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from config.constants import DEFAULT_MAX_PAGES, DEFAULT_VIEWPORT


@dataclass
class SearchProfile:
    """A single job search configuration."""

    name: str
    keywords: str
    location: str = ""
    geo_id: str = ""
    distance: float = 25.0
    time_filter: str = "r2592000"  # past month
    experience_levels: list[str] = field(default_factory=list)
    job_types: list[str] = field(default_factory=list)
    max_pages: int = DEFAULT_MAX_PAGES


@dataclass
class ScraperConfig:
    """Top-level scraper configuration."""

    # Auth
    li_at_cookie: str = ""
    jsessionid_cookie: str = ""

    # Browser
    headless: bool = True
    user_data_dir: str = "./browser_data"
    viewport: dict = field(default_factory=lambda: dict(DEFAULT_VIEWPORT))
    block_resources: bool = True

    # Output
    output_dir: str = "./output"
    output_format: str = "csv"  # csv, json, both

    # Search profiles
    search_profiles: list[SearchProfile] = field(default_factory=list)

    # Logging
    log_dir: str = "./logs"
    log_level: str = "INFO"
    verbose: bool = False


def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
) -> ScraperConfig:
    """Load config from YAML file + .env, with env vars taking precedence."""
    load_dotenv(env_path or ".env")

    config = ScraperConfig()

    # Environment variables (highest priority)
    config.li_at_cookie = os.environ.get("LI_AT_COOKIE", "")
    config.jsessionid_cookie = os.environ.get("JSESSIONID_COOKIE", "")
    config.headless = os.environ.get("HEADLESS", "true").lower() == "true"

    # YAML config file
    yaml_path = Path(config_path or "config/search_profiles.yaml")
    if yaml_path.exists():
        with open(yaml_path, "r") as f:
            raw = yaml.safe_load(f) or {}

        # Browser settings
        browser = raw.get("browser", {})
        if "headless" in browser:
            config.headless = browser["headless"]
        if "user_data_dir" in browser:
            config.user_data_dir = browser["user_data_dir"]
        if "block_resources" in browser:
            config.block_resources = browser["block_resources"]

        # Output settings
        output = raw.get("output", {})
        if "dir" in output:
            config.output_dir = output["dir"]
        if "format" in output:
            config.output_format = output["format"]

        # Logging
        logging_cfg = raw.get("logging", {})
        if "level" in logging_cfg:
            config.log_level = logging_cfg["level"]
        if "dir" in logging_cfg:
            config.log_dir = logging_cfg["dir"]

        # Search profiles
        for profile_raw in raw.get("search_profiles", []):
            config.search_profiles.append(
                SearchProfile(
                    name=profile_raw.get("name", "default"),
                    keywords=profile_raw["keywords"],
                    location=profile_raw.get("location", ""),
                    geo_id=profile_raw.get("geo_id", ""),
                    distance=profile_raw.get("distance", 25.0),
                    time_filter=profile_raw.get("time_filter", "r2592000"),
                    experience_levels=profile_raw.get("experience_levels", []),
                    job_types=profile_raw.get("job_types", []),
                    max_pages=profile_raw.get("max_pages", DEFAULT_MAX_PAGES),
                )
            )

    # Default search profile if none configured
    if not config.search_profiles:
        keywords = os.environ.get("SEARCH_KEYWORDS", "")
        location = os.environ.get("SEARCH_LOCATION", "")
        if keywords:
            config.search_profiles.append(
                SearchProfile(name="default", keywords=keywords, location=location)
            )

    return config
