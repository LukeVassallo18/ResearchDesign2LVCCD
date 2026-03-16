# CVD Accessibility Audit

A Python research tool for automated web accessibility evaluation focused on
**colour vision deficiencies (CVD)**.

---

## Project Overview

This tool is part of an academic research study evaluating colour accessibility
risks in web interfaces. It follows a **simulation-based accessibility
evaluation methodology** — used when direct user testing is not feasible —
to identify which UI component types are most vulnerable to contrast failures
across different types of colour vision deficiency.

---

## Research Question

> **Which UI component groups are most vulnerable to colour accessibility
> issues across simulated colour vision deficiencies?**

---

## Methodology

The evaluation pipeline consists of the following stages:

| # | Stage | Description | Status |
|---|-------|-------------|--------|
| 1 | Website scanning | Load URLs, open in headless browser | ✅ Implemented |
| 2 | UI component detection | Parse DOM, categorise elements | 🔲 Planned |
| 3 | Screenshot capture | Full-page + per-component PNGs | ✅ Implemented |
| 4 | CVD simulation | Apply protanopia / deuteranopia / tritanopia transforms | 🔲 Planned |
| 5 | Contrast analysis | Compute WCAG contrast ratios pre/post simulation | 🔲 Planned |
| 6 | Risk classification | Pass / Warning / Critical per component | 🔲 Planned |
| 7 | Trend analysis | Failure rates by component type and CVD type | 🔲 Planned |

---

## Project Structure

```
cvd-accessibility-audit/
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

## Configuration

Edit `config.py` to adjust project-wide settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `BROWSER_HEADLESS` | `True` | Set to `False` to watch the browser during scans |
| `PAGE_LOAD_TIMEOUT` | `30000` | Max page load time (ms) |
| `WAIT_AFTER_LOAD` | `2000` | JS settle buffer after networkidle (ms) |
| `VIEWPORT_WIDTH` | `1280` | Browser viewport width (px) |
| `VIEWPORT_HEIGHT` | `720` | Browser viewport height (px) |

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
