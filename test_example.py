# save as: button_style_dump.py
# run: python button_style_dump.py "https://example.com" "button"
# or:  python button_style_dump.py "https://your-site.com" "button:has-text('Submit')"

import sys
from playwright.sync_api import sync_playwright

def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://scrape.do/blog/web-scraping-with-playwright/"
    selector = sys.argv[2] if len(sys.argv) > 2 else "button"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")

        btn = page.locator(selector).first
        btn.wait_for(state="visible")

        text = btn.inner_text()  # visible text [web:16]
        styles = btn.evaluate(
            """(el) => {
                const cs = window.getComputedStyle(el);  // computed styles [web:22]
                return {
                    tag: el.tagName,
                    id: el.id || null,
                    className: el.className || null,
                    // common useful button styles
                    color: cs.getPropertyValue('color'),
                    backgroundColor: cs.getPropertyValue('background-color'),
                    fontFamily: cs.getPropertyValue('font-family'),
                    fontSize: cs.getPropertyValue('font-size'),
                    fontWeight: cs.getPropertyValue('font-weight'),
                    padding: cs.getPropertyValue('padding'),
                    border: cs.getPropertyValue('border'),
                    borderRadius: cs.getPropertyValue('border-radius'),
                    lineHeight: cs.getPropertyValue('line-height'),
                    display: cs.getPropertyValue('display'),
                    cursor: cs.getPropertyValue('cursor'),
                };
            }"""
        )  # locator.evaluate pattern for computed style [web:22]

        print("=== Button ===")
        print(f"URL: {url}")
        print(f"Selector: {selector}")
        print(f"Text: {text!r}")
        print("=== Computed styles ===")
        for k, v in styles.items():
            print(f"{k}: {v}")

        browser.close()

if __name__ == "__main__":
    main()
