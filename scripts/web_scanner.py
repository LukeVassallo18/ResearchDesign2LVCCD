import json
from playwright.sync_api import sync_playwright


def load_sites(path="data/sites.json"):

    with open(path, "r") as f:
        sites = json.load(f)

    return sites


def scan_site(page, site):

    result = {
        "site": site["site_name"],
        "url": site["url"],
        "success": False,
        "error": None
    }

    try:

        page.goto(site["url"], wait_until="networkidle", timeout=30000)

        result["success"] = True

    except Exception as e:

        result["error"] = str(e)

    return result


def run_scanner(sites):

    results = []

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for site in sites:

            print(f"Scanning {site['site_name']}...")

            result = scan_site(page, site)

            results.append(result)

        browser.close()

    return results