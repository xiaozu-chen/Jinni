import xml.etree.ElementTree as ET

import pytest

import svgcharts

SVG = "{http://www.w3.org/2000/svg}"


def parse(markup: str) -> ET.Element:
    return ET.fromstring(markup)


@pytest.mark.parametrize("low,high", [(0, 100), (0, 1), (-5, 3), (0, 0), (5, 5), (0.001, 0.009), (0, 123456)])
def test_nice_ticks_cover_the_range(low, high):
    ticks = svgcharts.nice_ticks(low, high)
    assert ticks == sorted(ticks)
    assert ticks[0] <= low
    assert ticks[-1] >= high
    assert 2 <= len(ticks) <= 8


@pytest.mark.parametrize("value,expected", [
    (0, "0"), (5.0, "5"), (1234.5, "1,234.5"), (-2.5, "-2.5"), (0.004, "0.004"), (1000000, "1,000,000"),
])
def test_fmt(value, expected):
    assert svgcharts.fmt(value) == expected


def test_bar_chart_has_one_bar_per_value():
    root = parse(svgcharts.bar_chart(["a", "b", "c"], [1, 5, 3], "T", "x", "y"))
    assert len(root.findall(f".//{SVG}rect")) == 3


def test_line_chart_has_one_line_and_one_dot_per_value():
    root = parse(svgcharts.line_chart(["a", "b", "c"], [1, 5, 3], "T", "x", "y"))
    assert len(root.findall(f".//{SVG}polyline")) == 1
    assert len(root.findall(f".//{SVG}circle")) == 3


def test_negative_values_give_valid_bars():
    root = parse(svgcharts.bar_chart(["a", "b"], [-4, 6], "T", "x", "y"))
    for rect in root.findall(f".//{SVG}rect"):
        assert float(rect.get("height")) >= 0


def test_flat_data_still_renders():
    parse(svgcharts.bar_chart(["a", "b"], [0, 0], "T", "x", "y"))
    parse(svgcharts.line_chart(["a", "b", "c"], [5, 5, 5], "T", "x", "y"))


def test_user_text_is_escaped():
    evil = "<script>alert(1)</script>"
    svg = svgcharts.bar_chart([evil], [1], evil, evil, evil)
    page = svgcharts.html_page(evil, evil, svg)
    parse(svg)
    assert "<script" not in page


def test_page_blocks_scripts_and_network():
    page = svgcharts.html_page("T", "S", "<svg></svg>")
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page


def test_dollar_signs_in_titles_survive():
    assert "Cost in $" in svgcharts.html_page("Cost in $", "$5 total", "<svg></svg>")


def test_many_labels_are_rotated():
    labels = [f"label {i}" for i in range(12)]
    svg = svgcharts.bar_chart(labels, list(range(12)), "T", "x", "y")
    assert "rotate(-40" in svg


def test_bad_input_is_rejected():
    with pytest.raises(ValueError):
        svgcharts.bar_chart([], [], "T", "x", "y")
    with pytest.raises(ValueError):
        svgcharts.bar_chart(["a"], [1, 2], "T", "x", "y")


@pytest.mark.parametrize("value,expected", [
    (0, "0"), (999, "999"), (1000, "1K"), (1500, "1.5K"), (25_000, "25K"),
    (1_450_000, "1.45M"), (1_500_000_000, "1.5B"), (-2_000_000, "-2M"),
    (2_000_000_000_000, "2T"), (0.004, "0.004"),
])
def test_compact(value, expected):
    assert svgcharts.compact(value) == expected


def test_big_numbers_get_short_axis_labels():
    root = parse(svgcharts.bar_chart(["a", "b"], [1_450_935_791, 233_740_000], "T", "x", "y"))
    ticks = [t.text for t in root.findall(f".//{SVG}text") if t.get("class") == "tick"]
    assert ticks
    assert all(len(t) <= 6 for t in ticks)