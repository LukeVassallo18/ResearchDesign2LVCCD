import sys
import json
import re
from datetime import date
from urllib.parse import urlparse
from collections import defaultdict

import numpy as np
from PIL import Image

from playwright.sync_api import sync_playwright

# DaltonLens 0.1 API (your installed version)
from daltonlens.simulate import Deficiency, Simulator_Machado2009


# ----------------------------
# Selectors
# ----------------------------

INTERACTIVE_SELECTOR = """
a, button, input, select, textarea,
[role="button"], [role="link"], [role="textbox"], [role="tab"], [role="checkbox"], [role="radio"],
[onclick], [tabindex]
"""


DEFAULT_URLS = [
    "https://www.booking.com/",
    "https://www.airbnb.com/",
    "https://react.dev/"
]


# ----------------------------
# Utilities: URL key
# ----------------------------

def domain_key(url: str) -> str:
    netloc = urlparse(url).netloc
    return netloc.removeprefix("www.")


# ----------------------------
# DaltonLens (CVD simulation)
# ----------------------------

DEFICIENCY_MAP = {
    "protanopia": Deficiency.PROTAN,
    "deuteranopia": Deficiency.DEUTAN,
    "tritanopia": Deficiency.TRITAN,
}

_SIMULATOR = Simulator_Machado2009()
_CVD_CACHE = {}  # (rgb_tuple, deficiency_str) -> rgb_tuple


def simulate_rgb(rgb, deficiency: str):
    """
    Simulate a single RGB color under a CVD type using DaltonLens.
    Passes a NumPy array (not a PIL Image) to match the DaltonLens API.
    Uses caching for speed.
    """
    if rgb is None:
        return None

    deficiency = deficiency.lower().strip()
    if deficiency not in DEFICIENCY_MAP:
        raise ValueError(f"Unknown deficiency: {deficiency}")

    key = (rgb, deficiency)
    if key in _CVD_CACHE:
        return _CVD_CACHE[key]

    # DaltonLens in your environment expects a numpy array with .astype(...)
    arr = np.array([[rgb]], dtype=np.uint8)  # shape (1, 1, 3)

    sim_arr = _SIMULATOR.simulate_cvd(arr, DEFICIENCY_MAP[deficiency], severity=1.0)

    # Some versions return PIL Images; normalize to numpy
    if isinstance(sim_arr, Image.Image):
        sim_arr = np.array(sim_arr)
    else:
        sim_arr = np.asarray(sim_arr)
    if sim_arr.dtype != np.uint8:
        # if it looks like 0..1 floats, scale up; otherwise just clip
        maxv = float(np.max(sim_arr)) if sim_arr.size else 1.0
        if maxv <= 1.0:
            sim_arr = (sim_arr * 255.0)
        sim_arr = np.clip(sim_arr, 0, 255).astype(np.uint8)

    sim_rgb = tuple(sim_arr[0, 0].tolist())

    _CVD_CACHE[key] = sim_rgb
    return sim_rgb


# ----------------------------
# Color parsing + WCAG contrast
# ----------------------------

_RGBA_RE = re.compile(r"rgba?\(([^)]+)\)", re.IGNORECASE)


def parse_css_color_to_rgb(color: str):
    """
    Supports rgb(...) and rgba(...) CSS strings.
    Returns (r,g,b) ints in 0..255, or None if unsupported/transparent.
    """
    if not color:
        return None

    c = color.strip().lower()
    if c == "transparent":
        return None

    m = _RGBA_RE.search(c)
    if not m:
        return None

    parts = [p.strip() for p in m.group(1).split(",")]
    if len(parts) < 3:
        return None

    try:
        r = int(float(parts[0]))
        g = int(float(parts[1]))
        b = int(float(parts[2]))

        # Treat fully transparent rgba as None
        if len(parts) >= 4:
            a = float(parts[3])
            if a == 0:
                return None

        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))
        return (r, g, b)
    except Exception:
        return None


