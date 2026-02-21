import sys
import json
from playwright.sync_api import sync_playwright

GLOBAL_SELECTOR = """
a, button, input, select, textarea,
label, nav, header, footer, aside, section,
form, [role], [onclick], [tabindex],
p, h1, h2, h3, h4, h5, h6
"""

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
        case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
            return "heading"
        case "p":
            return "paragraph"
        case _:
            if role in ["button", "link", "navigation"]:
                return role
            return "other"

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.booking.com/"

    grouped_styles = {}
    total_scanned = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)  # Wait for potential dynamic content to load

        elements = page.locator(GLOBAL_SELECTOR)
        count = elements.count()

        for i in range(count):
            el = elements.nth(i)

            if not el.is_visible():
                continue

            data = el.evaluate("""(el) => {
                const cs = window.getComputedStyle(el);
                return {
                    tag: el.tagName,
                    role: el.getAttribute("role"),
                    text: (el.innerText || "").trim().slice(0, 80),
                    textColor: cs.getPropertyValue("color"),
                    backgroundColor: cs.getPropertyValue("background-color"),
                    fontSize: cs.getPropertyValue("font-size")
                };
            }""")

            if not data["text"]:
                continue

            total_scanned += 1

            category = classify(data["tag"], data["role"])
            key = f"{category}|{data['textColor']}|{data['backgroundColor']}|{data['fontSize']}"

            if key not in grouped_styles:
                grouped_styles[key] = {
                    "category": category,
                    "textColor": data["textColor"],
                    "backgroundColor": data["backgroundColor"],
                    "fontSize": data["fontSize"],
                    "count": 1,
                    "sampleTexts": [data["text"]],
                    "sampleTags": [data["tag"]]
                }
            else:
                grouped_styles[key]["count"] += 1

                # Add up to 5 sample texts only
                if len(grouped_styles[key]["sampleTexts"]) < 5:
                    grouped_styles[key]["sampleTexts"].append(data["text"])

                if data["tag"] not in grouped_styles[key]["sampleTags"]:
                    grouped_styles[key]["sampleTags"].append(data["tag"])

        browser.close()

    results = {
        "url": url,
        "total_elements_scanned": total_scanned,
        "total_unique_style_groups": len(grouped_styles),
        "groups": list(grouped_styles.values())
    }

    with open("UI_elements.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("Saved UI elements scan.")
    print("Elements scanned:", total_scanned)
    print("Unique style groups:", len(grouped_styles))

if __name__ == "__main__":
    main()