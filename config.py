"""
config.py
─────────────────────────────────────────────────────────────────────────────
Central configuration for the CVD Accessibility Audit project.

All path definitions and browser/viewport settings are defined here so that
every module imports from a single source of truth, making the project easy
to reconfigure without touching individual module files.
─────────────────────────────────────────────────────────────────────────────
"""

import os

# ── Base Directory ────────────────────────────────────────────────────────────
# Resolves to the project root directory regardless of the caller's working
# directory, ensuring all relative paths stay consistent.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Data Paths ────────────────────────────────────────────────────────────────
DATA_DIR  = os.path.join(BASE_DIR, "data")
SITES_CSV = os.path.join(DATA_DIR, "sites.csv")   # Input: list of URLs to scan
COMPONENT_DATA_CSV = os.path.join(DATA_DIR, "component_data.csv")

# ── Output Paths ──────────────────────────────────────────────────────────────
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")   # Full-page screenshots
COMPONENT_SCREENSHOTS_DIR = os.path.join(SCREENSHOTS_DIR, "components")
FULLPAGE_SCREENSHOTS_DIR = os.path.join(SCREENSHOTS_DIR, "fullpage")

DEBUG_DIR = os.path.join(BASE_DIR, "debug")
DEBUG_OVERLAYS_DIR = os.path.join(DEBUG_DIR, "overlays")

# ── Playwright Browser Settings ───────────────────────────────────────────────
# BROWSER_HEADLESS — set to False for a visible browser window during debugging
BROWSER_HEADLESS  = True
PAGE_LOAD_TIMEOUT = 30_000   # milliseconds — max time to wait for navigation
WAIT_AFTER_LOAD   = 2_000    # milliseconds — extra settle time for JS content

# ── Viewport Dimensions ───────────────────────────────────────────────────────
# Standard desktop viewport; affects layout and which elements are visible.
VIEWPORT_WIDTH  = 1280
VIEWPORT_HEIGHT = 720
