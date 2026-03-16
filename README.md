
## Project Structure

```
research_design/
│
├── .venv/                        # Python virtual environment (not committed)
├── requirements.txt              # Python dependencies
├── README.md                     # This file
├── config.py                     # Central path & browser configuration
├── run_scan.py                   # Main pipeline entry point
│
├── data/
│   └── sites.csv                 # Input: list of websites to scan
│
├── screenshots/                  # Output: full-page PNG screenshots
│
└── modules/
    ├── __init__.py
    ├── web_scanner.py            # Stage 1 — Playwright-based page scanner
    ├── screenshot_capture.py     # Stage 3 — Full-page screenshot capture
    └── component_detector.py     # Stage 2 — UI component detection (planned)
```

---

## Setup

### 1. Create and activate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browser binaries

```bash
playwright install
```

---

## Adding or Changing Sites

Edit `data/sites.csv`. The file must contain `site_name` and `url` columns:

```csv
site_name,url
BBC,https://bbc.com
CNN,https://cnn.com
Wikipedia,https://wikipedia.org
```

Add any number of rows. Each site will be scanned in sequence.

---

## Running the Scanner

```bash
python run_scan.py
```

The script shows a `tqdm` progress bar and logs each step to stdout.

---

## Output

| Path | Description |
|------|-------------|
| `screenshots/<site>_fullpage.png` | Full-page PNG of each scanned site |

Future stages will add:

| Path | Description |
|------|-------------|
| `simulations/protanopia/` | CVD-transformed screenshots |
| `simulations/deuteranopia/` | |
| `simulations/tritanopia/` | |
| `data/component_results.csv` | Per-component contrast + risk results |
| `reports/trends.csv` | Aggregated failure rates by component × CVD type |
| `reports/figures/` | Matplotlib visualisations |

---

## Dependencies

| Library | Purpose |
|---------|---------|
| `playwright` | Headless browser automation for page scanning |
| `pandas` | Structured data handling for site lists and results |
| `beautifulsoup4` | HTML/DOM parsing for component detection |
| `requests` | Auxiliary HTTP requests |
| `tqdm` | Progress bar for pipeline stages |
