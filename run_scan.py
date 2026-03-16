import json
from scripts.web_scanner import load_sites, run_scanner


def main():

    sites = load_sites()

    results = run_scanner(sites)

    with open("data/component_counts.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nComponent counts saved to data/component_counts.json")


if __name__ == "__main__":
    main()