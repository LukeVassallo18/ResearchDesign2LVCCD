import sys
import json
from datetime import date
from urllib.parse import urlparse
from collections import defaultdict
from playwright.sync_api import sync_playwright

# Layer A (interactive UI): controls + ARIA roles + JS-driven / focusable elements
INTERACTIVE_SELECTOR = """
a, button, input, select, textarea,
[role="button"], [role="link"], [role="textbox"], [role="navigation"],
[onclick], [tabindex]
"""

# Layer B (content text): headings + paragraphs + labels + list items (common UI text)
CONTENT_SELECTOR = """
h1, h2, h3, h4, h5, h6, p, label, li
"""

# ---------- Classification ----------
def classify(tag, role):
    tag = (tag or "").lower()
    role = (role or "").lower()

    match tag:
        case "button":
            return "button"
        case "a":
            return "link"
        case "input" | "textarea" | "select":
            return "input"
        case "nav":
            return "navigation"
        case "label":
            return "label"
        case "li":
            return "listitem"
        case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
            return "heading"
        case "p":
            return "paragraph"
        case _:
            # fall back to semantic role if present
            if role in ["button", "link", "navigation", "textbox"]:
                return role
            return "other"


# ---------- Helpers ----------
def domain_key(url):
    netloc = urlparse(url).netloc
    return netloc.removeprefix("www.")


DEFAULT_URLS = [
    "https://www.booking.com/",
    "https://www.airbnb.com/",
    "https://react.dev/",
]


# ---------- Core scan ----------
def scan_selector(page, url, selector, layer_name):
    """
    Scans elements matched by selector, extracts a compact set of accessibility-relevant info,
    resolves effective background by walking up DOM, and groups results to keep JSON small.
    """

    grouped_styles = {}
    totals = {
        "elements_kept": 0,
        "matched": 0,
        "raw_bg_transparent_kept": 0,   # how many kept elements had raw bg transparent (before ancestor resolution)
    }
    category_counts = defaultdict(int)

    loc = page.locator(selector)
    totals["matched"] = loc.count()

    for i in range(totals["matched"]):
        el = loc.nth(i)

        # visibility check (fast)
        if not el.is_visible():
            continue

        # extract minimal-but-debuggable info
        data = el.evaluate(
            """(el) => {
                const cs = window.getComputedStyle(el);

                // 1) Build a "label" for debugging & later accessibility logic:
                // Prefer visible text, else aria-label/title/placeholder/value.
                const text = (el.innerText || "").trim();
                const aria = (el.getAttribute("aria-label") || "").trim();
                const title = (el.getAttribute("title") || "").trim();
                const placeholder = (el.getAttribute("placeholder") || "").trim();
                const value = (el.value != null ? String(el.value).trim() : "");

                const label = text || aria || title || placeholder || value;

                // 2) Effective background resolution:
                // If this element is transparent, walk up ancestors until non-transparent.
                function isTransparent(bg) {
                    if (!bg) return true;
                    bg = bg.toLowerCase();
                    if (bg === "transparent") return true;
                    if (bg.startsWith("rgba")) {
                        // rgba(r,g,b,a) -> if a == 0
                        const m = bg.match(/rgba\\(([^)]+)\\)/);
                        if (!m) return false;
                        const parts = m[1].split(",").map(s => s.trim());
                        const a = parseFloat(parts[3]);
                        return !isNaN(a) && a === 0;
                    }
                    return false;
                }

                const rawBg = cs.getPropertyValue("background-color");
                let effectiveBg = rawBg;

                if (isTransparent(effectiveBg)) {
                    let cur = el;
                    while (cur) {
                        const curStyle = window.getComputedStyle(cur);
                        const curBg = curStyle.getPropertyValue("background-color");
                        if (!isTransparent(curBg)) {
                            effectiveBg = curBg;
                            break;
                        }
                        cur = cur.parentElement;
                    }
                }

                // 3) Minimal fields for contrast & colourblind-related metrics later
                return {
                    tag: el.tagName,
                    role: el.getAttribute("role"),
                    onclick: el.getAttribute("onclick"),
                    tabindex: el.getAttribute("tabindex"),
                    label: label.slice(0, 80),

                    textColor: cs.getPropertyValue("color"),
                    rawBackgroundColor: rawBg,
                    backgroundColor: effectiveBg,
                    fontSize: cs.getPropertyValue("font-size"),
                    fontWeight: cs.getPropertyValue("font-weight"),
                    textDecoration: cs.getPropertyValue("text-decoration-line"),

                    // helpful for later analysis (e.g., icon-only controls)
                    hasVisibleText: !!text
                };
            }"""
        )

        # Keep if we have a usable label (debuggable) OR it's an interactive element with ARIA label/value etc.
        if not data.get("label"):
            continue

        totals["elements_kept"] += 1
        if data.get("rawBackgroundColor") in ("rgba(0, 0, 0, 0)", "transparent"):
            totals["raw_bg_transparent_kept"] += 1

        category = classify(data.get("tag"), data.get("role"))
        category_counts[category] += 1

        # Group key: layer + category + text/bg/font info
        # (This keeps JSON small but still meaningful for metrics.)
        key = "|".join(
            [
                layer_name,
                category,
                data.get("textColor", ""),
                data.get("backgroundColor", ""),
                data.get("fontSize", ""),
                data.get("fontWeight", ""),
                data.get("textDecoration", ""),
            ]
        )

        if key not in grouped_styles:
            grouped_styles[key] = {
                "layer": layer_name,
                "category": category,
                "textColor": data["textColor"],
                "backgroundColor": data["backgroundColor"],
                "fontSize": data["fontSize"],
                "fontWeight": data["fontWeight"],
                "textDecoration": data["textDecoration"],
                "count": 1,
                "sampleLabels": [data["label"]],
                "sampleTags": [data["tag"]],
                "sampleRoles": [data["role"]] if data.get("role") else [],
                "rawBgTransparentExamples": 1 if data.get("rawBackgroundColor") in ("rgba(0, 0, 0, 0)", "transparent") else 0,
            }
        else:
            g = grouped_styles[key]
            g["count"] += 1
            if len(g["sampleLabels"]) < 5 and data["label"] not in g["sampleLabels"]:
                g["sampleLabels"].append(data["label"])
            if data["tag"] not in g["sampleTags"]:
                g["sampleTags"].append(data["tag"])
            if data.get("role") and data["role"] not in g["sampleRoles"]:
                g["sampleRoles"].append(data["role"])
            if data.get("rawBackgroundColor") in ("rgba(0, 0, 0, 0)", "transparent"):
                g["rawBgTransparentExamples"] += 1

    return {
        "layer": layer_name,
        "selector": selector,
        "matched": totals["matched"],
        "elements_kept": totals["elements_kept"],
        "raw_bg_transparent_kept": totals["raw_bg_transparent_kept"],
        "category_counts": dict(category_counts),
        "groups": list(grouped_styles.values()),
    }