def _srgb_channel_to_linear(v255: float) -> float:
    v = v255 / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb):
    r, g, b = rgb
    R = _srgb_channel_to_linear(r)
    G = _srgb_channel_to_linear(g)
    B = _srgb_channel_to_linear(b)
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def contrast_ratio(rgb1, rgb2):
    if rgb1 is None or rgb2 is None:
        return None
    L1 = relative_luminance(rgb1)
    L2 = relative_luminance(rgb2)
    lighter = max(L1, L2)
    darker = min(L1, L2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def contrast_for_all_vision(fg_rgb, bg_rgb):
    """
    Compute contrast ratio for normal vision + CVD simulations.
    """
    out = {"normal": contrast_ratio(fg_rgb, bg_rgb)}
    for d in ("protanopia", "deuteranopia", "tritanopia"):
        fg2 = simulate_rgb(fg_rgb, d) if fg_rgb else None
        bg2 = simulate_rgb(bg_rgb, d) if bg_rgb else None
        out[d] = contrast_ratio(fg2, bg2)
    return out


# ----------------------------
# Classification
# ----------------------------

def classify(tag, role):
    tag = (tag or "").lower()
    role = (role or "").lower()

    match tag:
        case "button":
            return "button"
        case "a":
            return "link"
        case "input" | "select" | "textarea":
            return "input"
        case _:
            if role in ["button", "link", "textbox", "tab", "checkbox", "radio"]:
                return role
            return "interactive_other"


# ----------------------------
# JS extraction (effective BG + accessibility hints)
# ----------------------------

EXTRACT_JS = r"""
(el) => {
  const cs = window.getComputedStyle(el);

  // ---- label extraction (for debugging & reporting) ----
  const text = (el.innerText || "").trim();
  const aria = (el.getAttribute("aria-label") || "").trim();
  const title = (el.getAttribute("title") || "").trim();
  const placeholder = (el.getAttribute("placeholder") || "").trim();
  const value = (el.value != null ? String(el.value).trim() : "");
  const label = (text || aria || title || placeholder || value).slice(0, 140);

  // ---- transparent check ----
  function isTransparent(bg) {
    if (!bg) return true;
    bg = bg.toLowerCase();
    if (bg === "transparent") return true;
    if (bg.startsWith("rgba")) {
      const m = bg.match(/rgba\(([^)]+)\)/);
      if (!m) return false;
      const parts = m[1].split(",").map(s => s.trim());
      const a = parseFloat(parts[3]);
      return !isNaN(a) && a === 0;
    }
    return false;
  }

  // ---- effective background (walk up ancestors) ----
  function effectiveBackground(node) {
    let cur = node;
    let depth = 0;
    while (cur) {
      const st = window.getComputedStyle(cur);
      const bg = st.getPropertyValue("background-color");
      if (!isTransparent(bg)) return { bg, depth };
      cur = cur.parentElement;
      depth += 1;
      if (depth > 25) break; // avoid pathological DOM
    }
    const bodyBg = window.getComputedStyle(document.body).getPropertyValue("background-color");
    return { bg: bodyBg || "rgb(255, 255, 255)", depth: -1 };
  }

  const bgInfo = effectiveBackground(el);

  // ---- styles relevant to contrast + indicators (borders/outlines) ----
  const borderTopColor = cs.getPropertyValue("border-top-color");
  const borderTopWidth = cs.getPropertyValue("border-top-width");
  const borderTopStyle = cs.getPropertyValue("border-top-style");

  const outlineColor = cs.getPropertyValue("outline-color");
  const outlineWidth = cs.getPropertyValue("outline-width");
  const outlineStyle = cs.getPropertyValue("outline-style");

  const boxShadow = cs.getPropertyValue("box-shadow");

  // ---- a11y attributes for form validation ----
  const ariaInvalid = el.getAttribute("aria-invalid");
  const required = el.hasAttribute("required") || el.getAttribute("aria-required") === "true";

  return {
    tag: el.tagName,
    role: el.getAttribute("role"),
    type: el.getAttribute("type"),
    label,
    hasVisibleText: !!text,

    textColor: cs.getPropertyValue("color"),
    rawBackgroundColor: cs.getPropertyValue("background-color"),
    backgroundColor: bgInfo.bg,
    bgResolvedDepth: bgInfo.depth,

    fontSize: cs.getPropertyValue("font-size"),
    fontWeight: cs.getPropertyValue("font-weight"),
    textDecoration: cs.getPropertyValue("text-decoration-line"),

    borderColor: borderTopColor,
    borderWidth: borderTopWidth,
    borderStyle: borderTopStyle,

    outlineColor,
    outlineWidth,
    outlineStyle,

    boxShadow,

    ariaInvalid,
    required
  };
}
"""


# ----------------------------
# Error-state triggering (best effort)
# ----------------------------

def maybe_trigger_error_state(page, el, base_data):
    """
    Best-effort trigger:
      - focus
      - blur (Tab)
      - for some types (email/url/number), enter invalid values then blur
    Won't work on all websites, but catches many common patterns.
    """
    tag = (base_data.get("tag") or "").upper()
    typ = (base_data.get("type") or "").lower()

    try:
        el.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass

    # Try focus/click
    try:
        el.click(timeout=1500, force=True)
    except Exception:
        try:
            el.focus(timeout=1500)
        except Exception:
            return False

    # If it's an input with a known validator type, try invalid text
    if tag == "INPUT" and typ in ("email", "url", "number"):
        try:
            el.fill("abc", timeout=1500)  # invalid for email/url/number
        except Exception:
            pass

    # Blur via Tab
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass

    # Give the UI a moment to update styles/messages
    try:
        page.wait_for_timeout(250)
    except Exception:
        pass

    return True


# ----------------------------
# Grouping helpers (efficiency)
# ----------------------------

def style_key(layer, category, state, data):
    """
    Key defines a 'style token' you can score once.
    Include indicator styles so border/outline checks map to tokens too.
    """
    return "|".join([
        layer,
        category,
        state,  # "base" or "error"
        data.get("textColor", ""),
        data.get("backgroundColor", ""),
        data.get("fontSize", ""),
        data.get("fontWeight", ""),
        data.get("textDecoration", ""),
        data.get("borderColor", ""),
        data.get("borderWidth", ""),
        data.get("borderStyle", ""),
        data.get("outlineColor", ""),
        data.get("outlineWidth", ""),
        data.get("outlineStyle", ""),
    ])


def _append_unique(items, value, limit=5):
    if value and value not in items and len(items) < limit:
        items.append(value)


def _init_group(layer, state, category, data):
    return {
        "layer": layer,
        "state": state,
        "category": category,
        "textColor": data.get("textColor"),
        "backgroundColor": data.get("backgroundColor"),
        "bgResolvedDepth": data.get("bgResolvedDepth"),
        "fontSize": data.get("fontSize"),
        "fontWeight": data.get("fontWeight"),
        "textDecoration": data.get("textDecoration"),
        "borderColor": data.get("borderColor"),
        "borderWidth": data.get("borderWidth"),
        "borderStyle": data.get("borderStyle"),
        "outlineColor": data.get("outlineColor"),
        "outlineWidth": data.get("outlineWidth"),
        "outlineStyle": data.get("outlineStyle"),
        "count": 1,
        "sampleLabels": [data.get("label")],
        "sampleTags": [data.get("tag")],
        "sampleRoles": [data.get("role")] if data.get("role") else [],
        "a11y": {
            "required_examples": 1 if data.get("required") else 0,
            "aria_invalid_examples": 1 if data.get("ariaInvalid") else 0,
        },
    }


def _update_group(group, data):
    group["count"] += 1
    _append_unique(group["sampleLabels"], data.get("label"))
    _append_unique(group["sampleTags"], data.get("tag"), limit=10)
    _append_unique(group["sampleRoles"], data.get("role"), limit=10)
    if data.get("required"):
        group["a11y"]["required_examples"] += 1
    if data.get("ariaInvalid"):
        group["a11y"]["aria_invalid_examples"] += 1


def compute_group_contrasts(group):
    """
    Compute contrast for group token:
      - text vs bg
      - border vs bg (indicator)
      - outline vs bg (indicator)
    Under normal + prot/deut/trit.
    """
    text_rgb = parse_css_color_to_rgb(group["textColor"])
    bg_rgb = parse_css_color_to_rgb(group["backgroundColor"])
    border_rgb = parse_css_color_to_rgb(group["borderColor"])
    outline_rgb = parse_css_color_to_rgb(group["outlineColor"])

    out = {
        "text_on_bg": contrast_for_all_vision(text_rgb, bg_rgb) if text_rgb and bg_rgb else None,
        "border_on_bg": contrast_for_all_vision(border_rgb, bg_rgb) if border_rgb and bg_rgb else None,
        "outline_on_bg": contrast_for_all_vision(outline_rgb, bg_rgb) if outline_rgb and bg_rgb else None,
    }
    return out


# ----------------------------
# Scanning
# ----------------------------

def scan_url(page, url, max_elements=500):
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3000)

    loc = page.locator(INTERACTIVE_SELECTOR)
    matched = loc.count()
    scan_n = min(matched, max_elements)

    # group tokens for efficiency
    groups = {}
    category_counts = defaultdict(int)

    # stats
    kept = 0
    error_state_captured = 0

    for i in range(scan_n):
        el = loc.nth(i)

        try:
            if not el.is_visible():
                continue
        except Exception:
            continue

        try:
            base = el.evaluate(EXTRACT_JS)
        except Exception:
            continue

        if not base.get("label"):
            continue

        kept += 1
        category = classify(base.get("tag"), base.get("role"))
        category_counts[category] += 1

        # --- base state token ---
        k_base = style_key("interactive", category, "base", base)
        if k_base not in groups:
            groups[k_base] = _init_group("interactive", "base", category, base)
        else:
            _update_group(groups[k_base], base)

        # --- try error state only for form fields ---
        is_form_field = (base.get("tag") in ("INPUT", "SELECT", "TEXTAREA")) or (base.get("role") == "textbox")
        if is_form_field:
            triggered = maybe_trigger_error_state(page, el, base)
            if not triggered:
                continue

            try:
                err = el.evaluate(EXTRACT_JS)
            except Exception:
                continue

            # Only keep an error-state token if something meaningfully changes
            changed = (
                (err.get("borderColor") and err.get("borderColor") != base.get("borderColor")) or
                (err.get("outlineColor") and err.get("outlineColor") != base.get("outlineColor")) or
                (err.get("ariaInvalid") and err.get("ariaInvalid") != base.get("ariaInvalid"))
            )

            if not changed:
                continue

            error_state_captured += 1

            k_err = style_key("interactive", category, "error", err)
            if k_err not in groups:
                err_group = _init_group("interactive", "error", category, err)
                # Preserve fallback label behavior for error state
                if not err_group["sampleLabels"][0]:
                    err_group["sampleLabels"][0] = base.get("label")
                groups[k_err] = err_group
            else:
                err_data = dict(err)
                err_data["label"] = err.get("label") or base.get("label")
                _update_group(groups[k_err], err_data)

    # Compute contrasts once per group token (efficient)
    group_list = list(groups.values())
    for g in group_list:
        g["contrast"] = compute_group_contrasts(g)

    return {
        "url": url,
        "matched": matched,
        "scanned": scan_n,
        "elements_kept": kept,
        "error_state_tokens_seen": error_state_captured,
        "category_counts": dict(category_counts),
        "unique_style_groups": len(group_list),
        "groups": group_list,
    }


