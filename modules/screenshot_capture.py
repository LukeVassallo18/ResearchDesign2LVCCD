"""
modules/screenshot_capture.py
─────────────────────────────────────────────────────────────────────────────
Full-page screenshot capture using Playwright.

Research Methodology — Stage 3: Screenshot Capture
────────────────────────────────────────────────────
Screenshots serve as the visual input for subsequent pipeline stages:
  • CVD simulation   — the captured image is transformed per deficiency type
  • Contrast analysis — pixel colours are sampled from the transformed image

Each screenshot is named after its site so results remain traceable back to
their source throughout the pipeline.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import re
import logging

from config import SCREENSHOTS_DIR

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """
    Convert an arbitrary string into a filesystem-safe filename stem.

    Replaces whitespace and path-unsafe characters with underscores and
    converts to lowercase for consistent naming across platforms.

    Args:
        name: Raw site name or identifier string.

    Returns:
        Sanitised lowercase string suitable for use in a file path.
    """
    name = name.lower().strip()
    name = re.sub(r"[^\w\-]", "_", name)   # replace non-word chars with _
    name = re.sub(r"_+", "_", name)         # collapse consecutive underscores
    return name


def ensure_screenshots_dir() -> None:
    """Create the screenshots output directory if it does not already exist."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


# ── Screenshot Capture ────────────────────────────────────────────────────────

def capture_full_page(page, site_name: str) -> str | None:
    """
    Capture a full-page screenshot of the currently loaded Playwright page.

    Playwright's full_page=True option scrolls the entire document height and
    stitches the result into a single PNG, making it suitable for capturing
    below-the-fold content without manual scrolling.

    Args:
        page:      Active Playwright page object pointing at the loaded site.
        site_name: Human-readable site label; used to derive the filename.

    Returns:
        Absolute path to the saved PNG file, or None if capture failed.
    """
    ensure_screenshots_dir()

    safe_name = _safe_filename(site_name)
    filename  = f"{safe_name}_fullpage.png"
    filepath  = os.path.join(SCREENSHOTS_DIR, filename)

    try:
        page.screenshot(path=filepath, full_page=True)
        logger.info(f"  📸 Screenshot saved: {filepath}")
        return filepath
    except Exception as exc:
        logger.error(f"  ✗ Screenshot failed for {site_name}: {exc}")
        return None
