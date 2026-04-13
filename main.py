import asyncio
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


TARGET_SITES = [
    "https://developer.mozilla.org",
    "https://www.apple.com/",
]

HEADLESS = os.getenv("ACCESSIBILITY_SCANNER_HEADLESS", "false").lower() == "true"
MAX_OUTPUT_PER_SITE = 200
NETWORK_TIMEOUT_MS = 60_000
OUTPUT_DIR = Path("output")
SCAN_RESULTS_FILE = OUTPUT_DIR / "scan_results.json"
ANALYSIS_RESULTS_FILE = OUTPUT_DIR / "analysis_summary.json"

BUTTON_CLASS_KEYWORDS = ("btn", "button", "cta", "primary", "action")
NAV_CLASS_KEYWORDS = ("nav", "menu", "navbar")
CARD_CLASS_KEYWORDS = ("card", "tile", "box")
ALERT_CLASS_KEYWORDS = ("alert", "error", "warning")
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
    "br",
    "hr",
}


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


def attribute_exists(attributes: dict[str, Any], name: str) -> bool:
    return name in attributes and attributes[name] is not None


def has_visual_role(element_data: dict[str, Any]) -> bool:
    tag_name = element_data["tag"]
    attributes = element_data["attributes"]
    styles = element_data["styles"]
    has_border = has_visible_border(styles.get("border"))
    has_raw_background = not is_transparent_color(styles.get("rawBackgroundColor"))

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
            },
            attribute_exists(attributes, "href"),
            attribute_exists(attributes, "onclick"),
            bool(attributes.get("role")),
            bool(attributes.get("aria-label")),
            styles.get("cursor") == "pointer",
            contains_keyword(
                joined_tokens,
                BUTTON_CLASS_KEYWORDS
                + NAV_CLASS_KEYWORDS
                + CARD_CLASS_KEYWORDS
                + ALERT_CLASS_KEYWORDS,
            ),
            has_border,
            has_padding(styles.get("padding")) and has_raw_background,
        )
    )


def should_skip_element(element_data: dict[str, Any]) -> bool:
    if element_data["tag"] in IGNORED_TAGS:
        return True

    styles = element_data["styles"]
    text = normalize_text(element_data.get("text", ""))
    element_data["text"] = text

    if styles.get("display") == "none" or styles.get("visibility") == "hidden":
        return True

    if not text and not has_visual_role(element_data):
        return True

    return False


def classify_component(element_data: dict[str, Any]) -> str:
    tag_name = element_data["tag"]
    attributes = element_data["attributes"]
    styles = element_data["styles"]

    role = (attributes.get("role") or "").strip().lower()
    class_tokens = build_token_string(attributes.get("class", ""), attributes.get("id", ""))
    href_exists = attribute_exists(attributes, "href")
    onclick_exists = attribute_exists(attributes, "onclick")
    background = styles.get("backgroundColor")
    has_border = has_visible_border(styles.get("border"))

    if (
        tag_name == "button"
        or role == "button"
        or (
            tag_name == "a"
            and contains_keyword(class_tokens, BUTTON_CLASS_KEYWORDS)
        )
        or onclick_exists
        or (
            styles.get("cursor") == "pointer"
            and not is_transparent_color(background)
            and has_padding(styles.get("padding"))
            and (
                not href_exists
                or has_border
                or contains_keyword(class_tokens, BUTTON_CLASS_KEYWORDS)
                or role == "button"
                or onclick_exists
            )
        )
    ):
        return "button"

    if (tag_name == "a" or href_exists) and not (
        tag_name == "a" and contains_keyword(class_tokens, BUTTON_CLASS_KEYWORDS)
    ):
        return "link"

    if (
        tag_name == "nav"
        or role == "navigation"
        or contains_keyword(class_tokens, NAV_CLASS_KEYWORDS)
    ):
        return "navigation"

    if tag_name == "form":
        return "form"

    if tag_name in {"input", "textarea", "select"}:
        return "input"

    if role == "alert" or contains_keyword(class_tokens, ALERT_CLASS_KEYWORDS):
        return "alert"

    if tag_name in {"p", "span", "label"} or starts_with_heading_tag(tag_name):
        return "text"

    if tag_name == "header":
        return "header"

    if tag_name == "footer":
        return "footer"

    if (
        tag_name == "div"
        and contains_keyword(class_tokens, CARD_CLASS_KEYWORDS)
        and (
            not is_transparent_color(styles.get("rawBackgroundColor"))
            or not is_transparent_color(background)
        )
    ):
        return "card"

    return "other"


