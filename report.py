import json
import csv
import html as html_mod
from pathlib import Path
import matplotlib.pyplot as plt

CVD_TYPES = ["normal", "protanopia", "deuteranopia", "tritanopia"]

# ---------------------------------------------------------
# Contrast Threshold Logic
# ---------------------------------------------------------

def threshold_for_font(font_size: str, font_weight: str = "400") -> float:
    """
    Return the WCAG 2.1 SC 1.4.3 contrast threshold for the given font size/weight.
    Large text qualifies for the relaxed 3:1 threshold:
      - Regular text: ≥ 18 pt  →  ≥ 24 px  (at 96 dpi, 1 pt = 1.333 px)
      - Bold text:    ≥ 14 pt  →  ≥ 18.67 px  (font-weight ≥ 700)
    Everything else must meet the 4.5:1 standard threshold.
    """
    try:
        px = float(font_size.replace("px", "").strip())
    except Exception:
        px = 0.0
    try:
        weight = int(float(font_weight))
    except Exception:
        weight = 400
    if px >= 24 or (weight >= 700 and px >= 18.67):
        return 3.0
    return 4.5


def worst_case(contrast_dict: dict | None):
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


# ---------------------------------------------------------
# Failure Classification
# ---------------------------------------------------------

def classify_failure(example):
    font_thr = threshold_for_font(example.get("fontSize", "0px"), example.get("fontWeight", "400"))

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


# ---------------------------------------------------------
# CVI (Component Vulnerability Index)
# ---------------------------------------------------------

def _collect_cvd_failures(contrast: dict, font_thr: float) -> list:
    """
    Return a list of CVD-only failure dicts for one style group's contrast data.

    A CVD-only failure means the group passes WCAG under normal vision but fails
    under at least one CVD simulation (protanopia / deuteranopia / tritanopia).
    Groups that already fail for normal vision are excluded — they are general
    failures, not CVD-specific.

    Channels checked:
      text_on_bg   — WCAG AA: font_thr (4.5, or 3.0 for large text ≥18 px)
      border_on_bg — WCAG non-text indicator: 3.0
      outline_on_bg — WCAG non-text indicator: 3.0
    """
    failures = []
    channels = [
        ("text",    contrast.get("text_on_bg"),    font_thr),
        ("border",  contrast.get("border_on_bg"),  3.0),
        ("outline", contrast.get("outline_on_bg"), 3.0),
    ]
    for channel, c, thr in channels:
        if not c:
            continue
        normal = c.get("normal")
        if normal is None or normal < thr:
            # Already fails for all viewers — not a CVD-specific issue
            continue
        failing = {
            t: round(c[t], 2)
            for t in ("protanopia", "deuteranopia", "tritanopia")
            if c.get(t) is not None and c[t] < thr
        }
        if failing:
            failures.append({
                "channel":    channel,
                "normal":     round(normal, 2),
                "threshold":  thr,
                "failing_cvd": failing,
                "all_cvd": {
                    t: round(c[t], 2)
                    for t in ("protanopia", "deuteranopia", "tritanopia")
                    if c.get(t) is not None
                },
            })
    return failures


def compute_cvi(data: dict) -> list:
    """
    CVI = CVD-only vulnerable groups / total unique style groups.

    Reads directly from the raw JSON (data["sites"]) so it has access to
    individual group contrast data rather than only aggregated summary counts.

    A group is CVD-only vulnerable if it passes WCAG thresholds under normal
    vision but fails under ≥1 CVD type on any of: text, border, or outline.
    This isolates accessibility failures caused specifically by colour vision
    deficiency, not pre-existing general contrast failures.

    CVI = 0            → Fully Accessible
    CVI ≤ 0.05 (≤5%)  → Minor Risk
    CVI ≤ 0.15 (≤15%) → Moderate Risk
    CVI ≤ 0.30 (≤30%) → High Risk
    CVI  > 0.30       → Critical Risk
    """
    results = []

    for site_name, site_blob in data["sites"].items():
        if "error" in site_blob:
            continue

        groups = site_blob.get("result", {}).get("groups", [])
        total_groups = len(groups)
        if total_groups == 0:
            continue

        cvd_only_ids = set()
        for idx, g in enumerate(groups):
            contrast = g.get("contrast") or {}
            font_thr = threshold_for_font(g.get("fontSize", "0px"), g.get("fontWeight", "400"))
            if _collect_cvd_failures(contrast, font_thr):
                cvd_only_ids.add(idx)

        cvi = round(len(cvd_only_ids) / total_groups, 3)

        if cvi == 0:
            category = "Fully Accessible"
        elif cvi <= 0.05:
            category = "Minor Risk"
        elif cvi <= 0.15:
            category = "Moderate Risk"
        elif cvi <= 0.30:
            category = "High Risk"
        else:
            category = "Critical Risk"

        results.append({
            "site":             site_name,
            "cvi":              cvi,
            "category":         category,
            "total_vulnerable": len(cvd_only_ids),
            "total_styles":     total_groups,
        })

    return results
