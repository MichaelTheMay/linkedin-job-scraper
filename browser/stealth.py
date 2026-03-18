"""Anti-detection stealth patches — 5 layers of protection.

Layer 1: Browser launch flags
Layer 2: JavaScript property patches (init scripts)
Layer 3: Behavioral stealth helpers (delays, scrolling)
Layer 4: Network stealth (headers, resource blocking)
Layer 5: Session stealth (cookie management)
"""

from __future__ import annotations

import math
import random

from config.constants import (
    BLOCKED_RESOURCE_PATTERNS,
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
)

# ---------------------------------------------------------------------------
# Layer 1: Chrome launch arguments
# ---------------------------------------------------------------------------

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    f"--window-size={DEFAULT_VIEWPORT['width']},{DEFAULT_VIEWPORT['height']}",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--lang=en-US",
]


# ---------------------------------------------------------------------------
# Layer 2: JavaScript init script patches
# ---------------------------------------------------------------------------

STEALTH_INIT_SCRIPT = """
// --- navigator.webdriver ---
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
});

// --- Remove Playwright globals ---
delete window.__playwright__binding__;
delete window.__pwInitScripts;

// --- chrome.runtime (headless lacks this) ---
if (!window.chrome) { window.chrome = {}; }
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
    };
}

// --- navigator.plugins (headless has empty array) ---
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        return [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer',
              description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
              description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin',
              description: '' },
        ];
    },
    configurable: true,
});

// --- navigator.languages ---
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
});

// --- navigator.hardwareConcurrency ---
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
    configurable: true,
});

// --- screen.colorDepth ---
Object.defineProperty(screen, 'colorDepth', {
    get: () => 24,
    configurable: true,
});

// --- permissions.query (notifications) ---
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => {
    if (parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
    }
    return originalQuery(parameters);
};

// --- WebGL vendor/renderer ---
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL
    if (parameter === 37445) {
        return 'Google Inc. (NVIDIA)';
    }
    // UNMASKED_RENDERER_WEBGL
    if (parameter === 37446) {
        return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    }
    return getParameter.call(this, parameter);
};
"""


# ---------------------------------------------------------------------------
# Layer 3: Behavioral stealth
# ---------------------------------------------------------------------------


def gaussian_delay(mean: float, sigma: float = 0.5) -> float:
    """Return a gaussian-distributed delay (clamped to positive values).

    More human-like than uniform random — most delays cluster near the mean
    with occasional longer pauses.
    """
    delay = random.gauss(mean, sigma)
    return max(0.3, delay)  # never less than 300ms


def jittered_delay(base: float, jitter_pct: float = 0.3) -> float:
    """Return base delay with ±jitter_pct random variation."""
    jitter = base * jitter_pct
    return base + random.uniform(-jitter, jitter)


def exponential_backoff(attempt: int, base: float = 30.0, cap: float = 480.0) -> float:
    """Exponential backoff with jitter, capped at `cap` seconds."""
    delay = min(base * (2 ** attempt), cap)
    jitter = delay * 0.2 * random.random()
    return delay + jitter


def human_scroll_steps(total_distance: int) -> list[int]:
    """Generate a list of scroll step sizes that mimic human scrolling.

    Humans scroll in bursts with variable speed, not at a constant rate.
    """
    steps = []
    remaining = total_distance
    while remaining > 0:
        step = random.randint(80, 300)
        step = min(step, remaining)
        steps.append(step)
        remaining -= step
    return steps


# ---------------------------------------------------------------------------
# Layer 4: Network stealth
# ---------------------------------------------------------------------------

EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
}


async def block_unnecessary_resources(page) -> None:
    """Block images, fonts, and tracking scripts to speed up page loads."""
    for pattern in BLOCKED_RESOURCE_PATTERNS:
        await page.route(pattern, lambda route: route.abort())


async def set_stealth_headers(context) -> None:
    """Set extra headers on the browser context for network stealth."""
    await context.set_extra_http_headers(EXTRA_HEADERS)
