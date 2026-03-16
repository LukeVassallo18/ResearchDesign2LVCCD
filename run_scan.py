"""
run_scan.py
─────────────────────────────────────────────────────────────────────────────
Main entry point for the CVD Accessibility Audit pipeline.

Current Stage: Website Scanning, DOM Component Extraction, and Visual Debugging
────────────────────────────────────────────────────────────────────────────────
This script executes the first two operational stages of the research
methodology pipeline:

    Stage 1 — Load websites from data/sites.csv
    Stage 2 — Open each page in a headless Playwright browser
    Stage 3 — Wait for the page to fully load (network + JS settle time)
    Stage 4 — Save a full-page screenshot per site
    Stage 5 — Parse rendered DOM for UI component groups
    Stage 6 — Export component metadata to CSV
    Stage 7 — Draw component overlays for visual validation

Stages not yet implemented (planned for later iterations):
    Stage 8 — CVD simulation (protanopia / deuteranopia / tritanopia)
    Stage 9 — WCAG contrast analysis per component
    Stage 10 — Risk classification (Pass / Warning / Critical)
    Stage 11 — Trend analysis across component groups and CVD types
    Stage 12 — Matplotlib figure generation

Usage
──────
    python run_scan.py

Output
───────
    screenshots/fullpage/<site>.png       — full-page screenshots
    data/component_data.csv                — extracted UI component records
    debug/overlays/<site>_components.png  — debug overlays
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import sys
from collections import Counter

from tqdm import tqdm

from modules.web_scanner       import load_sites, run_scanner
from modules.component_detector import detect_components, initialise_component_output
from modules.debug_visualizer import create_component_overlay
from modules.screenshot_capture import capture_full_page

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
    contains the live Playwright page object. Screenshot capture, DOM
    component detection, and debug overlay generation are executed here while
    the page is still open in the browser.

    Args:
        result: Dict with keys site_name, url, success, page, error.
            Modified in-place to add screenshot_path, components, and
            overlay_path.
    """
    page      = result["page"]
    site_name = result["site_name"]

    # ── Stage 4: Full-page Screenshot Capture ────────────────────────────────
    screenshot_path = capture_full_page(page, site_name)
    result["screenshot_path"] = screenshot_path

    # ── Stage 5: DOM Component Detection ─────────────────────────────────────
    components = detect_components(page, site_name)
    result["components"] = components

    # ── Stage 7: Debug Overlay Generation ────────────────────────────────────
    overlay_path = create_component_overlay(site_name)
    result["overlay_path"] = overlay_path

    distribution = Counter(component["component_type"] for component in components)
    logger.info(f"  {site_name} component distribution")
    for component_type in sorted(distribution.keys()):
        logger.info(f"    {component_type:<12}: {distribution[component_type]}")


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

    initialise_component_output()
    logger.info("Component output initialised at data/component_data.csv")

    # ── Stages 2–7: Scan → Screenshot → Detect → Overlay ────────────────────
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
    overlays   = [r for r in results if r.get("overlay_path")]
    components = sum(len(r.get("components", [])) for r in results)

    print()   # blank line after progress bar
    logger.info("-" * 65)
    logger.info(f"Scan complete:")
    logger.info(f"  Sites scanned      : {len(results)}")
    logger.info(f"  Successful loads   : {len(successful)}")
    logger.info(f"  Screenshots saved  : {len(captured)}")
    logger.info(f"  Overlays saved     : {len(overlays)}")
    logger.info(f"  Components found   : {components}")
    logger.info(f"  Failures           : {len(failed)}")

    if failed:
        logger.warning("Failed sites:")
        for r in failed:
            logger.warning(f"  ✗  {r['site_name']}  —  {r.get('error', 'unknown error')}")

    logger.info(f"\nOutput → screenshots/fullpage/, debug/overlays/, data/component_data.csv")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