# ---------------------------------------------------------
# CVD-Vulnerable Component Details
# ---------------------------------------------------------

def find_vulnerable_components(data: dict) -> dict:
    """
    Return per-site lists of style groups that are CVD-only vulnerable,
    with per-channel contrast values and failure detail.

    Only components that pass WCAG for normal vision but fail under ≥1 CVD
    simulation are included.  Groups sorted by element count (highest impact first).

    Returns: {site_name: [list of vulnerable group dicts]}
    """
    out = {}
    for site_name, site_blob in data["sites"].items():
        if "error" in site_blob:
            out[site_name] = []
            continue

        groups = site_blob.get("result", {}).get("groups", [])
        vulnerable = []

        for g in groups:
            contrast  = g.get("contrast") or {}
            font_thr  = threshold_for_font(g.get("fontSize", "0px"), g.get("fontWeight", "400"))
            failures  = _collect_cvd_failures(contrast, font_thr)

            if failures:
                vulnerable.append({
                    "category":    g.get("category", "?"),
                    "state":       g.get("state",    "base"),
                    "count":       g.get("count",    1),
                    "sample_label": (g.get("sampleLabels") or [""])[0] or "",
                    "sample_tags":  g.get("sampleTags") or [],
                    "fontSize":     g.get("fontSize", ""),
                    "failures":     failures,
                })

        vulnerable.sort(key=lambda x: -x["count"])
        out[site_name] = vulnerable

    return out


# ---------------------------------------------------------
# Extract Contrast Data
# ---------------------------------------------------------

def extract_contrast_data(data):
    """Extract contrast ratios for each site by CVD type"""
    contrast_stats = {}
    
    for site_name, site_blob in data["sites"].items():
        if "error" in site_blob:
            continue
            
        groups = site_blob.get("result", {}).get("groups", [])
        
        # Aggregate contrast data
        text_contrasts = {"normal": [], "protanopia": [], "deuteranopia": [], "tritanopia": []}
        border_contrasts = {"normal": [], "protanopia": [], "deuteranopia": [], "tritanopia": []}
        outline_contrasts = {"normal": [], "protanopia": [], "deuteranopia": [], "tritanopia": []}
        
        for group in groups:
            contrast = group.get("contrast", {})
            
            # Text contrast
            text_on_bg = contrast.get("text_on_bg")
            if text_on_bg:
                for cvd_type in CVD_TYPES:
                    if cvd_type in text_on_bg:
                        text_contrasts[cvd_type].append(text_on_bg[cvd_type])
            
            # Border contrast
            border_on_bg = contrast.get("border_on_bg")
            if border_on_bg:
                for cvd_type in CVD_TYPES:
                    if cvd_type in border_on_bg:
                        border_contrasts[cvd_type].append(border_on_bg[cvd_type])
            
            # Outline contrast
            outline_on_bg = contrast.get("outline_on_bg")
            if outline_on_bg:
                for cvd_type in CVD_TYPES:
                    if cvd_type in outline_on_bg:
                        outline_contrasts[cvd_type].append(outline_on_bg[cvd_type])
        
        # Calculate averages
        contrast_stats[site_name] = {
            "text": {
                cvd_type: round(sum(vals) / len(vals), 2) if vals else 0
                for cvd_type, vals in text_contrasts.items()
            },
            "border": {
                cvd_type: round(sum(vals) / len(vals), 2) if vals else 0
                for cvd_type, vals in border_contrasts.items()
            },
            "outline": {
                cvd_type: round(sum(vals) / len(vals), 2) if vals else 0
                for cvd_type, vals in outline_contrasts.items()
            }
        }
    
    return contrast_stats


# ---------------------------------------------------------
# Chart Generators
# ---------------------------------------------------------