# ----------------------------
# Vulnerability summary (simple, actionable)
# ----------------------------

def summarize(site_result):
    """
    Flags potentially vulnerable groups:
      - text contrast below AA threshold in normal OR any CVD type
      - indicator (border/outline) contrast below 3.0 in normal OR any CVD type
    Notes:
      - AA: 4.5 normal text, 3.0 large text (>=18px heuristic)
      - For borders/outlines, we use 3.0 as a heuristic for visibility of non-text indicators.
    """
    summary = {
        "url": site_result["url"],
        "elements_kept": site_result["elements_kept"],
        "unique_style_groups": site_result["unique_style_groups"],
        "vulnerable_groups_text": 0,
        "vulnerable_groups_indicator": 0,
        "cvd_only_fail_text": 0,
        "cvd_only_fail_indicator": 0,
        "top_vulnerable_examples": [],
    }

    def threshold_for_font(font_size: str):
        try:
            px = float(font_size.replace("px", "").strip())
        except Exception:
            px = 0.0
        return 3.0 if px >= 18 else 4.5

    def any_below(contrasts: dict | None, thr: float):
        if not contrasts:
            return False
        for _, v in contrasts.items():
            if v is None:
                continue
            if v < thr:
                return True
        return False

    def normal_pass_but_cvd_fail(contrasts: dict | None, thr: float):
        if not contrasts:
            return False
        normal = contrasts.get("normal")
        if normal is None or normal < thr:
            return False
        for d in ("protanopia", "deuteranopia", "tritanopia"):
            v = contrasts.get(d)
            if v is not None and v < thr:
                return True
        return False

    examples = []

    for g in site_result["groups"]:
        thr_text = threshold_for_font(g.get("fontSize", "0px"))

        text_c = (g.get("contrast") or {}).get("text_on_bg")
        border_c = (g.get("contrast") or {}).get("border_on_bg")
        outline_c = (g.get("contrast") or {}).get("outline_on_bg")

        text_bad = any_below(text_c, thr_text) if text_c else False
        indicator_bad = False

        # Use border or outline as indicator channels
        if border_c and any_below(border_c, 3.0):
            indicator_bad = True
        if outline_c and any_below(outline_c, 3.0):
            indicator_bad = True

        if text_bad:
            summary["vulnerable_groups_text"] += 1
            if normal_pass_but_cvd_fail(text_c, thr_text):
                summary["cvd_only_fail_text"] += 1

        if indicator_bad:
            summary["vulnerable_groups_indicator"] += 1
            # consider cvd-only on either border or outline
            if (border_c and normal_pass_but_cvd_fail(border_c, 3.0)) or (outline_c and normal_pass_but_cvd_fail(outline_c, 3.0)):
                summary["cvd_only_fail_indicator"] += 1

        if text_bad or indicator_bad:
            # keep compact example list
            examples.append({
                "layer": g["layer"],
                "state": g["state"],
                "category": g["category"],
                "count": g["count"],
                "textColor": g["textColor"],
                "backgroundColor": g["backgroundColor"],
                "borderColor": g["borderColor"],
                "outlineColor": g["outlineColor"],
                "fontSize": g["fontSize"],
                "sample": (g["sampleLabels"][0] if g.get("sampleLabels") else ""),
                "contrast": g.get("contrast"),
            })

    # Pick top examples by frequency (most impactful)
    examples.sort(key=lambda x: x["count"], reverse=True)
    summary["top_vulnerable_examples"] = examples[:10]
    return summary