def summarize_texts(elements: list[dict[str, Any]], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    summary: list[str] = []

    for element in elements:
        text = normalize_text(element.get("text", ""))
        if not text or text in seen:
            continue
        seen.add(text)
        summary.append(text)
        if len(summary) >= limit:
            break

    return summary


def build_site_analysis(site_result: dict[str, Any]) -> dict[str, Any]:
    results = site_result["results"]
    category_counts = site_result["category_counts"]
    sorted_categories = sorted(
        category_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    examples_by_component: dict[str, list[str]] = {}
    for component_name in (
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
    ):
        component_examples = [
            element for element in results if element["component"] == component_name
        ]
        if component_examples:
            examples_by_component[component_name] = summarize_texts(component_examples)

    dominant_components = [
        {"component": component, "count": count}
        for component, count in sorted_categories[:5]
    ]

    return {
        "site": site_result["site"],
        "total_elements_scanned": site_result["total_elements_scanned"],
        "components_detected": sum(category_counts.values()),
        "output_records_written": len(results),
        "category_counts": category_counts,
        "dominant_components": dominant_components,
        "sample_text_by_component": examples_by_component,
    }


def build_analysis_report(site_results: list[dict[str, Any]]) -> dict[str, Any]:
    overall_counts: Counter[str] = Counter()
    total_elements_scanned = 0
    total_components_detected = 0
    site_analyses: list[dict[str, Any]] = []

    for site_result in site_results:
        total_elements_scanned += site_result["total_elements_scanned"]
        overall_counts.update(site_result["category_counts"])
        total_components_detected += sum(site_result["category_counts"].values())
        site_analyses.append(build_site_analysis(site_result))

    return {
        "total_sites_scanned": len(site_results),
        "total_elements_scanned": total_elements_scanned,
        "total_components_detected": total_components_detected,
        "overall_category_counts": dict(overall_counts),
        "site_analysis": site_analyses,
    }


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def print_analysis_report(analysis_report: dict[str, Any]) -> None:
    print("Accessibility Scan Analysis")
    print("=" * 27)
    print(f"Sites scanned: {analysis_report['total_sites_scanned']}")
    print(f"Total elements scanned: {analysis_report['total_elements_scanned']}")
    print(f"Total components detected: {analysis_report['total_components_detected']}")
    print()
    print("Overall component counts:")

    for component, count in sorted(
        analysis_report["overall_category_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  - {component}: {count}")

    for site_summary in analysis_report["site_analysis"]:
        print()
        print(f"Site: {site_summary['site']}")
        print(f"  Elements scanned: {site_summary['total_elements_scanned']}")
        print(f"  Components detected: {site_summary['components_detected']}")
        print("  Top component categories:")

        for item in site_summary["dominant_components"]:
            print(f"    - {item['component']}: {item['count']}")

        print("  Representative findings:")
        for component, texts in site_summary["sample_text_by_component"].items():
            joined_examples = "; ".join(texts) if texts else "No text examples"
            print(f"    - {component}: {joined_examples}")


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

            return window.getComputedStyle(element).backgroundColor;
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
            const normalizedText = textSource.replace(/\\s+/g, " ").trim().slice(0, 100);

            return {
              tag: element.tagName.toLowerCase(),
              text: normalizedText,
              attributes,
              styles: {
                color: style.color,
                backgroundColor: resolveBackgroundColor(element),
                rawBackgroundColor: style.backgroundColor,
                fontSize: style.fontSize,
                cursor: style.cursor,
                display: style.display,
                visibility: style.visibility,
                border: style.border,
                padding: style.padding
              }
            };
          });
        }
        """
    )


async def scan_site(browser, url: str) -> dict[str, Any]:
    page = await browser.new_page()

    try:
        await page.goto(url, wait_until="load", timeout=NETWORK_TIMEOUT_MS)

        try:
            await page.wait_for_load_state("networkidle", timeout=NETWORK_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            print(
                f"Warning: networkidle timeout for {url}; continuing after page load.",
                flush=True,
            )

        await page.wait_for_timeout(2_000)
        raw_elements = await extract_element_data(page)

        category_counts: Counter[str] = Counter()
        classified_elements: list[dict[str, Any]] = []

        for element_data in raw_elements:
            if should_skip_element(element_data):
                continue

            component_type = classify_component(element_data)
            category_counts[component_type] += 1

            classified_elements.append(
                {
                    "site": url,
                    "component": component_type,
                    "tag": element_data["tag"],
                    "text": element_data["text"],
                    "color": element_data["styles"]["color"],
                    "background": element_data["styles"]["backgroundColor"],
                    "font_size": element_data["styles"]["fontSize"],
                    "attributes": element_data["attributes"],
                }
            )

        return {
            "site": url,
            "total_elements_scanned": len(raw_elements),
            "components_detected": sum(category_counts.values()),
            "category_counts": dict(category_counts),
            "results": classified_elements[:MAX_OUTPUT_PER_SITE],
        }
    finally:
        await page.close()


async def main() -> None:
    site_results: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=HEADLESS)

        try:
            for url in TARGET_SITES:
                site_result = await scan_site(browser, url)
                site_results.append(site_result)
        finally:
            await browser.close()

    scan_payload = {
        "sites": site_results,
        "limits": {
            "max_output_per_site": MAX_OUTPUT_PER_SITE,
            "headless": HEADLESS,
        },
    }
    analysis_report = build_analysis_report(site_results)

    write_json_file(SCAN_RESULTS_FILE, scan_payload)
    write_json_file(ANALYSIS_RESULTS_FILE, analysis_report)
    print_analysis_report(analysis_report)
    print()
    print(f"Raw scan JSON written to: {SCAN_RESULTS_FILE}")
    print(f"Analysis JSON written to: {ANALYSIS_RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
