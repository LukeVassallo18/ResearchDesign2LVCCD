"""
modules/component_detector.py
─────────────────────────────────────────────────────────────────────────────
UI component detection from the rendered DOM.

Research Methodology — Stage 2: UI Component Detection
────────────────────────────────────────────────────────
This module parses the rendered HTML using BeautifulSoup, classifies DOM
elements into UI component groups, extracts computed visual properties from
the live Playwright page, and writes the results to data/component_data.csv.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag

from config import COMPONENT_DATA_CSV

logger = logging.getLogger(__name__)


COMPONENT_CSV_HEADERS = [
    "site",
    "component_type",
    "html_tag",
    "text_content",
    "font_size",
    "foreground_color",
    "background_color",
    "bounding_box",
]

CARD_PATTERN = re.compile(
    r"card|tile|panel|teaser|feature|product|content-block|content_card",
    re.IGNORECASE,
)
WHITESPACE_PATTERN = re.compile(r"\s+")


def initialise_component_output() -> None:
    """Reset component outputs for a fresh scan run."""
    os.makedirs(os.path.dirname(COMPONENT_DATA_CSV), exist_ok=True)

    with open(COMPONENT_DATA_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPONENT_CSV_HEADERS)
        writer.writeheader()


def _normalise_text(text: str) -> str:
    """Collapse repeated whitespace into a single space."""
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _has_component_ancestor(tag: Tag, names: set[str]) -> bool:
    """Return True when the node is nested inside one of the given ancestor tags."""
    for parent in tag.parents:
        if isinstance(parent, Tag) and parent.name in names:
            return True
    return False


def _has_role_ancestor(tag: Tag, roles: set[str]) -> bool:
    """Return True when the node is nested inside an ancestor with one of the given ARIA roles."""
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        role_attr = parent.get("role")
        if isinstance(role_attr, list):
            role_attr = " ".join(role_attr)
        role = (role_attr or "").strip().lower()
        if role in roles:
            return True
    return False


def _iter_common_component_tags(soup: BeautifulSoup) -> Iterable[tuple[str, Tag]]:
    """Yield candidate nodes using a strict common-tag strategy."""
    for tag in soup.find_all(["nav", "footer", "form", "button", "p", "a", "input", "select", "textarea", "article", "section", "div"]):
        if not isinstance(tag, Tag):
            continue
        component_type = _classify_component(tag)
        if component_type is not None:
            yield component_type, tag


def _is_button_like_anchor(tag: Tag) -> bool:
    """Return True when an anchor behaves like a button in common UI patterns."""
    if tag.name.lower() != "a":
        return False

    role_attr = tag.get("role")
    if isinstance(role_attr, list):
        role_attr = " ".join(role_attr)
    role = (role_attr or "").strip().lower()
    if role == "button":
        return True

    class_attr = tag.get("class")
    classes = " ".join(class_attr if isinstance(class_attr, list) else [])
    identifier = f"{classes} {tag.get('id', '')}".lower()

    # Common naming conventions in popular UI frameworks/design systems
    return bool(re.search(r"\b(btn|button|cta|call-to-action|action-button|primary|secondary)\b", identifier))


def _has_card_structure(tag: Tag) -> bool:
    """Return True when an element looks like a content card container."""
    has_heading = tag.find(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None
    has_text_block = tag.find(["p"]) is not None
    has_media = tag.find(["img", "picture", "video", "svg"]) is not None
    has_container = tag.find(["article", "section", "div"]) is not None

    return (has_heading and (has_text_block or has_media)) or (has_media and has_text_block) or (has_container and has_heading)


def _refine_component_type(tag: Tag, component_type: str, visuals: dict, text_content: str) -> str:
    """Refine initial DOM classification with computed style and layout heuristics."""
    if component_type != "link":
        return component_type

    if tag.name.lower() != "a":
        return component_type

    box = visuals.get("bounding_box") or {}
    width = float(box.get("width", 0) or 0)
    height = float(box.get("height", 0) or 0)
    area = width * height

    display = str(visuals.get("display", "")).lower()
    background = str(visuals.get("background_color", "")).lower()
    border_width = float(visuals.get("border_width", 0) or 0)
    border_style = str(visuals.get("border_style", "")).lower()
    padding_x = float(visuals.get("padding_left", 0) or 0) + float(visuals.get("padding_right", 0) or 0)
    padding_y = float(visuals.get("padding_top", 0) or 0) + float(visuals.get("padding_bottom", 0) or 0)

    has_visible_background = background not in {"transparent", "rgba(0, 0, 0, 0)", ""}
    has_visible_border = border_width >= 1 and border_style not in {"none", ""}
    has_button_layout = display in {"inline-block", "inline-flex", "flex", "block", "inline-grid", "grid"}

    if _is_button_like_anchor(tag):
        return "button"

    if has_button_layout and (has_visible_background or has_visible_border) and (padding_x >= 12 or padding_y >= 8):
        if 20 <= height <= 90 and 40 <= width <= 420:
            return "button"

    if _has_card_structure(tag):
        if area >= 30_000 or (width >= 320 and height >= 100):
            return "card"
        if len(text_content) >= 60 and area >= 18_000:
            return "card"

    return component_type


def _classify_component(tag: Tag) -> str | None:
    """Map a BeautifulSoup tag to a supported UI component type using strict HTML-first rules."""
    tag_name = tag.name.lower()
    role_attr = tag.get("role")
    if isinstance(role_attr, list):
        role_attr = " ".join(role_attr)
    role = (role_attr or "").strip().lower()
    tag_type_attr = tag.get("type")
    if isinstance(tag_type_attr, list):
        tag_type_attr = " ".join(tag_type_attr)
    tag_type = (tag_type_attr or "").strip().lower()
    classes = " ".join(tag.get("class") or [])
    identifier = f"{classes} {tag.get('id', '')}".strip()

    if tag_name == "nav" or role == "navigation":
        return "navigation"

    if tag_name == "button" or (tag_name == "input" and tag_type in {"button", "submit", "reset"}):
        return "button"

    if tag_name == "a" and _is_button_like_anchor(tag):
        return "button"

    if tag_name == "a" and tag.get("href"):
        return "link"

    if tag_name == "form":
        return "form"

    if tag_name in {"input", "select", "textarea"}:
        return "form"

    if tag_name == "p":
        return "text"

    if tag_name == "footer":
        return "footer"

    if role in {"alert", "alertdialog"}:
        return "alert"

    if tag_name == "article":
        return "card"

    if tag_name in {"section", "div"} and (role == "article" or CARD_PATTERN.search(identifier)):
        return "card"

    return None


def _should_skip_component(tag: Tag, component_type: str) -> bool:
    """Filter out low-value or duplicate-prone elements before extraction."""
    text_content = _normalise_text(tag.get_text(" ", strip=True))
    aria_label_attr = tag.get("aria-label", "")
    aria_label = _normalise_text(aria_label_attr if isinstance(aria_label_attr, str) else "")
    title_attr = tag.get("title", "")
    title = _normalise_text(title_attr if isinstance(title_attr, str) else "")
    type_attr = tag.get("type", "")
    input_type = (type_attr if isinstance(type_attr, str) else "").strip().lower()
    href_attr = tag.get("href", "")
    href = (href_attr if isinstance(href_attr, str) else "").strip()
    href_lower = href.lower()
    class_attr = tag.get("class")
    classes = " ".join(class_attr if isinstance(class_attr, list) else [])
    identifier = f"{classes} {tag.get('id', '')}".strip()
    identifier_lower = identifier.lower()
    rel = (tag.get("rel") or [])
    tag_name = tag.name.lower()

    parent_names = {
        parent.name
        for parent in tag.parents
        if isinstance(parent, Tag) and parent.name != "[document]"
    }

    if component_type == "navigation":
        if _has_component_ancestor(tag, {"nav"}):
            return True

    if component_type == "footer":
        if _has_component_ancestor(tag, {"footer"}):
            return True

    if component_type == "form":
        if tag_name in {"input", "select", "textarea"} and _has_component_ancestor(tag, {"form"}):
            return True
        if tag_name == "input" and input_type in {"hidden", "image"}:
            return True

    if component_type == "link" and not any([text_content, aria_label, title]):
        return True

    if component_type == "link" and href_lower in {"", "#"}:
        return True

    if component_type == "link" and href_lower.startswith("javascript:"):
        return True

    if component_type == "link" and len(text_content) < 3 and not any([aria_label, title]):
        return True

    if component_type == "link" and rel and "nofollow" in [r.lower() for r in rel] and len(text_content) < 6:
        return True

    if component_type == "link":
        link_in_semantic_area = bool(parent_names.intersection({"nav", "header", "footer", "aside"}))
        has_cta_signal = bool(re.search(r"btn|button|cta|menu|nav|tab|link", identifier_lower))
        has_link_accessibility_label = bool(aria_label or title)
        if not any([link_in_semantic_area, has_cta_signal, has_link_accessibility_label]):
            return True

    if component_type == "button" and _has_component_ancestor(tag, {"button"}):
        return True

    if component_type == "button" and not any([text_content, aria_label, title, tag.get("value")]):
        return True

    if component_type == "text":
        if not text_content:
            return True
        if len(text_content) < 80 or len(text_content.split()) < 12:
            return True
        if any(name in {"a", "button", "label", "nav", "footer", "li", "header", "aside"} for name in parent_names):
            return True
        if isinstance(tag.parent, Tag) and tag.parent.name in {"p", "span", "a", "button"}:
            return True

    if component_type == "alert":
        if _has_role_ancestor(tag, {"alert", "alertdialog"}):
            return True
        if not text_content or len(text_content) < 12:
            return True

    if component_type == "card":
        if _has_component_ancestor(tag, {"article", "section"}):
            return True
        if tag.name == "div" and not CARD_PATTERN.search(identifier):
            return True
        card_text = len(text_content)
        has_media = tag.find(["img", "picture", "svg"]) is not None
        has_heading = tag.find(["h1", "h2", "h3", "h4", "h5", "h6"]) is not None
        has_action = tag.find(["a", "button"]) is not None
        if card_text < 40 and not has_heading:
            return True
        if not any([has_media, has_heading, has_action]):
            return True
        if any(name in {"nav", "footer", "header"} for name in parent_names):
            return True

    return False


def _build_css_path(tag: Tag) -> str:
    """Build a CSS path that can be resolved back to the live DOM element."""
    segments: list[str] = []
    current: Tag | None = tag

    while current is not None and isinstance(current, Tag):
        if current.name == "[document]":
            break

        parent = current.parent
        if not isinstance(parent, Tag):
            segments.append(current.name)
            break

        same_tag_siblings = [
            sibling
            for sibling in parent.find_all(current.name, recursive=False)
            if isinstance(sibling, Tag)
        ]
        index = same_tag_siblings.index(current) + 1
        segments.append(f"{current.name}:nth-of-type({index})")
        current = parent

    return " > ".join(reversed(segments))


def _extract_component_visuals(page, selector: str) -> dict | None:
    """Read computed styles and bounding box data from the live DOM element."""
    script = """
    (cssSelector) => {
        const element = document.querySelector(cssSelector);
        if (!element) {
            return null;
        }

        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();

        const resolveBackground = (node) => {
            let current = node;
            while (current) {
                const bg = window.getComputedStyle(current).backgroundColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                    return bg;
                }
                current = current.parentElement;
            }
            return 'rgb(255, 255, 255)';
        };

        return {
            html_tag: element.tagName.toLowerCase(),
            text_content: (element.innerText || element.textContent || '').trim(),
            font_size: style.fontSize || '',
            foreground_color: style.color || '',
            background_color: resolveBackground(element),
            border_width: parseFloat(style.borderTopWidth || '0') || 0,
            border_style: style.borderTopStyle || '',
            padding_left: parseFloat(style.paddingLeft || '0') || 0,
            padding_right: parseFloat(style.paddingRight || '0') || 0,
            padding_top: parseFloat(style.paddingTop || '0') || 0,
            padding_bottom: parseFloat(style.paddingBottom || '0') || 0,
            display: style.display || '',
            visibility: style.visibility || '',
            opacity: style.opacity || '',
            bounding_box: {
                x: rect.left + window.scrollX,
                y: rect.top + window.scrollY,
                width: rect.width,
                height: rect.height,
            },
        };
    }
    """

    visuals = page.evaluate(script, selector)
    if not visuals:
        return None

    box = visuals.get("bounding_box") or {}
    if box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
        return None
    if box.get("x", 0) < -100 or box.get("y", 0) < -100:
        return None
    if visuals.get("display") == "none":
        return None
    if visuals.get("visibility") == "hidden":
        return None
    if str(visuals.get("opacity", "1")) == "0":
        return None

    return visuals


def _append_components_to_csv(components: list[dict]) -> None:
    """Append component records to the CSV output file."""
    if not components:
        return

    with open(COMPONENT_DATA_CSV, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPONENT_CSV_HEADERS)
        for component in components:
            writer.writerow(
                {
                    "site": component["site"],
                    "component_type": component["component_type"],
                    "html_tag": component["html_tag"],
                    "text_content": component["text_content"],
                    "font_size": component["font_size"],
                    "foreground_color": component["foreground_color"],
                    "background_color": component["background_color"],
                    "bounding_box": json.dumps(component["bounding_box"], ensure_ascii=False),
                }
            )


def detect_components(page, site_name: str) -> list[dict]:
    """
    Detect supported UI components on the provided Playwright page.

    The rendered page HTML is parsed with BeautifulSoup.  Matching DOM nodes
    are classified into the required component groups (using strict common
    HTML tags), enriched with computed visual properties from the live page,
    and appended to data/component_data.csv.

    Args:
        page:      Active Playwright page object.
        site_name: Name of the site being analysed.

    Returns:
        List of extracted component dictionaries for the current site.
    """
    soup = BeautifulSoup(page.content(), "html.parser")
    components: list[dict] = []
    seen_selectors: set[str] = set()

    for component_type, tag in _iter_common_component_tags(soup):
        if _should_skip_component(tag, component_type):
            continue

        selector = _build_css_path(tag)
        if selector in seen_selectors:
            continue
        seen_selectors.add(selector)

        visuals = _extract_component_visuals(page, selector)
        if visuals is None:
            continue

        text_sources = [
            visuals.get("text_content"),
            tag.get_text(" ", strip=True),
            tag.get("aria-label"),
            tag.get("title"),
            tag.get("value"),
            tag.get("placeholder"),
        ]
        text_content = _normalise_text(
            next(
                (
                    " ".join(src) if isinstance(src, list) else (src or "")
                    for src in text_sources
                    if src
                ),
                "",
            )
        )
        if component_type == "text" and not text_content:
            continue

        component_type = _refine_component_type(tag, component_type, visuals, text_content)
        if _should_skip_component(tag, component_type):
            continue

        components.append(
            {
                "site": site_name,
                "component_type": component_type,
                "html_tag": visuals.get("html_tag") or tag.name.lower(),
                "text_content": text_content,
                "font_size": visuals.get("font_size", ""),
                "foreground_color": visuals.get("foreground_color", ""),
                "background_color": visuals.get("background_color", ""),
                "bounding_box": visuals.get("bounding_box", {}),
            }
        )

    _append_components_to_csv(components)
    logger.info(f"  🧩 Components detected for {site_name}: {len(components)}")
    return components
