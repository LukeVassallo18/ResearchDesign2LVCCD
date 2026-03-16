"""
run_scan.py
─────────────────────────────────────────────────────────────────────────────
Main entry point for the CVD Accessibility Audit pipeline.

Current Stage: Website Scanning & Screenshot Capture
──────────────────────────────────────────────────────
This script executes the first two operational stages of the research
methodology pipeline:

    Stage 1 — Load websites from data/sites.csv
    Stage 2 — Open each page in a headless Playwright browser
    Stage 3 — Wait for the page to fully load (network + JS settle time)
    Stage 4 — Capture a full-page PNG screenshot
    Stage 5 — Save screenshots to screenshots/

Stages not yet implemented (planned for later iterations):
    Stage 6 — UI component detection
    Stage 7 — CVD simulation (protanopia / deuteranopia / tritanopia)
    Stage 8 — WCAG contrast analysis per component
    Stage 9 — Risk classification (Pass / Warning / Critical)
    Stage 10 — Trend analysis across component groups and CVD types
    Stage 11 — Matplotlib figure generation

Usage
──────
    python run_scan.py

Output
───────
    screenshots/<site>_fullpage.png   — one PNG per scanned site
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import sys

from tqdm import tqdm

from modules.web_scanner       import load_sites, run_scanner
from modules.screenshot_capture import capture_full_page
from modules.component_detector import detect_components

# ── Logging Configuration ─────────────────────────────────────────────────────
# Single handler writing to stdout; level INFO shows scan progress without
# flooding the terminal with debug-level Playwright internals.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ── Per-Page Callback ─────────────────────────────────────────────────────────

def on_page_ready(result: dict) -> None:
    """
    Callback invoked by run_scanner for each successfully loaded page.

    Receives the result dict produced by web_scanner.scan_page, which
    contains the live Playwright page object.  Downstream tasks (screenshot
    capture, component detection) are executed here while the page is still
    open in the browser.

    Args:
        result: Dict with keys site_name, url, success, page, error.
                Modified in-place to add screenshot_path and components.
    """
    page      = result["page"]
    site_name = result["site_name"]

    # ── Stage 4: Screenshot Capture ───────────────────────────────────────────
    screenshot_path = capture_full_page(page, site_name)
    result["screenshot_path"] = screenshot_path

    # ── Stage 6 (stub): Component Detection ──────────────────────────────────
    # Returns an empty list until the component_detector module is implemented.
    components = detect_components(page, site_name)
    result["components"] = components


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 65)
    logger.info("  CVD Accessibility Audit — Website Scanner")
    logger.info("=" * 65)

    # ── Stage 1: Load websites ────────────────────────────────────────────────
    logger.info("Loading sites from data/sites.csv …")
    try:
        sites = load_sites()
    except (FileNotFoundError, ValueError) as exc:
        logger.error(f"Cannot load sites: {exc}")
        sys.exit(1)

    total = len(sites)
    logger.info(f"{total} site(s) queued for scanning.\n")

    # ── Stages 2–5: Scan → Screenshot → Detect ───────────────────────────────
    # tqdm wraps the callback so the progress bar advances once per site rather
    # than once per internal browser event, giving a clean single-line display.
    progress = tqdm(
        total=total,
        desc="Scanning",
        unit="site",
        ncols=72,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    )

    def on_page_ready_tracked(result: dict) -> None:
        """Wraps on_page_ready to advance the tqdm progress bar."""
        on_page_ready(result)
        status = "✓" if result["success"] else "✗"
        progress.set_postfix(site=result["site_name"], status=status)
        progress.update(1)

    results = run_scanner(sites, on_page_ready=on_page_ready_tracked)
    progress.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    successful = [r for r in results if r["success"]]
    failed     = [r for r in results if not r["success"]]
    captured   = [r for r in results if r.get("screenshot_path")]

    print()   # blank line after progress bar
    logger.info("-" * 65)
    logger.info(f"Scan complete:")
    logger.info(f"  Sites scanned      : {len(results)}")
    logger.info(f"  Successful loads   : {len(successful)}")
    logger.info(f"  Screenshots saved  : {len(captured)}")
    logger.info(f"  Failures           : {len(failed)}")

    if failed:
        logger.warning("Failed sites:")
        for r in failed:
            logger.warning(f"  ✗  {r['site_name']}  —  {r.get('error', 'unknown error')}")

    logger.info(f"\nOutput → screenshots/")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
