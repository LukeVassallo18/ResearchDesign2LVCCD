import asyncio
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from daltonlens.simulate import Deficiency, Simulator_Brettel1997
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

# 20 - 30 sites is a good range for a comprehensive analysis while keeping the runtime manageable.
# The selected sites cover a variety of industries, design styles, and accessibility practices to provide a well-rounded dataset for analysis.
TARGET_SITES = [
    "https://developer.mozilla.org",
    "https://www.apple.com/",
    "https://www.amazon.de/",
    "https://www.netlify.com/",
    "https://www.nasa.gov/",
    "https://stripe.com/en-mt",
    "https://mita.gov.mt/",
    "https://openai.com/",
    "https://www.wikipedia.org/",
    "https://eu.louisvuitton.com/eng-e1/homepage",
    "https://www.cnn.com/",
    "https://www.w3schools.com/",
    "https://firebase.google.com/",
    "https://www.education.com/",
    "https://claude.ai/login",
    "https://timesofmalta.com/",
    "https://www.espn.com/",
    "https://www.foxnews.com/",
    "https://www.ryanair.com/mt/en",
    "https://www.emirates.com/mt/english/",
    "https://www.printables.com/",
    "https://www.behance.net/",
    "https://imgur.com/",
    "https://www.reddit.com/"
]

HEADLESS = os.getenv("ACCESSIBILITY_SCANNER_HEADLESS", "false").lower() == "true"
NETWORK_TIMEOUT_MS = 30_000
NETWORK_IDLE_TIMEOUT_MS = 10_000
POST_LOAD_DELAY_MS = 1_000
PER_SITE_TIMEOUT_SECONDS = 90
OUTPUT_DIR = Path("output")
DETAILED_RESULTS_FILE = OUTPUT_DIR / "detailed_results.json"
DETAILED_RESULTS_CSV_FILE = OUTPUT_DIR / "detailed_results.csv"
LEGACY_SUMMARY_OUTPUT_FILES = (
    OUTPUT_DIR / "analysis_summary.json",
    OUTPUT_DIR / "site_summary.csv",
    OUTPUT_DIR / "component_failure_summary.csv",
    OUTPUT_DIR / "component_vulnerability_summary.csv",
)

BUTTON_CLASS_KEYWORDS = ("btn", "button", "cta", "primary", "action")
NAV_CLASS_KEYWORDS = ("nav", "menu", "navbar")
CARD_CLASS_KEYWORDS = ("card", "tile", "box")
ALERT_CLASS_KEYWORDS = ("alert", "error", "warning")
COOKIE_KEYWORDS = (
    "cookie",
    "cookies",
    "consent",
    "gdpr",
    "privacy",
    "onetrust",
    "cookiebot",
    "cookielaw",
    "cmp",
    "didomi",
    "trustarc",
)
TRACKED_ATTRIBUTES = {"class", "id", "role", "href", "onclick", "type", "name"}
IGNORED_TAGS = {
    "head",
    "html",
    "body",
    "script",
    "style",
    "noscript",
    "meta",
    "link",
    "svg",
    "path",
    "title",
    "defs",
    "clippath",
    "mask",
    "use",
    "source",
    "picture",
    "text",
    "textpath",
    "tspan",
    "br",
    "hr",
    "mdn-dropdown",
}
BUTTON_LIKE_TAGS = {"a", "div", "span"}
TEXT_TAGS = {"p", "span", "label", "h1", "h2", "h3", "h4", "h5", "h6"}
STRUCTURAL_TAGS = {
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "main",
    "section",
    "article",
    "aside",
}
DEFAULT_BACKGROUND = "rgb(255, 255, 255)"
DEFAULT_BACKGROUND_RGB = (255, 255, 255)
CVD_CONDITIONS = {
    "protanopia": Deficiency.PROTAN,
    "deuteranopia": Deficiency.DEUTAN,
    "tritanopia": Deficiency.TRITAN,
}
ALL_CONDITIONS = ("normal", "protanopia", "deuteranopia", "tritanopia")
CORE_VULNERABILITY_TYPES = (
    "button",
    "link",
    "navigation",
    "text",
    "card",
    "form",
    "input",
    "header",
    "footer",
)
SUPPORTED_COMPONENT_TYPES = (
    "button",
    "link",
    "navigation",
    "form",
    "input",
    "text",
    "header",
    "footer",
    "card",
    "alert",
    "other",
)
CVD_SIMULATOR = Simulator_Brettel1997()
SPSS_EXPORT_COLUMNS = (
    "site",
    "component_type",
    "tag",
    "contrast_normal",
    "contrast_protanopia",
    "contrast_deuteranopia",
    "contrast_tritanopia",
    "contrast_loss_protanopia",
    "contrast_loss_deuteranopia",
    "contrast_loss_tritanopia",
    "pass_normal",
    "pass_protanopia",
    "pass_deuteranopia",
    "pass_tritanopia",
    "wcag_threshold",
)


