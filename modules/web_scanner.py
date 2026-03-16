"""
modules/web_scanner.py
─────────────────────────────────────────────────────────────────────────────
Automated website scanning using Playwright.

Research Methodology — Stage 1: Automated Webpage Scanning
────────────────────────────────────────────────────────────
This module reads target URLs from data/sites.csv, opens each page in a
headless Chromium browser, waits for the page to fully settle (including
JavaScript-rendered content), and surfaces the live Playwright page object
so downstream callbacks (e.g. screenshot capture, component detection) can
operate on it before the browser moves to the next URL.

Design decisions aligned with research methodology:
  • networkidle wait-until strategy — ensures AJAX/fetch resources are loaded
    before any DOM extraction or screenshot, reducing incomplete captures.
  • Configurable WAIT_AFTER_LOAD buffer — compensates for deferred JS rendering
    that networkidle alone does not capture.
  • Callback pattern (on_page_ready) — decouples scanning from downstream
    stages, keeping each module independently testable and replaceable.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from config import (
    SITES_CSV,
    BROWSER_HEADLESS,
    PAGE_LOAD_TIMEOUT,
    WAIT_AFTER_LOAD,
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
)

logger = logging.getLogger(__name__)


# ── Site Loading ──────────────────────────────────────────────────────────────

def load_sites(csv_path: str = SITES_CSV) -> pd.DataFrame:
    """
    Load the list of websites to scan from a CSV file.

    The CSV must contain at minimum two columns:
        site_name — human-readable label used in filenames and logs
        url       — fully-qualified URL to scan

    Args:
        csv_path: Path to the sites CSV file. Defaults to config.SITES_CSV.

    Returns:
        pandas DataFrame with one row per site.

    Raises:
        FileNotFoundError: If the CSV file does not exist at csv_path.
        ValueError: If required columns are missing.
    """
    try:
        sites = pd.read_csv(csv_path)
    except FileNotFoundError:
        logger.error(f"Sites CSV not found: {csv_path}")
        raise

    required_columns = {"site_name", "url"}
    missing = required_columns - set(sites.columns)
    if missing:
        raise ValueError(f"sites.csv is missing required columns: {missing}")

    logger.info(f"Loaded {len(sites)} site(s) from {csv_path}")
    return sites


# ── Single-Page Scan ──────────────────────────────────────────────────────────

def scan_page(page, url: str, site_name: str) -> dict:
    """
    Navigate to a URL and wait for the page to fully settle.

    Uses networkidle as the primary load signal, followed by a configurable
    WAIT_AFTER_LOAD buffer to allow deferred JavaScript rendering.

    On timeout, the function logs a warning but still returns success=True
    because a partially loaded page often yields a valid screenshot.

    Args:
        page:      Active Playwright page object.
        url:       The URL to navigate to.
        site_name: Human-readable label for logging and file naming.

    Returns:
        dict with keys:
            site_name   — str
            url         — str
            success     — bool
            page        — Playwright page object (if loaded) or None
            error       — str describing the failure, or None
    """
    result = {
        "site_name": site_name,
        "url":       url,
        "success":   False,
        "page":      None,
        "error":     None,
    }

    try:
        logger.info(f"  → Navigating to {site_name} ({url})")

        # Primary navigation — wait until network connections have settled
        page.goto(url, wait_until="networkidle", timeout=PAGE_LOAD_TIMEOUT)

        # Secondary buffer — absorbs any deferred JS rendering after networkidle
        page.wait_for_timeout(WAIT_AFTER_LOAD)

        result["success"] = True
        result["page"]    = page
        logger.info(f"  ✓ Loaded: {site_name}")

    except PlaywrightTimeoutError:
        # Timeout is common on slow or media-heavy pages; treat as partial load.
        logger.warning(
            f"  ⚠ Timeout on {site_name} ({url}). "
            "Proceeding with partial page load."
        )
        result["success"] = True   # Partial load — screenshot may still be valid
        result["page"]    = page

    except Exception as exc:
        logger.error(f"  ✗ Failed to scan {site_name} ({url}): {exc}")
        result["error"] = str(exc)

    return result


# ── Full-Scan Orchestrator ────────────────────────────────────────────────────

def run_scanner(sites: pd.DataFrame, on_page_ready=None) -> list:
    """
    Launch a headless Chromium browser and scan every site in the DataFrame.

    For each site a new browser page is opened, navigated, and — on success —
    the optional on_page_ready callback is invoked with the result dict.  The
    callback receives the live Playwright page object so screenshot capture
    and component detection can run against the rendered DOM before the
    browser moves on.

    Args:
        sites:         DataFrame produced by load_sites().
        on_page_ready: Optional callable(result: dict).  Called once per
                       successfully loaded page.  Any exception raised inside
                       the callback is caught and logged so it cannot abort
                       the rest of the scan.

    Returns:
        List of result dicts, one per site, in the same order as the input
        DataFrame.  Each dict has the keys described in scan_page().
    """
    results = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=BROWSER_HEADLESS)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
        )

        for _, row in sites.iterrows():
            site_name = str(row["site_name"])
            url       = str(row["url"])

            # Each site gets a fresh page to avoid state bleed between sites
            page   = context.new_page()
            result = scan_page(page, url, site_name)

            # Invoke the downstream callback while the page is still live
            if result["success"] and on_page_ready is not None:
                try:
                    on_page_ready(result)
                except Exception as exc:
                    logger.error(
                        f"  ✗ Callback error for {site_name}: {exc}"
                    )

            page.close()
            results.append(result)

        context.close()
        browser.close()

    return results