def generate_cvi_chart(cvi_results, out_path):
    names = [r["site"] for r in cvi_results]
    scores = [r["cvi"] for r in cvi_results]
    
    # Color by risk category
    colors = []
    for r in cvi_results:
        if r["category"] == "Fully Accessible":
            colors.append("#10b981")
        elif r["category"] == "Minor Risk":
            colors.append("#84cc16")
        elif r["category"] == "Moderate Risk":
            colors.append("#f59e0b")
        elif r["category"] == "High Risk":
            colors.append("#ef4444")
        else:
            colors.append("#dc2626")

    fig, ax = plt.subplots(figsize=(14,6))
    ax.bar(names, scores, color=colors, edgecolor='black', linewidth=0.8)

    ax.set_title("Component Vulnerability Index (CVI) by Site", fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel("CVI Score", fontsize=12)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=9)   
    ax.grid(axis='y', alpha=0.3, linestyle='--')

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def generate_basic_chart(names, series, labels, title, ylabel, out_path):
    fig, ax = plt.subplots(figsize=(10,5))
    width = 0.35
    x = list(range(len(names)))

    for i, s in enumerate(series):
        offset = (i - len(series)/2) * width
        ax.bar([v + offset for v in x], s, width=width, label=labels[i])

    ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=9)
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3, linestyle='--')

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def generate_risk_distribution_chart(cvi_results, out_path):
    categories = ["Fully Accessible", "Minor Risk", "Moderate Risk", "High Risk", "Critical Risk"]
    counts = {cat: 0 for cat in categories}
    
    for result in cvi_results:
        counts[result["category"]] += 1
    
    colors = ["#10b981", "#84cc16", "#f59e0b", "#ef4444", "#dc2626"]
    chart_colors = [colors[categories.index(cat)] for cat in categories]
    
    fig, ax = plt.subplots(figsize=(8,6))
    values = [counts[cat] for cat in categories]
    bars = ax.bar(categories, values, color=chart_colors, edgecolor='black', linewidth=1.5)
    
    ax.set_title("Risk Distribution Across Sites", fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel("Number of Sites", fontsize=12)
    ax.set_xticklabels(categories, rotation=45, ha="right", fontsize=10)
    
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height,
                f'{int(height)}', ha='center', va='bottom', fontweight='bold')
    
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def generate_cvi_distribution_chart(cvi_results, out_path):
    cvs = sorted([r["cvi"] for r in cvi_results])
    
    fig, ax = plt.subplots(figsize=(10,5))
    ax.hist(cvs, bins=15, color='#3b82f6', edgecolor='black', alpha=0.7)
    
    ax.set_title("CVI Score Distribution", fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel("CVI Score", fontsize=12)
    ax.set_ylabel("Frequency", fontsize=12)
    ax.axvline(sum(cvs)/len(cvs), color='red', linestyle='--', linewidth=2, label=f'Mean: {sum(cvs)/len(cvs):.3f}')
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def generate_contrast_comparison_chart(contrast_stats, out_path):
    """Generate a chart comparing average contrast ratios across all sites by vision type"""
    sites = sorted(contrast_stats.keys())
    
    text_normal = [contrast_stats[s]["text"]["normal"] for s in sites]
    text_protanopia = [contrast_stats[s]["text"]["protanopia"] for s in sites]
    text_deuteranopia = [contrast_stats[s]["text"]["deuteranopia"] for s in sites]
    text_tritanopia = [contrast_stats[s]["text"]["tritanopia"] for s in sites]
    
    fig, ax = plt.subplots(figsize=(14, 6))
    x = list(range(len(sites)))
    width = 0.2
    
    ax.bar([i - 1.5*width for i in x], text_normal, width, label='Normal', color='#10b981', alpha=0.9)
    ax.bar([i - 0.5*width for i in x], text_protanopia, width, label='Protanopia', color='#f59e0b', alpha=0.9)
    ax.bar([i + 0.5*width for i in x], text_deuteranopia, width, label='Deuteranopia', color='#3b82f6', alpha=0.9)
    ax.bar([i + 1.5*width for i in x], text_tritanopia, width, label='Tritanopia', color='#ec4899', alpha=0.9)
    
    ax.axhline(y=4.5, color='red', linestyle='--', linewidth=2, alpha=0.7, label='AA Threshold (4.5)')
    ax.set_title("Text Contrast Ratios by Vision Type Across Sites", fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel("Contrast Ratio", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(sites, rotation=45, ha="right", fontsize=8)
    ax.legend(fontsize=9, loc='upper right')
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    ax.set_ylim(0, max(max(text_normal, text_protanopia, text_deuteranopia, text_tritanopia) or [10]) + 2)
    
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def generate_cvd_impact_chart(contrast_stats, out_path):
    """Show average contrast drop from normal to each CVD type"""
    sites = sorted(contrast_stats.keys())
    
    drops_proto = []
    drops_deut = []
    drops_trit = []
    
    for site in sites:
        normal = contrast_stats[site]["text"]["normal"]
        proto = contrast_stats[site]["text"]["protanopia"]
        deut = contrast_stats[site]["text"]["deuteranopia"]
        trit = contrast_stats[site]["text"]["tritanopia"]
        
        drops_proto.append(max(0, normal - proto))
        drops_deut.append(max(0, normal - deut))
        drops_trit.append(max(0, normal - trit))
    
    fig, ax = plt.subplots(figsize=(14, 6))
    x = list(range(len(sites)))
    width = 0.25
    
    ax.bar([i - width for i in x], drops_proto, width, label='Protanopia', color='#f59e0b', alpha=0.9)
    ax.bar(x, drops_deut, width, label='Deuteranopia', color='#3b82f6', alpha=0.9)
    ax.bar([i + width for i in x], drops_trit, width, label='Tritanopia', color='#ec4899', alpha=0.9)
    
    ax.set_title("Contrast Ratio Loss from Normal Vision to CVD Types", fontsize=14, fontweight='bold', pad=20)
    ax.set_ylabel("Contrast Loss (Normal - CVD)", fontsize=12)
    ax.set_xticks(x)
    ax.set_xticklabels(sites, rotation=45, ha="right", fontsize=8)
    ax.legend(fontsize=10)
    ax.grid(axis='y', alpha=0.3, linestyle='--')
    
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close(fig)


def make_html(report, cvi_results, chart_paths, contrast_stats, vulnerable_components, out_path: Path):
        site_lookup = {s["site"]: s for s in report["sites"] if "error" not in s}
        cvi_lookup = {c["site"]: c for c in cvi_results}
        
        # Compute statistics
        all_cvs = [c["cvi"] for c in cvi_results]
        avg_cvi = sum(all_cvs) / len(all_cvs) if all_cvs else 0
        max_cvi = max(all_cvs) if all_cvs else 0
        risk_counts = {
            "Fully Accessible": len([c for c in cvi_results if c["category"] == "Fully Accessible"]),
            "Minor Risk": len([c for c in cvi_results if c["category"] == "Minor Risk"]),
            "Moderate Risk": len([c for c in cvi_results if c["category"] == "Moderate Risk"]),
            "High Risk": len([c for c in cvi_results if c["category"] == "High Risk"]),
            "Critical Risk": len([c for c in cvi_results if c["category"] == "Critical Risk"]),
        }
        
        total_vuln_text = sum(s.get("vuln_text", 0) for s in report["sites"] if "error" not in s)
        total_vuln_indicator = sum(s.get("vuln_indicator", 0) for s in report["sites"] if "error" not in s)
        total_styles = sum(s.get("unique_style_groups", 0) for s in report["sites"] if "error" not in s)

        summary_rows = []
        for site_name in sorted(site_lookup.keys()):
                s = site_lookup[site_name]
                c = cvi_lookup.get(site_name, {})
                risk_category = c.get("category", "Unknown")
                risk_color = "#10b981" if risk_category == "Fully Accessible" else \
                             "#84cc16" if risk_category == "Minor Risk" else \
                             "#f59e0b" if risk_category == "Moderate Risk" else \
                             "#ef4444" if risk_category == "High Risk" else "#dc2626"
                summary_rows.append(f"""
                <tr>
                    <td><strong>{site_name}</strong></td>
                    <td>{s.get('matched')}</td>
                    <td>{s.get('kept')}</td>
                    <td>{s.get('unique_style_groups')}</td>
                    <td>{s.get('vuln_text')}</td>
                    <td>{s.get('vuln_indicator')}</td>
                    <td>{s.get('cvd_only_text')}</td>
                    <td>{s.get('cvd_only_indicator')}</td>
                    <td><strong>{c.get('cvi')}</strong></td>
                    <td><span class=\"risk-badge\" style=\"background-color: {risk_color};\">{risk_category}</span></td>
                </tr>
                """)

        chart_blocks = []
        for title, path in chart_paths.items():
                chart_blocks.append(f"<div class=\"card\"><h3>{title}</h3><img src=\"{path}\" alt=\"{title}\"/></div>")

        # ------------------------------------------------------------------
        # Pre-compute vulnerable components HTML (built before the f-string
        # so literal { } in generated HTML don't interfere with f-string parsing)
        # ------------------------------------------------------------------
        _CVD_TYPES = ("protanopia", "deuteranopia", "tritanopia")

        def _contrast_cell(val, thr):
            if val is None:
                return "<td style='text-align:center'>—</td>"
            css = "fail-value" if val < thr else "pass-value"
            return f"<td style='text-align:center'><span class='{css}'>{val}</span></td>"

        vuln_sections = []
        for _site in sorted(site_lookup.keys()):
            _comps = vulnerable_components.get(_site, [])
            _n     = len(_comps)
            _cvi   = cvi_lookup.get(_site, {}).get("cvi", "—")

            if _n == 0:
                _body = "<p class='no-vuln'>No CVD-only vulnerable components detected for this site.</p>"
            else:
                _rows = []
                for _comp in _comps:
                    _cat    = html_mod.escape(_comp["category"])
                    _state  = _comp["state"]
                    _count  = _comp["count"]
                    _sample = html_mod.escape((_comp["sample_label"] or "")[:70])
                    _tags   = html_mod.escape(", ".join(_comp["sample_tags"][:3]))
                    _scss   = "state-error" if _state == "error" else "state-base"

                    for _fail in _comp["failures"]:
                        _ch   = _fail["channel"]
                        _chcss = {"text": "ch-text", "border": "ch-border", "outline": "ch-outline"}.get(_ch, "ch-text")
                        _thr  = _fail["threshold"]
                        _cvd_cells = "".join(
                            _contrast_cell(_fail["all_cvd"].get(t), _thr)
                            for t in _CVD_TYPES
                        )
                        _rows.append(
                            "<tr>"
                            f"<td><strong>{_cat}</strong><br>"
                            f"<small style='color:#6b7280'>{_tags}</small></td>"
                            f"<td><span class='state-badge {_scss}'>{_state}</span></td>"
                            f"<td style='text-align:center'>{_count}</td>"
                            f"<td><small>{_sample}</small></td>"
                            f"<td><span class='channel-badge {_chcss}'>{_ch}</span></td>"
                            f"<td style='text-align:center'><strong>{_fail['normal']}</strong></td>"
                            + _cvd_cells +
                            f"<td style='text-align:center'>{_thr}</td>"
                            "</tr>"
                        )

                _header = (
                    "<thead><tr>"
                    "<th>Component</th><th>State</th><th>Count</th>"
                    "<th>Sample Label</th><th>Channel</th>"
                    "<th>Normal</th><th>Protanopia</th>"
                    "<th>Deuteranopia</th><th>Tritanopia</th>"
                    "<th>WCAG Threshold</th>"
                    "</tr></thead>"
                )
                _body = (
                    "<div class='component-detail-wrapper'>"
                    "<table>" + _header + "<tbody>"
                    + "".join(_rows) +
                    "</tbody></table></div>"
                )

            vuln_sections.append(
                "<details class='site-accordion'>"
                f"<summary>"
                f"<span><strong>{html_mod.escape(_site)}</strong> "
                f"<span style='font-weight:400;color:#6b7280'>CVI: {_cvi}</span></span>"
                f"<span style='color:#667eea'>{_n} CVD-only vulnerable "
                f"component{'s' if _n != 1 else ''}</span>"
                f"</summary>"
                + _body +
                "</details>"
            )

        vuln_section_html = "\n".join(vuln_sections)

        html = f"""<!doctype html>
<html>
<head>
    <meta charset=\"utf-8\"/>
    <title>CVD UI Contrast Audit Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            color: #1f2937;
            line-height: 1.6;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }}
        
        .header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .content {{ padding: 40px; }}
        
        h2 {{ 
            font-size: 1.8em;
            margin-top: 40px;
            margin-bottom: 20px;
            color: #111827;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        
        h2:first-of-type {{ margin-top: 0; }}
        
        h3 {{
            font-size: 1.3em;
            margin: 20px 0 15px 0;
            color: #374151;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        
        .stat-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
            transition: transform 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
        }}
        
        .stat-card .value {{
            font-size: 2.5em;
            font-weight: 700;
            margin: 10px 0;
        }}
        
        .stat-card .label {{
            font-size: 0.95em;
            opacity: 0.9;
        }}
        
        .risk-badges {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        
        .risk-badge-block {{
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            font-weight: 600;
            color: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        
        .risk-badge-block .count {{
            font-size: 1.8em;
            margin: 5px 0;
        }}
        
        .bg-green {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); }}
        .bg-yellow {{ background: linear-gradient(135deg, #84cc16 0%, #65a30d 100%); }}
        .bg-orange {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }}
        .bg-red {{ background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%); }}
        .bg-darkred {{ background: linear-gradient(135deg, #dc2626 0%, #991b1b 100%); }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
            gap: 25px;
            margin: 25px 0;
        }}
        
        .card {{
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 20px;
            background: #f9fafb;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            transition: box-shadow 0.2s;
        }}
        
        .card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.12);
        }}
        
        .card h3 {{
            margin-top: 0;
            color: #667eea;
        }}
        
        .card img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            margin-top: 10px;
        }}
        
        .legend-box {{
            background: #f0f9ff;
            border-left: 4px solid #667eea;
            padding: 20px;
            border-radius: 8px;
            margin: 25px 0;
        }}
        
        .legend-box h3 {{
            margin-top: 0;
            color: #667eea;
        }}
        
        .legend-box ul {{
            list-style: none;
            padding: 0;
        }}
        
        .legend-box li {{
            margin-bottom: 12px;
            padding-left: 20px;
            position: relative;
        }}
        
        .legend-box li:before {{
            content: "→";
            position: absolute;
            left: 0;
            color: #667eea;
            font-weight: bold;
        }}
        
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        th {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 0.9em;
            letter-spacing: 0.5px;
        }}
        
        td {{
            border-bottom: 1px solid #e5e7eb;
            padding: 12px 15px;
            font-size: 0.9em;
        }}
        
        tr:hover {{
            background: #f3f4f6;
        }}
        
        .risk-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 6px;
            color: white;
            font-weight: 600;
            font-size: 0.85em;
            letter-spacing: 0.3px;
        }}
        
        .footer {{
            background: #f9fafb;
            padding: 20px 40px;
            text-align: center;
            color: #6b7280;
            border-top: 1px solid #e5e7eb;
            font-size: 0.9em;
        }}
        
        .section-divider {{
            height: 2px;
            background: linear-gradient(90deg, transparent, #667eea, transparent);
            margin: 40px 0;
        }}
        
        .two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 30px;
            margin: 25px 0;
        }}
        
        .full-width {{
            grid-column: 1 / -1;
        }}
        
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 20px 0;
        }}
        
        .metric-item {{
            background: white;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            padding: 15px;
            text-align: center;
            transition: all 0.3s;
        }}
        
        .metric-item:hover {{
            border-color: #667eea;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.15);
            transform: translateY(-2px);
        }}
        
        .metric-value {{
            font-size: 1.8em;
            font-weight: 700;
            color: #667eea;
            margin: 10px 0;
        }}
        
        .metric-label {{
            font-size: 0.85em;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .insight-box {{
            background: linear-gradient(135deg, #fef3c7 0%, #fef08a 100%);
            border-left: 4px solid #f59e0b;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        
        .insight-box h4 {{
            color: #b45309;
            margin-top: 0;
            font-size: 1.1em;
        }}
        
        .insight-box p {{
            color: #78350f;
            margin: 10px 0;
        }}
        
        .chart-section {{
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
        }}
        
        .chart-section h3 {{
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}
        
        .chart-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        
        .chart-card {{
            background: #f9fafb;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }}
        
        .chart-card img {{
            width: 100%;
            height: auto;
            border-radius: 8px;
        }}
        
        /* ---- Vulnerable component accordion ---- */
        details.site-accordion {{
            margin: 12px 0;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            overflow: hidden;
        }}
        details.site-accordion > summary {{
            background: linear-gradient(135deg, #f0f4ff 0%, #e8edff 100%);
            padding: 14px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            color: #374151;
            list-style: none;
            user-select: none;
        }}
        details.site-accordion > summary::-webkit-details-marker {{ display: none; }}
        details.site-accordion > summary::after {{
            content: "▾";
            font-size: 1.1em;
            color: #667eea;
            margin-left: 8px;
        }}
        details.site-accordion[open] > summary {{
            border-bottom: 2px solid #667eea;
        }}
        details.site-accordion > summary:hover {{
            background: linear-gradient(135deg, #e8edff 0%, #dde5ff 100%);
        }}
        .component-detail-wrapper {{ padding: 15px; background: white; overflow-x: auto; }}
        .fail-value {{ color: #dc2626; font-weight: 700; }}
        .pass-value {{ color: #059669; font-weight: 600; }}
        .channel-badge {{
            display: inline-block; padding: 3px 8px; border-radius: 4px;
            font-size: 0.8em; font-weight: 700; text-transform: uppercase;
        }}
        .ch-text    {{ background: #eff6ff; color: #1d4ed8; }}
        .ch-border  {{ background: #fdf4ff; color: #7e22ce; }}
        .ch-outline {{ background: #fff7ed; color: #c2410c; }}
        .state-badge {{
            display: inline-block; padding: 2px 8px; border-radius: 4px;
            font-size: 0.85em; font-weight: 600;
        }}
        .state-base  {{ background: #f0fdf4; color: #15803d; }}
        .state-error {{ background: #fff1f2; color: #be123c; }}
        .no-vuln {{ color: #6b7280; font-style: italic; padding: 15px 20px; }}

        @media (max-width: 768px) {{
            .header h1 {{ font-size: 1.8em; }}
            .grid {{ grid-template-columns: 1fr; }}
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .metric-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .chart-grid {{ grid-template-columns: 1fr; }}
            .two-column {{ grid-template-columns: 1fr; }}
            .content {{ padding: 25px; }}
            h2 {{ font-size: 1.5em; }}
        }}
    </style>
</head>
<body>
    <div class=\"container\">
        <div class=\"header\">
            <h1>CVD UI Contrast Audit Report</h1>
            <p>Color Vision Deficiency Accessibility Analysis</p>
            <p style=\"margin-top: 15px; font-size: 0.95em;\">Scan: {report['scan_date']} · Model: {report['cvd_model']}</p>
        </div>
        
        <div class="content">
            <h2>Executive Summary</h2>
            
            <div class=\"insight-box\">
                <h4>Key Findings</h4>
                <p><strong>{len(cvi_results)} websites audited</strong> | <strong>{risk_counts['Critical Risk']} in Critical Risk</strong> | <strong>Average CVI: {avg_cvi:.3f}</strong></p>
                <p>Most websites show significant contrast issues for color vision deficiency types, particularly affecting users with protanopia and deuteranopia.</p>
            </div>
            
            <div class=\"stats-grid\">
                <div class=\"stat-card\">
                    <div class=\"label\">Sites Audited</div>
                    <div class=\"value\">{len(cvi_results)}</div>
                </div>
                <div class=\"stat-card\">
                    <div class=\"label\">Average CVI</div>
                    <div class=\"value\">{avg_cvi:.3f}</div>
                </div>
                <div class=\"stat-card\">
                    <div class=\"label\">Total Vulnerable Groups</div>
                    <div class=\"value\">{total_vuln_text + total_vuln_indicator}</div>
                </div>
                <div class=\"stat-card\">
                    <div class=\"label\">Total Style Groups</div>
                    <div class=\"value\">{total_styles}</div>
                </div>
            </div>
            
            <div class=\"section-divider\"></div>
            
            <h3>Risk Category Breakdown</h3>
            <div class=\"risk-badges\">
                <div class=\"risk-badge-block bg-green\">
                    <div>Fully Accessible</div>
                    <div class=\"count\">{risk_counts['Fully Accessible']}</div>
                </div>
                <div class=\"risk-badge-block bg-yellow\">
                    <div>Minor Risk</div>
                    <div class=\"count\">{risk_counts['Minor Risk']}</div>
                </div>
                <div class=\"risk-badge-block bg-orange\">
                    <div>Moderate Risk</div>
                    <div class=\"count\">{risk_counts['Moderate Risk']}</div>
                </div>
                <div class=\"risk-badge-block bg-red\">
                    <div>High Risk</div>
                    <div class=\"count\">{risk_counts['High Risk']}</div>
                </div>
                <div class=\"risk-badge-block bg-darkred\">
                    <div>Critical Risk</div>
                    <div class=\"count\">{risk_counts['Critical Risk']}</div>
                </div>
            </div>
            
            <div class=\"section-divider\"></div>
            
            <div class=\"legend-box\">
                <h3>How to read this report</h3>
                <ul>
                    <li><b>Vulnerable (text)</b>: Text contrast fails WCAG thresholds for at least one vision type.</li>
                    <li><b>Vulnerable (indicator)</b>: Border/outline contrast fails the 3.0 heuristic for at least one vision type.</li>
                    <li><b>CVD-only text</b>: Passes for normal vision but fails for color vision deficiency types.</li>
                    <li><b>CVD-only indicator</b>: Same concept applied to border/outline indicators.</li>
                    <li><b>CVI (Component Vulnerability Index)</b>: Proportion of unique style groups that <em>pass</em> WCAG for normal vision but <em>fail</em> for ≥1 CVD type (protanopia / deuteranopia / tritanopia). Range 0–1. Captures only CVD-induced failures, not pre-existing general contrast failures.</li>
                    <li><b>Risk Categories</b>: Fully Accessible (0%), Minor (&le;5%), Moderate (&le;15%), High (&le;30%), Critical (&gt;30%) — percentages of style groups that are CVD-only vulnerable.</li>
                </ul>
            </div>
            
            <div class=\"section-divider\"></div>
            
            <h2>Visual Analytics Dashboard</h2>
            <p style=\"color: #6b7280; margin-bottom: 20px;\">Comprehensive charts showing vulnerability metrics, contrast ratios, and CVD impact across all websites.</p>
            <div class=\"chart-grid\">
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">Vulnerable Groups by Site</h4><img src=\"report_assets/vulnerable_groups.png\" alt=\"Vulnerable Groups\"/></div>
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">Component Vulnerability Index</h4><img src=\"report_assets/cvi_chart.png\" alt=\"CVI\"/></div>
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">Risk Distribution</h4><img src=\"report_assets/risk_distribution.png\" alt=\"Risk Distribution\"/></div>
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">CVI Score Distribution</h4><img src=\"report_assets/cvi_distribution.png\" alt=\"CVI Distribution\"/></div>
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">Text Contrast by Vision Type</h4><img src=\"report_assets/contrast_by_vision.png\" alt=\"Contrast by Vision\"/></div>
                <div class=\"chart-card\"><h4 style=\"margin: 0 0 10px 0; color: #667eea;\">Contrast Loss from Normal to CVD</h4><img src=\"report_assets/cvd_impact.png\" alt=\"CVD Impact\"/></div>
            </div>
            
            <div class=\"section-divider\"></div>

            <h2>Detailed Site Analysis</h2>
            <p>Table shows vulnerability metrics for each scanned website. Sort by CVI to identify priority areas.</p>
            <table>
                <thead>
                    <tr>
                        <th>Site</th>
                        <th>Matched</th>
                        <th>Kept</th>
                        <th>Unique Styles</th>
                        <th>Vuln Text</th>
                        <th>Vuln Indicator</th>
                        <th>CVD-only Text</th>
                        <th>CVD-only Indicator</th>
                        <th>CVI Score</th>
                        <th>Risk Level</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(summary_rows)}
                </tbody>
            </table>
        </div>

        <div class=\"section-divider\"></div>

        <h2>CVD-Only Vulnerable Components</h2>
        <p style=\"color: #6b7280; margin-bottom: 20px;\">
            Components that pass WCAG contrast thresholds under normal vision but become
            inaccessible under colour vision deficiency simulation.
            These are the failures that are <em>invisible</em> to standard (non-CVD) contrast checkers.
            Values in <span style=\"color:#dc2626;font-weight:700\">red</span> fail the threshold;
            <span style=\"color:#059669;font-weight:600\">green</span> passes.
        </p>
        {vuln_section_html}

        <div class=\"section-divider\"></div>

        <div class=\"footer\">
            <p>Report generated by CVD UI Contrast Audit · {report['scan_date']}</p>
        </div>
    </div>
</body>
</html>
"""

        out_path.write_text(html, encoding="utf-8")




def main():

    data = json.loads(Path("cvd_ui_contrast_audit.json").read_text(encoding="utf-8"))

    report = {
        "scan_date": data.get("scan_date"),
        "cvd_model": data.get("cvd_model"),
        "sites": []
    }

    for site_name, site_blob in data["sites"].items():

        if "error" in site_blob:
            report["sites"].append({
                "site":  site_name,
                "error": site_blob["error"],
            })
            continue

        res = site_blob["result"]
        summ = site_blob["summary"]

        report["sites"].append({
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
            "unique_vulnerable_groups": summ.get("unique_vulnerable_groups", 0)
        })

    # -------------------------------------------------
    # Extract contrast data
    # -------------------------------------------------
    contrast_stats = extract_contrast_data(data)

    # -------------------------------------------------
    # Generate CVI
    # -------------------------------------------------

    cvi_results = compute_cvi(data)

    with open("cvi_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["site", "cvi", "category", "total_vulnerable", "total_styles"]
        )
        writer.writeheader()
        writer.writerows(cvi_results)

    # -------------------------------------------------
    # Charts
    # -------------------------------------------------

    out_dir = Path("report_assets")
    out_dir.mkdir(exist_ok=True)

    names = [s["site"] for s in report["sites"] if "error" not in s]

    vuln_text = [s["vuln_text"] for s in report["sites"] if "error" not in s]
    vuln_indicator = [s["vuln_indicator"] for s in report["sites"] if "error" not in s]

    vulnerable_path = out_dir / "vulnerable_groups.png"
    generate_basic_chart(
        names,
        [vuln_text, vuln_indicator],
        ["Text", "Indicator"],
        "Vulnerable Groups by Site",
        "Count",
        vulnerable_path
    )

    cvi_path = out_dir / "cvi_chart.png"
    generate_cvi_chart(
        cvi_results,
        cvi_path
    )
    
    risk_dist_path = out_dir / "risk_distribution.png"
    generate_risk_distribution_chart(
        cvi_results,
        risk_dist_path
    )
    
    cvi_dist_path = out_dir / "cvi_distribution.png"
    generate_cvi_distribution_chart(
        cvi_results,
        cvi_dist_path
    )
    
    contrast_comp_path = out_dir / "contrast_by_vision.png"
    generate_contrast_comparison_chart(
        contrast_stats,
        contrast_comp_path
    )
    
    cvd_impact_path = out_dir / "cvd_impact.png"
    generate_cvd_impact_chart(
        contrast_stats,
        cvd_impact_path
    )

    chart_paths = {
        "Vulnerable Groups by Site": vulnerable_path.as_posix(),
        "Component Vulnerability Index (CVI)": cvi_path.as_posix(),
        "Risk Distribution": risk_dist_path.as_posix(),
        "CVI Score Distribution": cvi_dist_path.as_posix(),
        "Text Contrast by Vision Type": contrast_comp_path.as_posix(),
        "Contrast Loss from Normal to CVD": cvd_impact_path.as_posix(),
    }

    vulnerable_components = find_vulnerable_components(data)

    make_html(report, cvi_results, chart_paths, contrast_stats, vulnerable_components, Path("report.html"))

    print("✔ Generated:")
    print(" - cvi_results.csv")
    print(" - report_assets/vulnerable_groups.png")
    print(" - report_assets/cvi_chart.png")
    print(" - report_assets/risk_distribution.png")
    print(" - report_assets/cvi_distribution.png")
    print(" - report_assets/contrast_by_vision.png")
    print(" - report_assets/cvd_impact.png")
    print(" - report.html")


if __name__ == "__main__":
    main()