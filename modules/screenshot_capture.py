"""
modules/screenshot_capture.py
─────────────────────────────────────────────────────────────────────────────
Full-page screenshot capture for debug validation overlays.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import re

from config import FULLPAGE_SCREENSHOTS_DIR

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    """Convert an arbitrary string into a filesystem-safe lowercase filename stem."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "site"


def ensure_fullpage_dir() -> None:
    """Create the full-page screenshot output directory if missing."""
    os.makedirs(FULLPAGE_SCREENSHOTS_DIR, exist_ok=True)


def get_fullpage_screenshot_path(site_name: str) -> str:
    """Return the target full-page screenshot path for a site name."""
    safe_name = _safe_filename(site_name)
    return os.path.join(FULLPAGE_SCREENSHOTS_DIR, f"{safe_name}.png")


def capture_full_page(page, site_name: str) -> str | None:
    """Capture and save a full-page screenshot for the given Playwright page."""
    ensure_fullpage_dir()
    path = get_fullpage_screenshot_path(site_name)

    try:
        page.screenshot(path=path, full_page=True)
        logger.info(f"  📸 Full-page screenshot saved: {path}")
        return path
    except Exception as exc:
        logger.warning(f"  ⚠ Could not save full-page screenshot for {site_name}: {exc}")
        return None
