import json
import csv
from pathlib import Path

CVD_TYPES = ["normal", "protanopia", "deuteranopia", "tritanopia"]

def threshold_for_font(font_size: str) -> float:
    # Same logic you used: >=18px counts as large text => 3.0
    try:
        px = float(font_size.replace("px", "").strip())
    except Exception:
        px = 0.0
    return 3.0 if px >= 18 else 4.5

def worst_case(contrast_dict: dict | None):
    """
    Returns (min_value, min_key) across normal/prot/deut/trit
    """
    if not contrast_dict:
        return (None, None)
    best = None
    best_k = None
    for k in CVD_TYPES:
        v = contrast_dict.get(k)
        if v is None:
            continue
        if best is None or v < best:
            best = v
            best_k = k
    return (best, best_k)

def classify_failure(example):
    """
    Determine which channel(s) failed:
      - text below AA threshold (4.5 or 3.0 depending on font size)
      - border below 3.0
      - outline below 3.0
    """
    font_thr = threshold_for_font(example.get("fontSize", "0px"))

    text_c = (example.get("contrast") or {}).get("text_on_bg")
    border_c = (example.get("contrast") or {}).get("border_on_bg")
    outline_c = (example.get("contrast") or {}).get("outline_on_bg")

    text_min, text_min_k = worst_case(text_c)
    border_min, border_min_k = worst_case(border_c)
    outline_min, outline_min_k = worst_case(outline_c)

    reasons = []
    if text_min is not None and text_min < font_thr:
        reasons.append(f"text<{font_thr} (worst {text_min} @ {text_min_k})")
    if border_min is not None and border_min < 3.0:
        reasons.append(f"border<3.0 (worst {border_min} @ {border_min_k})")
    if outline_min is not None and outline_min < 3.0:
        reasons.append(f"outline<3.0 (worst {outline_min} @ {outline_min_k})")

    return {
        "font_threshold": font_thr,
        "text_worst": text_min,
        "text_worst_type": text_min_k,
        "border_worst": border_min,
        "border_worst_type": border_min_k,
        "outline_worst": outline_min,
        "outline_worst_type": outline_min_k,
        "reasons": reasons,
        "is_vulnerable": len(reasons) > 0,
    }

def cvd_only_flag(example, channel: str, threshold: float):
    """
    True if normal passes but at least one CVD fails.
    channel in {"text_on_bg","border_on_bg","outline_on_bg"}
    """
    c = (example.get("contrast") or {}).get(channel)
    if not c:
        return False
    normal = c.get("normal")
    if normal is None or normal < threshold:
        return False
    for t in ["protanopia", "deuteranopia", "tritanopia"]:
        v = c.get(t)
        if v is not None and v < threshold:
            return True
    return False

def make_html(report, out_path: Path):
    # Simple self-contained HTML (no JS needed)
    rows = []
    for site in report["sites"]:
        rows.append(f"""
        <h2>{site['site']}</h2>
        <p>
          Matched: {site['matched']} | Kept: {site['kept']} | Unique style groups: {site['unique_style_groups']}
          <br/>
          Vulnerable (text): {site['vuln_text']} (CVD-only: {site['cvd_only_text']}) |
          Vulnerable (indicator): {site['vuln_indicator']} (CVD-only: {site['cvd_only_indicator']})
        </p>
        <table>
          <thead>
            <tr>
              <th>State</th><th>Category</th><th>Count</th><th>Sample</th>
              <th>Worst Text</th><th>Worst Border</th><th>Worst Outline</th>
              <th>Reasons</th>
            </tr>
          </thead>
          <tbody>
        """)

        for ex in site["top_examples"]:
            rows.append(f"""
            <tr>
              <td>{ex['state']}</td>
              <td>{ex['category']}</td>
              <td>{ex['count']}</td>
              <td>{ex['sample']}</td>
              <td>{ex['text_worst']} ({ex['text_worst_type']})</td>
              <td>{ex['border_worst']} ({ex['border_worst_type']})</td>
              <td>{ex['outline_worst']} ({ex['outline_worst_type']})</td>
              <td>{ex['reasons']}</td>
            </tr>
            """)

        rows.append("</tbody></table><hr/>")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>CVD UI Contrast Audit Report</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 24px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
  th {{ background: #f3f3f3; }}
  code {{ background:#f7f7f7; padding:2px 4px; border-radius:4px; }}
</style>
</head>
<body>
<h1>CVD UI Contrast Audit Report</h1>
<p>
Scan date: <b>{report['scan_date']}</b><br/>
Model: <b>{report['cvd_model']}</b>
</p>
{''.join(rows)}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")

def main():
    in_path = Path("cvd_ui_contrast_audit.json")
    data = json.loads(in_path.read_text(encoding="utf-8"))

    report = {
        "scan_date": data.get("scan_date"),
        "cvd_model": data.get("cvd_model"),
        "sites": []
    }

    csv_rows = []

    for site_name, site_blob in data["sites"].items():
        if "error" in site_blob:
            report["sites"].append({
                "site": site_name,
                "error": site_blob["error"]
            })
            continue

        res = site_blob["result"]
        summ = site_blob["summary"]

        site_entry = {
            "site": site_name,
            "url": summ["url"],
            "matched": res["matched"],
            "scanned": res["scanned"],
            "kept": summ["elements_kept"],
            "unique_style_groups": summ["unique_style_groups"],
            "vuln_text": summ["vulnerable_groups_text"],
            "vuln_indicator": summ["vulnerable_groups_indicator"],
            "cvd_only_text": summ["cvd_only_fail_text"],
            "cvd_only_indicator": summ["cvd_only_fail_indicator"],
            "top_examples": []
        }

        for ex in summ.get("top_vulnerable_examples", []):
            meta = classify_failure(ex)

            # add cvd-only flags per channel (more explicit)
            font_thr = meta["font_threshold"]
            cvd_only_text = cvd_only_flag(ex, "text_on_bg", font_thr)
            cvd_only_border = cvd_only_flag(ex, "border_on_bg", 3.0)
            cvd_only_outline = cvd_only_flag(ex, "outline_on_bg", 3.0)

            ex_row = {
                "site": site_name,
                "url": summ["url"],
                "state": ex.get("state"),
                "category": ex.get("category"),
                "count": ex.get("count"),
                "sample": (ex.get("sample") or "").replace("\n", " ")[:140],
                "fontSize": ex.get("fontSize"),
                "font_threshold": font_thr,

                "text_worst": meta["text_worst"],
                "text_worst_type": meta["text_worst_type"],
                "border_worst": meta["border_worst"],
                "border_worst_type": meta["border_worst_type"],
                "outline_worst": meta["outline_worst"],
                "outline_worst_type": meta["outline_worst_type"],

                "reasons": "; ".join(meta["reasons"]) if meta["reasons"] else "",
                "cvd_only_text": cvd_only_text,
                "cvd_only_border": cvd_only_border,
                "cvd_only_outline": cvd_only_outline,
            }

            site_entry["top_examples"].append({
                **ex_row,
                "reasons": ex_row["reasons"]
            })
            csv_rows.append(ex_row)

        report["sites"].append(site_entry)

    # 1) small JSON summary
    Path("report_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # 2) CSV for Excel / thesis tables
    csv_path = Path("vulnerable_examples.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(csv_rows[0].keys()) if csv_rows else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(csv_rows)

    # 3) HTML report
    make_html(report, Path("report.html"))

    print("Wrote:")
    print(" - report_summary.json")
    print(" - vulnerable_examples.csv")
    print(" - report.html")

if __name__ == "__main__":
    main()