def print_console(site_result, site_summary):
    print(f"\n=== {domain_key(site_result['url'])} ===")
    print(f"URL: {site_result['url']}")
    print(f"Matched: {site_result['matched']} | Scanned: {site_result['scanned']} | Kept: {site_result['elements_kept']}")
    print(f"Unique style groups: {site_result['unique_style_groups']}")
    print(f"Error-state tokens captured: {site_result['error_state_tokens_seen']}")
    print("\nCategory counts:")
    for k, v in sorted(site_result["category_counts"].items(), key=lambda x: (-x[1], x[0])):
        print(f"  - {k}: {v}")

    print("\nVulnerability summary:")
    print(f"  - Vulnerable groups (text): {site_summary['vulnerable_groups_text']} (CVD-only: {site_summary['cvd_only_fail_text']})")
    print(f"  - Vulnerable groups (indicator border/outline): {site_summary['vulnerable_groups_indicator']} (CVD-only: {site_summary['cvd_only_fail_indicator']})")

    if site_summary["top_vulnerable_examples"]:
        print("\nTop vulnerable examples (by impact):")
        for ex in site_summary["top_vulnerable_examples"][:5]:
            # show normal contrast quickly (if available)
            tn = ex.get("contrast", {}).get("text_on_bg", {}).get("normal")
            bn = ex.get("contrast", {}).get("border_on_bg", {}).get("normal") if ex.get("contrast", {}).get("border_on_bg") else None
            on = ex.get("contrast", {}).get("outline_on_bg", {}).get("normal") if ex.get("contrast", {}).get("outline_on_bg") else None
            print(
                f"  [{ex['state']}/{ex['category']}] count={ex['count']} "
                f"text={tn} border={bn} outline={on} sample='{ex['sample']}'"
            )


# ----------------------------
# Main
# ----------------------------

def main():
    urls = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_URLS

    output = {
        "scan_date": date.today().isoformat(),
        "cvd_model": "DaltonLens 0.1 / Simulator_Machado2009",
        "cvd_types": ["protanopia", "deuteranopia", "tritanopia"],
        "sites": {}
    }

    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for url in urls:
                print(f"\nScanning: {url}")
                try:
                    site = scan_url(page, url, max_elements=500)
                    site_summary = summarize(site)
                    output["sites"][domain_key(url)] = {
                        "result": site,
                        "summary": site_summary
                    }
                    print_console(site, site_summary)
                except Exception as e:
                    output["sites"][domain_key(url)] = {"error": str(e), "url": url}
                    print(f"  ERROR: {e}")
    except KeyboardInterrupt:
        print("\nScan interrupted by user.")
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass

    with open("cvd_ui_contrast_audit.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\nSaved: cvd_ui_contrast_audit.json")


if __name__ == "__main__":
    main()