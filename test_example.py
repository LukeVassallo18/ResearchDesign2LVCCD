import sys
import json
from datetime import date
from urllib.parse import urlparse
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

DEFAULT_URLS = [
    "https://www.booking.com/",
    "https://www.airbnb.com/",
    "https://react.dev/"
]

def scan_url(page, url):
    grouped_styles = {}
    total_scanned = 0

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

    return {
        "url": url,
        "total_elements_scanned": total_scanned,
        "total_unique_style_groups": len(grouped_styles),
        "groups": list(grouped_styles.values())
    }

def domain_key(url):
    netloc = urlparse(url).netloc
    return netloc.removeprefix("www.")

def main():
    urls = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_URLS

    websites = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for url in urls:
            print(f"Scanning: {url}")
            result = scan_url(page, url)
            key = domain_key(url)
            websites[key] = result
            print(f"  Elements scanned: {result['total_elements_scanned']}")
            print(f"  Unique style groups: {result['total_unique_style_groups']}")

        browser.close()

    output = {
        "scan_date": date.today().isoformat(),
        "total_websites": len(websites),
        "websites": websites
    }

    with open("UI_elements.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved results for {len(websites)} URL(s) to UI_elements.json.")

if __name__ == "__main__":
    main()