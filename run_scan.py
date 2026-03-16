import json
from scripts.web_scanner import load_sites, run_scanner


def main():

    sites = load_sites()

    results = run_scanner(sites)

    success = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    print("\nScan Summary")
    print("----------------")
    print("Sites scanned:", len(results))
    print("Successful:", len(success))
    print("Failed:", len(failed))

    if failed:

        print("\nFailures:")

        for f in failed:
            print(f["site"], "-", f["error"])

    with open("data/scan_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()