def is_transparent_color(color: str | None) -> bool:
    if not color:
        return True

    normalized = color.strip().lower().replace(" ", "")
    return normalized in {
        "transparent",
        "rgba(0,0,0,0)",
        "rgba(255,255,255,0)",
        "rgb(0,0,0,0)",
    }


def has_padding(padding: str | None) -> bool:
    if not padding:
        return False

    numbers = re.findall(r"-?\d+(?:\.\d+)?", padding)
    return any(float(number) > 0 for number in numbers)


def has_visible_border(border: str | None) -> bool:
    if not border:
        return False

    normalized = border.strip().lower()
    widths = re.findall(r"(-?\d+(?:\.\d+)?)px", normalized)

    if not widths:
        return normalized != "none"

    return any(float(width) > 0 for width in widths) and "none" not in normalized


def has_rounded_corners(border_radius: str | None) -> bool:
    if not border_radius:
        return False

    numbers = re.findall(r"-?\d+(?:\.\d+)?", border_radius)
    return any(float(number) > 0 for number in numbers)


def starts_with_heading_tag(tag_name: str) -> bool:
    return bool(re.fullmatch(r"h[1-6]", tag_name))


def build_token_string(*values: str | None) -> str:
    normalized_values = []

    for value in values:
        if not value or not value.strip():
            continue
        normalized_values.append(re.sub(r"[^a-z0-9]+", " ", value.strip().lower()))

    return " ".join(normalized_values)


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    tokens = [token for token in text.split() if token]

    return any(
        keyword == token or keyword in token
        for keyword in keywords
        for token in tokens
    )


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()[:100]


def word_count(value: str | None) -> int:
    normalized = normalize_text(value)
    if not normalized:
        return 0
    return len(normalized.split())


def attribute_exists(attributes: dict[str, Any], name: str) -> bool:
    return name in attributes and attributes[name] is not None


def clamp_rgb_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def parse_rgb(color_value: str | None) -> tuple[int, int, int, float]:
    if not color_value:
        return (*DEFAULT_BACKGROUND_RGB, 1.0)

    normalized = color_value.strip().lower()
    if normalized == "transparent":
        return (*DEFAULT_BACKGROUND_RGB, 0.0)

    rgb_match = re.fullmatch(r"rgba?\(([^)]+)\)", normalized)
    if rgb_match:
        parts = [part.strip() for part in rgb_match.group(1).split(",")]
        if len(parts) in {3, 4}:
            rgb_channels = []
            for part in parts[:3]:
                if part.endswith("%"):
                    rgb_channels.append(clamp_rgb_channel(float(part[:-1]) * 255 / 100))
                else:
                    rgb_channels.append(clamp_rgb_channel(float(part)))
            alpha = float(parts[3]) if len(parts) == 4 else 1.0
            return rgb_channels[0], rgb_channels[1], rgb_channels[2], max(0.0, min(1.0, alpha))

    hex_match = re.fullmatch(r"#([0-9a-f]{3,8})", normalized)
    if hex_match:
        hex_value = hex_match.group(1)
        if len(hex_value) in {3, 4}:
            hex_value = "".join(character * 2 for character in hex_value)
        if len(hex_value) == 6:
            hex_value += "ff"
        if len(hex_value) == 8:
            red = int(hex_value[0:2], 16)
            green = int(hex_value[2:4], 16)
            blue = int(hex_value[4:6], 16)
            alpha = int(hex_value[6:8], 16) / 255
            return red, green, blue, alpha

    return (*DEFAULT_BACKGROUND_RGB, 1.0)


