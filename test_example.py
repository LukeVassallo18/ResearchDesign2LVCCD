# save as: button_style_dump.py
# run: python button_style_dump.py "https://example.com" "button"
# or:  python button_style_dump.py "https://your-site.com" "button:has-text('Submit')"

import sys
import json
from unittest import result
from playwright.sync_api import sync_playwright

GLOBAL_SELECTOR = """
a, button, input, select, textarea, label, nav, header, footer, aside, section, form, div, span, [role], [onclick], [tabindex], p, h1, h2, h3, h4, h5, h6
"""

def classify_element(tag, role, onclick, tabindex):
    tag = (tag or "").lower()
    role = (role or "").lower()

    match tag:
        case "a":
            return "link"
        case "button":
            return "button"
        case "input" | "textarea" | "select":
            return "input"
        case "nav":
            return "navigation"
        case "form":
            return "form"
        case "header" | "footer" | "aside" | "section":
            return "layout"
        case "label":
            return "label"
        case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
            return "heading"
        case "p" | "div" | "span":
            if role in ["button", "link"]:
                return role
            if onclick is not None or tabindex is not None:
                return "interactive"
            return "text"
        case _:
            # for custom tags, use role or attributes to classify
            match role:
                case "button":
                    return "button"
                case "link":
                    return "link"
                case "navigation":
                    return "navigation"
                case "textbox":
                    return "input"
                case _:
                    if onclick is not None or tabindex is not None:
                        return "interactive_other"
                    return "container_or_text"
        

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.booking.com/?chal_t=1771689821449&force_referer="
    results = {
        "url": url,
        "elements": []
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # use a global selector to find all potential interactive elements, then classify them based on tag, role, and attributes
        page = browser.new_page()
        # wait until network idle to ensure all resources are loaded, especially for single page applications
        page.goto(url, wait_until="networkidle")

        elements = page.locator(GLOBAL_SELECTOR)
        count = elements.count()
        print(f"Found {count} potential interactive elements using global selector.")

        for i in range(count):
            el = elements.nth(i)

            if not el.is_visible():
                continue

            # FIRST extract the data
            data = el.evaluate("""(el) => {
                const cs = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();

                return {
                    tag: el.tagName,
                    id: el.id || null,
                    className: (typeof el.className === "string" ? el.className : null),
                    role: el.getAttribute("role"),
                    onclick: el.getAttribute("onclick"),
                    tabindex: el.getAttribute("tabindex"),
                    text: (el.innerText || "").trim().slice(0, 120),
                    textColor: cs.getPropertyValue("color"),
                    backgroundColor: cs.getPropertyValue("background-color"),
                    fontSize: cs.getPropertyValue("font-size"),
                    bbox: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height
                    }
                };
            }""")

            # THEN filter by size
            if data["bbox"]["width"] < 5 or data["bbox"]["height"] < 5:
                continue

            # THEN classify
            data["category"] = classify_element(
                data["tag"],
                data["role"],
                data["onclick"],
                data["tabindex"]
            )

            results["elements"].append(data)

        browser.close()

        with open("button_style_dump.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"Saved {len(results['elements'])} elements to button_style_dump.json")

if __name__ == "__main__":
    main()
