"""
modules/debug_visualizer.py
─────────────────────────────────────────────────────────────────────────────
Draws visual debug overlays for detected components.

Workflow:
  1) Load full-page screenshot for a site
  2) Read component rows from data/component_data.csv for that site
  3) Draw bounding boxes + component labels
  4) Save debug overlay to debug/overlays/{site}_components.png
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import csv
import importlib
import json
import logging
import os
import re

from config import COMPONENT_DATA_CSV, DEBUG_OVERLAYS_DIR
from modules.screenshot_capture import get_fullpage_screenshot_path

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    """Convert an arbitrary string into a filesystem-safe lowercase filename stem."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "site"


def ensure_debug_dirs() -> None:
    """Create debug overlay directory if missing."""
    os.makedirs(DEBUG_OVERLAYS_DIR, exist_ok=True)


def _load_site_components(site_name: str) -> list[dict]:
    """Load component rows for one site from the component CSV."""
    if not os.path.exists(COMPONENT_DATA_CSV):
        return []

    rows: list[dict] = []
    with open(COMPONENT_DATA_CSV, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("site") == site_name:
                rows.append(row)
    return rows


def _parse_box(raw_value: str) -> tuple[int, int, int, int] | None:
    """Parse a JSON bounding box string into integer xywh values."""
    try:
        box = json.loads(raw_value)
        x = int(round(float(box.get("x", 0))))
        y = int(round(float(box.get("y", 0))))
        w = int(round(float(box.get("width", 0))))
        h = int(round(float(box.get("height", 0))))
        if w <= 0 or h <= 0:
            return None
        return x, y, w, h
    except Exception:
        return None


def _draw_label(cv2, image, text: str, x: int, y: int) -> None:
    """Draw a readable label box and text near a component rectangle."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1

    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    label_x = max(x, 0)
    label_y = max(y - 8, text_height + 4)

    cv2.rectangle(
        image,
        (label_x, label_y - text_height - baseline - 4),
        (label_x + text_width + 6, label_y + 2),
        (0, 0, 0),
        -1,
    )
    cv2.putText(image, text, (label_x + 3, label_y - 2), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def create_component_overlay(site_name: str) -> str | None:
    """
    Generate a visual component overlay for a site.

    Returns:
        Path to the overlay image, or None when skipped/failed.
    """
    ensure_debug_dirs()

    try:
        cv2 = importlib.import_module("cv2")
    except ModuleNotFoundError:
        logger.warning("  ⚠ Debug overlay skipped: OpenCV is not installed")
        return None

    screenshot_path = get_fullpage_screenshot_path(site_name)
    if not os.path.exists(screenshot_path):
        logger.warning(f"  ⚠ Debug overlay skipped for {site_name}: screenshot missing ({screenshot_path})")
        return None

    rows = _load_site_components(site_name)
    if not rows:
        logger.warning(f"  ⚠ Debug overlay skipped for {site_name}: no component rows found")
        return None

    image = cv2.imread(screenshot_path)
    if image is None:
        logger.warning(f"  ⚠ Debug overlay skipped for {site_name}: failed to read screenshot")
        return None

    height, width = image.shape[:2]

    for row in rows:
        box = _parse_box(row.get("bounding_box", ""))
        if box is None:
            continue

        x, y, w, h = box
        x1 = max(0, min(x, width - 1))
        y1 = max(0, min(y, height - 1))
        x2 = max(0, min(x + w, width - 1))
        y2 = max(0, min(y + h, height - 1))

        if x2 <= x1 or y2 <= y1:
            continue

        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        _draw_label(cv2, image, row.get("component_type", "component"), x1, y1)

    output_name = f"{_safe_filename(site_name)}_components.png"
    output_path = os.path.join(DEBUG_OVERLAYS_DIR, output_name)
    cv2.imwrite(output_path, image)
    logger.info(f"  🖼️  Debug overlay saved: {output_path}")
    return output_path