def scan_url(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3000)

    interactive = scan_selector(page, url, INTERACTIVE_SELECTOR, "interactive")
    content = scan_selector(page, url, CONTENT_SELECTOR, "content")

    # Merge layers into a single site report
    all_groups = interactive["groups"] + content["groups"]

    total_kept = interactive["elements_kept"] + content["elements_kept"]
    total_matched = interactive["matched"] + content["matched"]

    # Merge category counts across layers
    merged_category_counts = defaultdict(int)
    for cat, c in interactive["category_counts"].items():
        merged_category_counts[cat] += c
    for cat, c in content["category_counts"].items():
        merged_category_counts[cat] += c

    return {
        "url": url,
        "matched_total": total_matched,
        "elements_kept_total": total_kept,
        "unique_style_groups_total": len(all_groups),
        "layers": {
            "interactive": {
                "matched": interactive["matched"],
                "elements_kept": interactive["elements_kept"],
                "raw_bg_transparent_kept": interactive["raw_bg_transparent_kept"],
                "category_counts": interactive["category_counts"],
                "groups": interactive["groups"],
            },
            "content": {
                "matched": content["matched"],
                "elements_kept": content["elements_kept"],
                "raw_bg_transparent_kept": content["raw_bg_transparent_kept"],
                "category_counts": content["category_counts"],
                "groups": content["groups"],
            },
        },
        "category_counts_total": dict(merged_category_counts),
    }


# ---------- Console summaries (step 3) ----------
def print_site_summary(domain, result, top_n=5):
    print(f"\n=== {domain} ===")
    print(f"URL: {result['url']}")
    print(f"Matched total (two layers): {result['matched_total']}")
    print(f"Elements kept total: {result['elements_kept_total']}")
    print(f"Unique style groups total: {result['unique_style_groups_total']}")

    print("\nCategory counts (kept elements):")
    for cat, cnt in sorted(result["category_counts_total"].items(), key=lambda x: (-x[1], x[0])):
        print(f"  - {cat}: {cnt}")

    # Show how often raw background was transparent (before ancestor resolution)
    raw_trans = (
        result["layers"]["interactive"]["raw_bg_transparent_kept"]
        + result["layers"]["content"]["raw_bg_transparent_kept"]
    )
    print(f"\nRaw background transparent (kept elements): {raw_trans}")

    # Top groups by count (across both layers)
    all_groups = result["layers"]["interactive"]["groups"] + result["layers"]["content"]["groups"]
    top = sorted(all_groups, key=lambda g: g["count"], reverse=True)[:top_n]

    print(f"\nTop {top_n} style groups by frequency:")
    for g in top:
        sample = g["sampleLabels"][0] if g["sampleLabels"] else ""
        print(
            f"  [{g['layer']}/{g['category']}] count={g['count']} | "
            f"{g['textColor']} on {g['backgroundColor']} | "
            f"font={g['fontSize']} weight={g['fontWeight']} deco={g['textDecoration']} | "
            f"sample='{sample}'"
        )


def main():
    urls = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_URLS
    websites = {}

    with sync_playwright() as p:
        # headless=False helps you debug; switch to True when stable/faster
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for url in urls:
            key = domain_key(url)
            print(f"\nScanning: {url}")
            try:
                result = scan_url(page, url)
                websites[key] = result
                print_site_summary(key, result, top_n=5)
            except Exception as e:
                websites[key] = {"url": url, "error": str(e)}
                print(f"  ERROR scanning {url}: {e}")

        browser.close()

    output = {
        "scan_date": date.today().isoformat(),
        "total_websites": len(websites),
        "websites": websites,
    }

    with open("UI_elements.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved results for {len(websites)} URL(s) to UI_elements.json.")


if __name__ == "__main__":
    main()