"""
modules/component_detector.py
─────────────────────────────────────────────────────────────────────────────
UI component detection from the rendered DOM.

Research Methodology — Stage 2: UI Component Detection
────────────────────────────────────────────────────────
This module will parse the DOM of each scanned page and categorise page
elements into semantic UI component groups:

    Component Group   | Example Elements
    ─────────────────────────────────────────────
    Navigation        | nav, header menus
    Buttons           | button, input[type=button]
    Links             | a
    Forms             | input, select, textarea
    Text blocks       | p, span
    Cards             | div[role=card]
    Alerts            | [role=alert]
    Footers           | footer

For each detected component the module will extract:
    • component_type      — category label (e.g. "button")
    • html_tag            — raw HTML tag name
    • text_content        — visible text of the element
    • font_size           — computed font size (px)
    • foreground_color    — computed CSS color
    • background_color    — computed CSS background-color
    • screenshot_region   — bounding box for cropped screenshot

These fields feed directly into:
    • screenshot_capture  — to crop element-level screenshots
    • contrast_analyzer   — to compute WCAG contrast ratios per component

─────────────────────────────────────────────────────────────────────────────
STATUS: STUB — Not yet implemented.
        Full implementation is planned for Stage 2 of the project.
─────────────────────────────────────────────────────────────────────────────
"""

import logging

logger = logging.getLogger(__name__)


def detect_components(page, site_name: str) -> list:
    """
    Detect and categorise UI components on the provided Playwright page.

    This is a stub function.  It currently returns an empty list and logs a
    notice so the rest of the pipeline can proceed without component data.

    Args:
        page:      Active Playwright page object.
        site_name: Name of the site being analysed (used for logging).

    Returns:
        List of component dicts — currently always empty.
        When implemented each dict will contain the fields listed in the
        module docstring above.
    """
    logger.debug(
        f"[STUB] Component detection not yet implemented for '{site_name}'. "
        "Returning empty component list."
    )
    return []
