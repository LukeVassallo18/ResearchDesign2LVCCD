import json

import pytest

import main


def make_element(
    *,
    tag: str = "div",
    text: str = "Sample",
    attributes: dict | None = None,
    styles: dict | None = None,
    text_word_count: int | None = None,
) -> dict:
    return {
        "tag": tag,
        "text": text,
        "text_word_count": text_word_count if text_word_count is not None else main.word_count(text),
        "attributes": attributes or {},
        "styles": {
            "color": "rgb(0, 0, 0)",
            "backgroundColor": "rgb(255, 255, 255)",
            "rawBackgroundColor": "rgb(255, 255, 255)",
            "fontSize": "16px",
            "borderColor": "rgb(0, 0, 0)",
            "outlineColor": "rgb(0, 0, 0)",
            "cursor": "auto",
            "position": "static",
            "zIndex": "auto",
            "display": "block",
            "visibility": "visible",
            "opacity": "1",
            "border": "none",
            "padding": "0px",
            "boxShadow": "none",
            "borderRadius": "0px",
            **(styles or {}),
        },
    }


def test_parse_rgb_supports_common_formats() -> None:
    assert main.parse_rgb("rgb(10, 20, 30)") == (10, 20, 30, 1.0)
    assert main.parse_rgb("rgba(10, 20, 30, 0.5)") == (10, 20, 30, 0.5)
    assert main.parse_rgb("#0f0") == (0, 255, 0, 1.0)
    assert main.parse_rgb("#33669980") == (51, 102, 153, pytest.approx(128 / 255))


def test_composite_rgba_over_background() -> None:
    rgba = (255, 0, 0, 0.5)
    background = (255, 255, 255)
    assert main.composite_rgba_over_background(rgba, background) == (255, 128, 128)


def test_contrast_ratio_black_on_white_is_21() -> None:
    ratio = main.contrast_ratio((0, 0, 0), (255, 255, 255))
    assert ratio == pytest.approx(21.0, rel=1e-3)


def test_get_wcag_threshold_uses_large_text_rule() -> None:
    assert main.get_wcag_threshold("16px") == 4.5
    assert main.get_wcag_threshold("18px") == 3.0


def test_classify_component_button_link_and_text() -> None:
    button = make_element(tag="button", text="Submit")
    link = make_element(tag="a", text="Read more", attributes={"href": "/docs"})
    text = make_element(tag="p", text="Paragraph text")

    assert main.classify_component(button) == "button"
    assert main.classify_component(link) == "link"
    assert main.classify_component(text) == "text"


def test_should_skip_element_for_hidden_or_empty_noise() -> None:
    hidden = make_element(styles={"display": "none"})
    empty_non_visual = make_element(tag="div", text="", styles={"rawBackgroundColor": "transparent"})

    assert main.should_skip_element(hidden) is True
    assert main.should_skip_element(empty_non_visual) is True


def test_is_cookie_consent_element_detects_overlay_banner() -> None:
    cookie_banner = make_element(
        tag="div",
        text="We use cookies to improve your experience",
        attributes={"id": "cookie-consent-banner", "role": "dialog"},
        styles={"position": "fixed"},
    )

    assert main.is_cookie_consent_element(cookie_banner) is True


def test_should_skip_element_for_cookie_consent_banner() -> None:
    cookie_banner = make_element(
        tag="section",
        text="Cookie preferences",
        attributes={"class": "gdpr-consent"},
        styles={"position": "sticky"},
    )

    assert main.should_skip_element(cookie_banner) is True


def test_compute_component_metrics_sets_expected_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "simulate_color", lambda rgb, _: rgb)

    element = make_element(
        tag="p",
        text="Accessible text",
        styles={
            "color": "rgb(0, 0, 0)",
            "backgroundColor": "rgb(255, 255, 255)",
            "fontSize": "16px",
        },
    )
    record = main.compute_component_metrics(
        site="https://example.com",
        component_index=1,
        component_type="text",
        element_data=element,
    )

    assert record["contrast_normal"] >= 4.5
    assert record["pass_normal"] is True
    assert record["pass_protanopia"] is True
    assert record["pass_deuteranopia"] is True
    assert record["pass_tritanopia"] is True


def test_build_failure_metrics() -> None:
    records = [
        {"pass_normal": True},
        {"pass_normal": False},
        {"pass_normal": False},
    ]
    metrics = main.build_failure_metrics(records, "normal")

    assert metrics["total_components"] == 3
    assert metrics["failed_components"] == 2
    assert metrics["failure_rate"] == pytest.approx(0.6667, rel=1e-4)


def test_build_analysis_summary_aggregates_counts_and_rates() -> None:
    site_results = [
        {
            "site": "https://a.com",
            "total_elements_scanned": 100,
            "other_percentage": 5.0,
            "category_counts": {"button": 1, "link": 1},
            "components": [
                {
                    "component_type": "button",
                    "pass_normal": False,
                    "pass_protanopia": False,
                    "pass_deuteranopia": True,
                    "pass_tritanopia": True,
                    "contrast_normal": 3.0,
                    "contrast_protanopia": 2.9,
                    "contrast_deuteranopia": 3.1,
                    "contrast_tritanopia": 3.2,
                    "contrast_loss_protanopia": 0.1,
                    "contrast_loss_deuteranopia": -0.1,
                    "contrast_loss_tritanopia": -0.2,
                },
                {
                    "component_type": "link",
                    "pass_normal": True,
                    "pass_protanopia": True,
                    "pass_deuteranopia": True,
                    "pass_tritanopia": True,
                    "contrast_normal": 7.0,
                    "contrast_protanopia": 6.9,
                    "contrast_deuteranopia": 6.8,
                    "contrast_tritanopia": 6.7,
                    "contrast_loss_protanopia": 0.1,
                    "contrast_loss_deuteranopia": 0.2,
                    "contrast_loss_tritanopia": 0.3,
                },
            ],
        },
        {
            "site": "https://b.com",
            "total_elements_scanned": 120,
            "other_percentage": 0.0,
            "category_counts": {"text": 1},
            "components": [
                {
                    "component_type": "text",
                    "pass_normal": True,
                    "pass_protanopia": True,
                    "pass_deuteranopia": False,
                    "pass_tritanopia": False,
                    "contrast_normal": 5.0,
                    "contrast_protanopia": 5.1,
                    "contrast_deuteranopia": 2.5,
                    "contrast_tritanopia": 2.4,
                    "contrast_loss_protanopia": -0.1,
                    "contrast_loss_deuteranopia": 2.5,
                    "contrast_loss_tritanopia": 2.6,
                }
            ],
        },
    ]

    summary = main.build_analysis_summary(site_results)

    assert summary["total_sites_scanned"] == 2
    assert summary["total_components"] == 3
    assert summary["counts_by_component_type"]["button"] == 1
    assert summary["counts_by_component_type"]["link"] == 1
    assert summary["counts_by_component_type"]["text"] == 1

    assert summary["overall_failure_rate"]["normal"]["failed_components"] == 1
    assert summary["overall_failure_rate"]["normal"]["failure_rate"] == pytest.approx(0.3333, rel=1e-4)


def test_write_json_file_creates_parent_and_serializes(tmp_path) -> None:
    target = tmp_path / "nested" / "sample.json"
    payload = {"ok": True, "count": 2}

    main.write_json_file(target, payload)

    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == payload
