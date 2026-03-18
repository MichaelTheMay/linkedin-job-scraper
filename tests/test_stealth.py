"""Tests for stealth utilities."""

import pytest
from browser.stealth import (
    STEALTH_ARGS,
    STEALTH_INIT_SCRIPT,
    exponential_backoff,
    gaussian_delay,
    human_scroll_steps,
    jittered_delay,
)


class TestGaussianDelay:
    def test_returns_positive(self):
        for _ in range(100):
            delay = gaussian_delay(2.0, 0.5)
            assert delay >= 0.3

    def test_clusters_near_mean(self):
        delays = [gaussian_delay(3.0, 0.5) for _ in range(1000)]
        avg = sum(delays) / len(delays)
        assert 2.5 < avg < 3.5


class TestExponentialBackoff:
    def test_increases_with_attempts(self):
        d0 = exponential_backoff(0, base=10.0, cap=1000.0)
        d1 = exponential_backoff(1, base=10.0, cap=1000.0)
        d2 = exponential_backoff(2, base=10.0, cap=1000.0)
        # Each should roughly double (with jitter)
        assert d1 > d0 * 1.5
        assert d2 > d1 * 1.5

    def test_caps_at_maximum(self):
        delay = exponential_backoff(20, base=30.0, cap=480.0)
        # Should be around 480 + jitter (max 20% = 96)
        assert delay <= 480 * 1.3


class TestHumanScrollSteps:
    def test_covers_full_distance(self):
        steps = human_scroll_steps(1000)
        assert sum(steps) == 1000

    def test_variable_step_sizes(self):
        steps = human_scroll_steps(2000)
        assert len(set(steps)) > 1  # not all the same size


class TestStealthArgs:
    def test_disables_automation_controlled(self):
        assert "--disable-blink-features=AutomationControlled" in STEALTH_ARGS

    def test_has_window_size(self):
        assert any("window-size" in arg for arg in STEALTH_ARGS)


class TestStealthInitScript:
    def test_patches_webdriver(self):
        assert "navigator" in STEALTH_INIT_SCRIPT
        assert "webdriver" in STEALTH_INIT_SCRIPT

    def test_patches_playwright_globals(self):
        assert "__playwright__binding__" in STEALTH_INIT_SCRIPT
        assert "__pwInitScripts" in STEALTH_INIT_SCRIPT

    def test_patches_plugins(self):
        assert "plugins" in STEALTH_INIT_SCRIPT
        assert "Chrome PDF" in STEALTH_INIT_SCRIPT

    def test_patches_webgl(self):
        assert "WebGLRenderingContext" in STEALTH_INIT_SCRIPT
        assert "NVIDIA" in STEALTH_INIT_SCRIPT