def rgb_to_string(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    return f"rgb({red}, {green}, {blue})"


def composite_rgba_over_background(
    rgba: tuple[int, int, int, float],
    background_rgb: tuple[int, int, int],
) -> tuple[int, int, int]:
    red, green, blue, alpha = rgba
    bg_red, bg_green, bg_blue = background_rgb
    return (
        clamp_rgb_channel((red * alpha) + (bg_red * (1 - alpha))),
        clamp_rgb_channel((green * alpha) + (bg_green * (1 - alpha))),
        clamp_rgb_channel((blue * alpha) + (bg_blue * (1 - alpha))),
    )


def get_effective_background(styles: dict[str, Any]) -> str:
    background = styles.get("backgroundColor")
    if background and not is_transparent_color(background):
        return background
    return DEFAULT_BACKGROUND


def srgb_to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    red, green, blue = [channel / 255 for channel in rgb]
    linear_red = srgb_to_linear(red)
    linear_green = srgb_to_linear(green)
    linear_blue = srgb_to_linear(blue)
    return (0.2126 * linear_red) + (0.7152 * linear_green) + (0.0722 * linear_blue)


def contrast_ratio(
    foreground_rgb: tuple[int, int, int],
    background_rgb: tuple[int, int, int],
) -> float:
    foreground_luminance = relative_luminance(foreground_rgb)
    background_luminance = relative_luminance(background_rgb)
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def get_wcag_threshold(font_size: str | None) -> float:
    if not font_size:
        return 4.5

    match = re.search(r"-?\d+(?:\.\d+)?", font_size)
    if not match:
        return 4.5

    return 3.0 if float(match.group()) >= 18 else 4.5


def simulate_color(
    rgb: tuple[int, int, int],
    deficiency: Deficiency,
) -> tuple[int, int, int]:
    color_sample = np.array([[list(rgb)]], dtype=np.uint8)
    simulated = CVD_SIMULATOR.simulate_cvd(color_sample, deficiency, 1.0)
    simulated_pixel = simulated[0, 0]
    return (
        int(simulated_pixel[0]),
        int(simulated_pixel[1]),
        int(simulated_pixel[2]),
    )


def safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_rate(failed: int, total: int) -> float:
    if not total:
        return 0.0
    return failed / total


def has_interactivity(attributes: dict[str, Any], styles: dict[str, Any]) -> bool:
    return any(
        (
            attribute_exists(attributes, "onclick"),
            attribute_exists(attributes, "href"),
            styles.get("cursor") == "pointer",
        )
    )


def has_visual_surface(styles: dict[str, Any]) -> bool:
    return any(
        (
            not is_transparent_color(styles.get("rawBackgroundColor")),
            has_visible_border(styles.get("border")),
            styles.get("boxShadow") not in {None, "", "none"},
            has_rounded_corners(styles.get("borderRadius")),
        )
    )


def is_hidden_element(styles: dict[str, Any]) -> bool:
    return any(
        (
            styles.get("display") == "none",
            styles.get("visibility") == "hidden",
            styles.get("opacity") == "0",
            styles.get("opacity") == "0.0",
        )
    )


def is_structural_container(element_data: dict[str, Any]) -> bool:
    styles = element_data["styles"]
    attributes = element_data["attributes"]

    return (
        element_data["tag"] in STRUCTURAL_TAGS
        and not attributes.get("role")
        and not has_interactivity(attributes, styles)
        and not has_visual_surface(styles)
    )


def is_noisy_text_container(element_data: dict[str, Any]) -> bool:
    tag_name = element_data["tag"]
    attributes = element_data["attributes"]
    styles = element_data["styles"]
    class_tokens = build_token_string(attributes.get("class", ""), attributes.get("id", ""))
    text_words = element_data.get("text_word_count", word_count(element_data["text"]))

    return (
        tag_name in {"div", "section", "article"}
        and text_words >= 12
        and not attributes.get("role")
        and not has_interactivity(attributes, styles)
        and not has_visual_surface(styles)
        and not contains_keyword(
            class_tokens,
            BUTTON_CLASS_KEYWORDS + NAV_CLASS_KEYWORDS + CARD_CLASS_KEYWORDS + ALERT_CLASS_KEYWORDS,
        )
    )


def has_visual_role(element_data: dict[str, Any]) -> bool:
    tag_name = element_data["tag"]
    attributes = element_data["attributes"]
    styles = element_data["styles"]

    joined_tokens = build_token_string(
        attributes.get("class", ""),
        attributes.get("id", ""),
        attributes.get("role", ""),
        attributes.get("aria-label", ""),
        attributes.get("aria-labelledby", ""),
        attributes.get("aria-describedby", ""),
    )

    return any(
        (
            tag_name
            in {
                "button",
                "a",
                "nav",
                "form",
                "input",
                "textarea",
                "select",
                "header",
                "footer",
                "label",
                "form",
            },
            bool(attributes.get("role")),
            bool(attributes.get("aria-label")),
            has_interactivity(attributes, styles),
            contains_keyword(
                joined_tokens,
                BUTTON_CLASS_KEYWORDS
                + NAV_CLASS_KEYWORDS
                + CARD_CLASS_KEYWORDS
                + ALERT_CLASS_KEYWORDS,
            ),
            has_visual_surface(styles),
        )
    )


def is_cookie_consent_element(element_data: dict[str, Any]) -> bool:
    attributes = element_data["attributes"]
    styles = element_data["styles"]
    text = element_data.get("text", "")

    signal_text = build_token_string(
        text,
        attributes.get("class", ""),
        attributes.get("id", ""),
        attributes.get("role", ""),
        attributes.get("aria-label", ""),
        attributes.get("aria-labelledby", ""),
        attributes.get("aria-describedby", ""),
    )
    has_cookie_signal = contains_keyword(signal_text, COOKIE_KEYWORDS)

    if not has_cookie_signal:
        return False

    role = (attributes.get("role") or "").strip().lower()
    position = (styles.get("position") or "").strip().lower()

    return any(
        (
            role in {"dialog", "alertdialog", "banner"},
            position in {"fixed", "sticky"},
            element_data["tag"] in {"form", "aside", "section", "div", "dialog"},
        )
    )


def should_skip_element(element_data: dict[str, Any]) -> bool:
    if element_data["tag"] in IGNORED_TAGS:
        return True

    styles = element_data["styles"]
    text = normalize_text(element_data.get("text", ""))
    element_data["text"] = text

    if is_hidden_element(styles):
        return True

    if is_cookie_consent_element(element_data):
        return True

    if is_structural_container(element_data):
        return True

    if is_noisy_text_container(element_data):
        return True

    if (
        not text
        and not element_data["attributes"].get("role")
        and not has_interactivity(element_data["attributes"], styles)
    ):
        return True

    if not text and not has_visual_role(element_data):
        return True

    return False


def classify_component(element_data: dict[str, Any]) -> str:
    tag_name = element_data["tag"]
    attributes = element_data["attributes"]
    styles = element_data["styles"]
    text = element_data["text"]

    role = (attributes.get("role") or "").strip().lower()
    class_tokens = build_token_string(attributes.get("class", ""), attributes.get("id", ""))
    href_exists = attribute_exists(attributes, "href")
    onclick_exists = attribute_exists(attributes, "onclick")
    background = styles.get("backgroundColor")
    pointer_cursor = styles.get("cursor") == "pointer"
    is_button_keyword = contains_keyword(class_tokens, BUTTON_CLASS_KEYWORDS)
    is_navigation_keyword = contains_keyword(class_tokens, NAV_CLASS_KEYWORDS)
    is_card_keyword = contains_keyword(class_tokens, CARD_CLASS_KEYWORDS)
    has_button_surface = (
        not is_transparent_color(background) and has_padding(styles.get("padding"))
    )
    has_pointer_button_surface = pointer_cursor and (
        not is_transparent_color(background)
        or has_visible_border(styles.get("border"))
    )
    has_visual_card_cue = any(
        (
            is_card_keyword,
            styles.get("boxShadow") not in {None, "", "none"},
            has_rounded_corners(styles.get("borderRadius")),
        )
    )
    text_words = element_data.get("text_word_count", word_count(text))

    if text_words > 40:
        return "other"

    if tag_name == "nav" or role == "navigation":
        if text_words > 30:
            return "other"
        return "navigation"

    if (
        tag_name == "button"
        or role == "button"
        or onclick_exists
        or has_button_surface
        or (tag_name in BUTTON_LIKE_TAGS and is_button_keyword)
        or (
            tag_name in {"div", "span"}
            and has_pointer_button_surface
        )
        or (
            tag_name == "a"
            and has_pointer_button_surface
            and (
                not href_exists
                or role == "button"
                or is_button_keyword
                or has_button_surface
            )
        )
    ):
        return "button"

    if tag_name == "a" and href_exists:
        if not text:
            element_data["text"] = "[no visible text]"
        return "link"

    if (
        text_words < 30
        and is_navigation_keyword
    ):
        return "navigation"

    if tag_name == "form":
        return "form"

    if tag_name in {"input", "textarea", "select"}:
        return "input"

    if role == "alert" or contains_keyword(class_tokens, ALERT_CLASS_KEYWORDS):
        return "alert"

    if tag_name in TEXT_TAGS or starts_with_heading_tag(tag_name):
        return "text"

    if tag_name == "header":
        return "header"

    if tag_name == "footer":
        return "footer"

    if (
        tag_name == "div"
        and has_visual_card_cue
        and not is_transparent_color(background)
    ):
        return "card"

    return "other"


def build_failure_metrics(
    records: list[dict[str, Any]],
    condition: str,
) -> dict[str, float | int]:
    total_components = len(records)
    failed_components = sum(
        1 for record in records if not record[f"pass_{condition}"]
    )
    return {
        "total_components": total_components,
        "failed_components": failed_components,
        "failure_rate": round(compute_rate(failed_components, total_components), 4),
    }


def compute_component_metrics(
    site: str,
    component_index: int,
    component_type: str,
    element_data: dict[str, Any],
) -> dict[str, Any]:
    styles = element_data["styles"]
    attributes = element_data["attributes"]
    font_size = styles.get("fontSize")
    foreground_raw = styles.get("color", DEFAULT_BACKGROUND)
    background_raw = get_effective_background(styles)
    border_color_raw = styles.get("borderColor", "")
    outline_color_raw = styles.get("outlineColor", "")

    effective_background_rgb = composite_rgba_over_background(
        parse_rgb(background_raw),
        DEFAULT_BACKGROUND_RGB,
    )
    effective_foreground_rgb = composite_rgba_over_background(
        parse_rgb(foreground_raw),
        effective_background_rgb,
    )

    threshold = get_wcag_threshold(font_size)
    record: dict[str, Any] = {
        "site": site,
        "component_index": component_index,
        "component_type": component_type,
        "tag": element_data["tag"],
        "text": element_data["text"],
        "text_word_count": element_data.get("text_word_count", word_count(element_data["text"])),
        "font_size": font_size,
        "wcag_threshold": threshold,
        "foreground_raw": foreground_raw,
        "background_raw": background_raw,
        "border_color_raw": border_color_raw,
        "outline_color_raw": outline_color_raw,
        "foreground_normal": rgb_to_string(effective_foreground_rgb),
        "background_normal": rgb_to_string(effective_background_rgb),
        "role": attributes.get("role", ""),
        "href": attributes.get("href", ""),
        "class_name": attributes.get("class", ""),
        "element_id": attributes.get("id", ""),
        "onclick": attributes.get("onclick", ""),
    }

    normal_contrast = contrast_ratio(effective_foreground_rgb, effective_background_rgb)
    record["contrast_normal"] = round(normal_contrast, 4)
    record["pass_normal"] = int(normal_contrast >= threshold)

    for condition_name, deficiency in CVD_CONDITIONS.items():
        simulated_foreground_rgb = simulate_color(effective_foreground_rgb, deficiency)
        simulated_background_rgb = simulate_color(effective_background_rgb, deficiency)
        simulated_contrast = contrast_ratio(
            simulated_foreground_rgb,
            simulated_background_rgb,
        )

        record[f"foreground_{condition_name}"] = rgb_to_string(simulated_foreground_rgb)
        record[f"background_{condition_name}"] = rgb_to_string(simulated_background_rgb)
        record[f"contrast_{condition_name}"] = round(simulated_contrast, 4)
        record[f"pass_{condition_name}"] = int(simulated_contrast >= threshold)
        record[f"contrast_loss_{condition_name}"] = round(
            normal_contrast - simulated_contrast,
            4,
        )

    return record


def build_analysis_summary(site_results: list[dict[str, Any]]) -> dict[str, Any]:
    all_records = [
        component
        for site_result in site_results
        for component in site_result["components"]
    ]
    observed_component_counts = Counter(record["component_type"] for record in all_records)
    component_counts = {
        component_type: observed_component_counts.get(component_type, 0)
        for component_type in SUPPORTED_COMPONENT_TYPES
    }

    overall_failure_rate = {
        condition: build_failure_metrics(all_records, condition)
        for condition in ALL_CONDITIONS
    }
    failure_rate_by_cvd_type = {
        condition: overall_failure_rate[condition]
        for condition in CVD_CONDITIONS
    }

    site_summary_table = []
    for site_result in site_results:
        records = site_result["components"]
        overall_failure = sum(1 for record in records if not record["pass_normal"])
        protanopia_failure = sum(
            1 for record in records if not record["pass_protanopia"]
        )
        deuteranopia_failure = sum(
            1 for record in records if not record["pass_deuteranopia"]
        )
        tritanopia_failure = sum(
            1 for record in records if not record["pass_tritanopia"]
        )
        site_summary_table.append(
            {
                "site": site_result["site"],
                "total_elements_scanned": site_result["total_elements_scanned"],
                "total_components": len(records),
                "other_percentage": round(site_result["other_percentage"], 4),
                "counts_by_component_type": {
                    component_type: site_result["category_counts"].get(component_type, 0)
                    for component_type in SUPPORTED_COMPONENT_TYPES
                },
                "failed_normal": overall_failure,
                "failure_rate_normal": round(
                    compute_rate(overall_failure, len(records)),
                    4,
                ),
                "failed_protanopia": protanopia_failure,
                "failure_rate_protanopia": round(
                    compute_rate(protanopia_failure, len(records)),
                    4,
                ),
                "failed_deuteranopia": deuteranopia_failure,
                "failure_rate_deuteranopia": round(
                    compute_rate(deuteranopia_failure, len(records)),
                    4,
                ),
                "failed_tritanopia": tritanopia_failure,
                "failure_rate_tritanopia": round(
                    compute_rate(tritanopia_failure, len(records)),
                    4,
                ),
            }
        )

    component_types = list(SUPPORTED_COMPONENT_TYPES)
    failure_rate_by_component_type = []
    mean_contrast_by_component_type = []
    mean_contrast_loss_by_component_type = []
    component_vulnerability_scores_by_type: dict[str, Any] = {}

    for component_type in component_types:
        component_records = [
            record for record in all_records if record["component_type"] == component_type
        ]
        row = {
            "component_type": component_type,
            "total_components": len(component_records),
        }
        mean_row = {
            "component_type": component_type,
            "total_components": len(component_records),
        }
        contrast_loss_row = {
            "component_type": component_type,
            "total_components": len(component_records),
        }
        vulnerability_row = {
            "component_type": component_type,
            "total_components": len(component_records),
        }

        for condition in ALL_CONDITIONS:
            failure_metrics = build_failure_metrics(component_records, condition)
            row[f"failed_{condition}"] = failure_metrics["failed_components"]
            row[f"failure_rate_{condition}"] = failure_metrics["failure_rate"]
            mean_row[f"mean_contrast_{condition}"] = round(
                safe_mean([record[f"contrast_{condition}"] for record in component_records]),
                4,
            )

        for condition in CVD_CONDITIONS:
            contrast_loss_row[f"mean_contrast_loss_{condition}"] = round(
                safe_mean(
                    [
                        record[f"contrast_loss_{condition}"]
                        for record in component_records
                    ]
                ),
                4,
            )
            vulnerability_row[f"cvs_{condition}"] = row[f"failure_rate_{condition}"]

        failure_rate_by_component_type.append(row)
        mean_contrast_by_component_type.append(mean_row)
        mean_contrast_loss_by_component_type.append(contrast_loss_row)
        component_vulnerability_scores_by_type[component_type] = vulnerability_row

    mean_contrast_overall = {
        condition: round(
            safe_mean([record[f"contrast_{condition}"] for record in all_records]),
            4,
        )
        for condition in ALL_CONDITIONS
    }
    mean_contrast_loss_by_cvd_type = {
        condition: round(
            safe_mean([record[f"contrast_loss_{condition}"] for record in all_records]),
            4,
        )
        for condition in CVD_CONDITIONS
    }

    component_vulnerability_summary_table = []
    for component_type in CORE_VULNERABILITY_TYPES:
        component_records = [
            record for record in all_records if record["component_type"] == component_type
        ]
        total_components = len(component_records)
        component_vulnerability_summary_table.append(
            {
                "component_type": component_type,
                "total_components": total_components,
                "cvs_protanopia": round(
                    compute_rate(
                        sum(1 for record in component_records if not record["pass_protanopia"]),
                        total_components,
                    ),
                    4,
                ),
                "cvs_deuteranopia": round(
                    compute_rate(
                        sum(1 for record in component_records if not record["pass_deuteranopia"]),
                        total_components,
                    ),
                    4,
                ),
                "cvs_tritanopia": round(
                    compute_rate(
                        sum(1 for record in component_records if not record["pass_tritanopia"]),
                        total_components,
                    ),
                    4,
                ),
            }
        )

    top_vulnerable_component_categories = sorted(
        (
            {
                "component_type": row["component_type"],
                "total_components": row["total_components"],
                "average_vulnerability_score": round(
                    safe_mean(
                        [
                            row["cvs_protanopia"],
                            row["cvs_deuteranopia"],
                            row["cvs_tritanopia"],
                        ]
                    ),
                    4,
                ),
            }
            for row in component_vulnerability_summary_table
            if row["total_components"] > 0
        ),
        key=lambda item: (-item["average_vulnerability_score"], item["component_type"]),
    )[:5]

    return {
        "total_sites_scanned": len(site_results),
        "sites_scanned": [site_result["site"] for site_result in site_results],
        "total_elements_scanned": sum(
            site_result["total_elements_scanned"] for site_result in site_results
        ),
        "total_components": len(all_records),
        "counts_by_component_type": component_counts,
        "overall_failure_rate": overall_failure_rate,
        "failure_rate_by_cvd_type": failure_rate_by_cvd_type,
        "failure_rate_by_site": site_summary_table,
        "failure_rate_by_component_type": failure_rate_by_component_type,
        "mean_contrast_by_component_type": mean_contrast_by_component_type,
        "mean_contrast_loss_by_component_type": mean_contrast_loss_by_component_type,
        "mean_contrast_ratios": {
            "overall": mean_contrast_overall,
            "by_component_type": mean_contrast_by_component_type,
        },
        "mean_contrast_loss_by_cvd_type": mean_contrast_loss_by_cvd_type,
        "component_vulnerability_scores_by_type": component_vulnerability_scores_by_type,
        "component_vulnerability_summary_table": component_vulnerability_summary_table,
        "top_vulnerable_component_categories": top_vulnerable_component_categories,
    }


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_csv_value(value: Any) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False)


