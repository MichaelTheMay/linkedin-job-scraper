"""Tests for configuration loading."""

import os
import tempfile

import pytest
import yaml
from config.settings import ScraperConfig, SearchProfile, load_config


class TestLoadConfig:
    def test_loads_from_env(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('LI_AT_COOKIE=test_cookie_value\nJSESSIONID_COOKIE=ajax:123\n')
        # Create an empty yaml so it doesn't try to load default
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("search_profiles: []")

        monkeypatch.setenv("LI_AT_COOKIE", "test_cookie_value")
        monkeypatch.setenv("JSESSIONID_COOKIE", "ajax:123")

        config = load_config(config_path=str(yaml_file), env_path=str(env_file))
        assert config.li_at_cookie == "test_cookie_value"
        assert config.jsessionid_cookie == "ajax:123"

    def test_loads_search_profiles_from_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LI_AT_COOKIE", "x")
        yaml_content = {
            "search_profiles": [
                {
                    "name": "test-search",
                    "keywords": "python developer",
                    "location": "Austin, TX",
                    "max_pages": 3,
                }
            ]
        }
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml.dump(yaml_content))

        config = load_config(config_path=str(yaml_file))
        assert len(config.search_profiles) == 1
        assert config.search_profiles[0].name == "test-search"
        assert config.search_profiles[0].keywords == "python developer"
        assert config.search_profiles[0].max_pages == 3

    def test_default_profile_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LI_AT_COOKIE", "x")
        monkeypatch.setenv("SEARCH_KEYWORDS", "data scientist")
        monkeypatch.setenv("SEARCH_LOCATION", "NYC")

        # No yaml file
        config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
        assert len(config.search_profiles) == 1
        assert config.search_profiles[0].keywords == "data scientist"


class TestSearchProfile:
    def test_defaults(self):
        profile = SearchProfile(name="test", keywords="engineer")
        assert profile.max_pages == 10
        assert profile.distance == 25.0
        assert profile.time_filter == "r2592000"
