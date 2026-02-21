import re
from playwright.sync_api import sync_playwright, expect

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # show browser
        page = browser.new_page()

        page.goto("https://playwright.dev/")
        expect(page).to_have_title(re.compile("Playwright"))

        page.get_by_role("link", name="Get started").click()
        expect(page.get_by_role("heading", name="Installation")).to_be_visible()

        page.wait_for_timeout(2000)
        browser.close()

if __name__ == "__main__":
    main()