def flatten_record_for_csv(record: dict[str, Any]) -> dict[str, str | int | float]:
    flat_record: dict[str, str | int | float] = {}

    for key, value in record.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flat_record[f"{key}_{nested_key}"] = normalize_csv_value(nested_value)
        else:
            flat_record[key] = normalize_csv_value(value)

    return flat_record


def write_csv_file(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        path.write_text("", encoding="utf-8")
        return

    flattened_records = [flatten_record_for_csv(record) for record in records]
    fieldnames = sorted({key for record in flattened_records for key in record})

    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened_records)


def build_spss_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {column: normalize_csv_value(record.get(column)) for column in SPSS_EXPORT_COLUMNS}
        for record in records
    ]


async def extract_element_data(page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
          const trackedAttributes = new Set(["class", "id", "role", "href", "onclick", "type", "name"]);

          const isTransparent = (color) => {
            if (!color) {
              return true;
            }

            const normalized = color.toLowerCase().replace(/\\s+/g, "");
            return normalized === "transparent"
              || normalized === "rgba(0,0,0,0)"
              || normalized === "rgba(255,255,255,0)"
              || normalized === "rgb(0,0,0,0)";
          };

          const resolveBackgroundColor = (element) => {
            let current = element;

            while (current) {
              const currentStyle = window.getComputedStyle(current);
              const backgroundColor = currentStyle.backgroundColor;

              if (!isTransparent(backgroundColor)) {
                return backgroundColor;
              }

              current = current.parentElement;
            }

            return "rgb(255, 255, 255)";
          };

          const elements = Array.from(document.querySelectorAll("*"));

          return elements.map((element) => {
            const style = window.getComputedStyle(element);
            const attributes = {};

            for (const attribute of Array.from(element.attributes)) {
              if (trackedAttributes.has(attribute.name) || attribute.name.startsWith("aria-")) {
                attributes[attribute.name] = attribute.value;
              }
            }

            const textSource = element.innerText || element.textContent || "";
            const fullNormalizedText = textSource.replace(/\\s+/g, " ").trim();
            const normalizedText = fullNormalizedText.slice(0, 100);
            const textWordCount = fullNormalizedText
              ? fullNormalizedText.split(/\\s+/).filter(Boolean).length
              : 0;

            return {
              tag: element.tagName.toLowerCase(),
              text: normalizedText,
              text_word_count: textWordCount,
              attributes,
              styles: {
                color: style.color,
                backgroundColor: resolveBackgroundColor(element),
                rawBackgroundColor: style.backgroundColor,
                fontSize: style.fontSize,
                borderColor: style.borderColor,
                outlineColor: style.outlineColor,
                cursor: style.cursor,
                position: style.position,
                zIndex: style.zIndex,
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
                border: style.border,
                padding: style.padding,
                boxShadow: style.boxShadow,
                borderRadius: style.borderRadius
              }
            };
          });
        }
        """
    )


async def dismiss_cookie_banners(page) -> None:
        await page.evaluate(
                """
                () => {
                    const buttonSelectors = [
                        "button",
                        "[role='button']",
                        "input[type='button']",
                        "input[type='submit']",
                        "a[role='button']"
                    ];

                    const dismissText = [
                        "accept",
                        "agree",
                        "allow all",
                        "accept all",
                        "reject",
                        "decline",
                        "close",
                        "got it",
                        "ok"
                    ];

                    const cookieSignals = [
                        "cookie",
                        "consent",
                        "gdpr",
                        "onetrust",
                        "cookiebot",
                        "didomi",
                        "trustarc",
                        "cmp"
                    ];

                    const textIncludesSignal = (value, signals) => {
                        const normalized = (value || "").toLowerCase();
                        return signals.some((signal) => normalized.includes(signal));
                    };

                    const isCookieContainer = (element) => {
                        if (!element) return false;
                        const markerText = [
                            element.id,
                            element.className,
                            element.getAttribute("role"),
                            element.getAttribute("aria-label"),
                            element.textContent
                        ].join(" ");
                        return textIncludesSignal(markerText, cookieSignals);
                    };

                    for (const selector of buttonSelectors) {
                        for (const button of Array.from(document.querySelectorAll(selector))) {
                            const text = (button.innerText || button.value || button.textContent || "").trim().toLowerCase();
                            if (!text) continue;
                            if (!textIncludesSignal(text, dismissText)) continue;

                            const container = button.closest("[id], [class], [role], form, dialog, section, aside, div");
                            if (isCookieContainer(container)) {
                                try {
                                    button.click();
                                } catch {
                                    // ignore click failures
                                }
                            }
                        }
                    }

                    const removableSelectors = [
                        "#onetrust-banner-sdk",
                        ".onetrust-pc-dark-filter",
                        ".cookiebot",
                        "#CybotCookiebotDialog",
                        "[id*='cookie']",
                        "[class*='cookie']",
                        "[id*='consent']",
                        "[class*='consent']",
                        "[id*='gdpr']",
                        "[class*='gdpr']",
                        "[id*='onetrust']",
                        "[class*='onetrust']"
                    ];

                    for (const selector of removableSelectors) {
                        for (const node of Array.from(document.querySelectorAll(selector))) {
                            if (!isCookieContainer(node)) continue;
                            node.remove();
                        }
                    }
                }
                """
        )


async def scan_site(browser, url: str) -> dict[str, Any]:
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NETWORK_TIMEOUT_MS)

        try:
            await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            print(
                f"Warning: networkidle timeout for {url}; continuing after page load.",
                flush=True,
            )

        await dismiss_cookie_banners(page)
        await page.wait_for_timeout(POST_LOAD_DELAY_MS)
        raw_elements = await extract_element_data(page)

        category_counts: Counter[str] = Counter()
        classified_elements: list[dict[str, Any]] = []
        component_index = 0

        for element_data in raw_elements:
            if should_skip_element(element_data):
                continue

            component_type = classify_component(element_data)
            category_counts[component_type] += 1
            component_index += 1
            classified_elements.append(
                compute_component_metrics(
                    site=url,
                    component_index=component_index,
                    component_type=component_type,
                    element_data=element_data,
                )
            )

        other_count = category_counts.get("other", 0)
        classified_total = sum(category_counts.values())
        other_percentage = (
            (other_count / classified_total) * 100 if classified_total else 0
        )

        return {
            "site": url,
            "total_elements_scanned": len(raw_elements),
            "components_detected": classified_total,
            "category_counts": dict(category_counts),
            "other_percentage": round(other_percentage, 2),
            "components": classified_elements,
            "error": None,
        }
    finally:
        await page.close()


async def main() -> None:
    site_results: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=HEADLESS)

        try:
            for url in TARGET_SITES:
                try:
                    site_result = await asyncio.wait_for(
                        scan_site(browser, url),
                        timeout=PER_SITE_TIMEOUT_SECONDS,
                    )
                except (PlaywrightTimeoutError, TimeoutError, asyncio.TimeoutError) as exc:
                    print(
                        f"Warning: timed out while scanning {url}: {exc}",
                        flush=True,
                    )
                    site_result = {
                        "site": url,
                        "total_elements_scanned": 0,
                        "components_detected": 0,
                        "category_counts": {},
                        "other_percentage": 0.0,
                        "components": [],
                        "error": f"timeout: {type(exc).__name__}",
                    }
                except Exception as exc:
                    print(
                        f"Warning: failed to scan {url}: {exc}",
                        flush=True,
                    )
                    site_result = {
                        "site": url,
                        "total_elements_scanned": 0,
                        "components_detected": 0,
                        "category_counts": {},
                        "other_percentage": 0.0,
                        "components": [],
                        "error": f"scan_failed: {type(exc).__name__}",
                    }
                site_results.append(site_result)
        finally:
            await browser.close()

    detailed_results = [
        component
        for site_result in site_results
        for component in site_result["components"]
    ]
    spss_records = build_spss_records(detailed_results)

    for legacy_path in LEGACY_SUMMARY_OUTPUT_FILES:
        if legacy_path.exists():
            legacy_path.unlink()

    write_json_file(DETAILED_RESULTS_FILE, detailed_results)
    write_csv_file(DETAILED_RESULTS_CSV_FILE, spss_records)

    print("SPSS dataset export complete")
    print("=" * 28)
    print(f"Sites scanned: {len(site_results)}")
    print(f"Rows exported: {len(spss_records)}")
    print()
    print(f"Detailed JSON written to: {DETAILED_RESULTS_FILE}")
    print(f"Detailed CSV written to: {DETAILED_RESULTS_CSV_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
