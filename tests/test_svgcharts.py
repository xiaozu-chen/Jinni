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


def slices(root):
    return root.findall(f".//{SVG}path")


def rects_with(root, name):
    return [r for r in root.findall(f".//{SVG}rect") if name in r.get("class", "").split()]


def test_grouped_bars_have_one_bar_per_value_per_series():
    root = parse(svgcharts.bar_chart(["a", "b"], {"x": [1, 2], "y": [3, 4]}, "T", "k", "v"))
    assert len(rects_with(root, "bar")) == 4


def test_multi_series_gets_a_legend_and_a_line_each():
    root = parse(svgcharts.line_chart(["a", "b"], {"x": [1, 2], "y": [3, 4]}, "T", "k", "v"))
    assert [r.get("class") for r in rects_with(root, "swatch")] == ["swatch s0", "swatch s1"]
    assert len(root.findall(f".//{SVG}polyline")) == 2


def test_single_series_has_no_legend():
    root = parse(svgcharts.bar_chart(["a"], {"x": [1]}, "T", "k", "v"))
    assert rects_with(root, "swatch") == []


def test_too_many_series_are_rejected():
    series = {f"s{i}": [1, 2] for i in range(9)}
    with pytest.raises(ValueError):
        svgcharts.bar_chart(["a", "b"], series, "T", "k", "v")


def test_series_length_mismatch_is_rejected():
    with pytest.raises(ValueError):
        svgcharts.line_chart(["a", "b"], {"x": [1, 2], "y": [1]}, "T", "k", "v")


def test_stacked_bars_stack_each_series_from_the_prior_total():
    root = parse(svgcharts.stacked_bar_chart(["a", "b"], {"x": [2, -1], "y": [3, -4]}, "T", "k", "v"))
    bars = rects_with(root, "bar")
    assert len(bars) == 4
    assert [b.find(f"{SVG}title").text for b in bars] == [
        "a · x: 2", "b · x: -1", "a · y: 3", "b · y: -4",
    ]


def test_secondary_line_series_uses_a_right_axis():
    root = parse(svgcharts.line_chart(
        ["a", "b"], {"temperature": [10, 20]}, "T", "day", "°C", {"rain": [100, 200]}
    ))
    assert len(root.findall(f".//{SVG}polyline")) == 2
    assert any(line.get("x1") == "560" and line.get("x2") == "560" for line in root.findall(f".//{SVG}line"))
    assert "rain" in [text.text for text in root.findall(f".//{SVG}text")]


def test_donut_chart_has_a_theme_colored_hole():
    root = parse(svgcharts.donut_chart(["a", "b", "c"], [5, 3, 2], "T"))
    holes = [circle for circle in root.findall(f".//{SVG}circle") if "hole" in circle.get("class", "")]
    assert len(holes) == 1
    assert ".hole { fill: var(--bg); }" in svgcharts.html_page("T", "S", svgcharts.donut_chart(["a", "b"], [1, 2], "T"))


def test_narrow_bars_use_compact_value_labels():
    svg = svgcharts.bar_chart([str(i) for i in range(12)], [1_450_000] * 12, "T", "x", "y")
    assert '<text class="value"' in svg
    assert ">1.45M</text>" in svg


def test_series_palette_uses_okabe_ito_colors():
    expected = ("#0072b2", "#e69f00", "#009e73", "#d55e00", "#cc79a7", "#56b4e9", "#f0e442", "#000000")
    assert all(color in svgcharts.LIGHT_VARS for color in expected)


def test_a_long_legend_wraps_onto_more_rows():
    names = {f"a fairly long series name {i}": [1, 2] for i in range(6)}
    root = parse(svgcharts.bar_chart(["a", "b"], names, "T", "k", "v"))
    rows = {t.get("y") for t in root.findall(f".//{SVG}text") if t.get("class") == "legend"}
    assert len(rows) > 1


def test_pie_has_one_slice_per_positive_value():
    assert len(slices(parse(svgcharts.pie_chart(["a", "b", "c"], [5, 3, 2], "T")))) == 3


def test_pie_drops_zero_values():
    assert len(slices(parse(svgcharts.pie_chart(["a", "b", "c"], [5, 0, 2], "T")))) == 2


def test_single_slice_pie_is_a_full_circle():
    root = parse(svgcharts.pie_chart(["a", "b"], [5, 0], "T"))
    assert len(root.findall(f".//{SVG}circle")) == 1
    assert slices(root) == []


def test_pie_groups_the_tail_into_other():
    labels = [f"c{i}" for i in range(12)]
    root = parse(svgcharts.pie_chart(labels, list(range(12, 0, -1)), "T"))
    legend = [t.text for t in root.findall(f".//{SVG}text") if t.get("class") == "legend"]
    assert len(slices(root)) == 8
    assert "Other" in legend


def test_pie_percentages_add_up():
    root = parse(svgcharts.pie_chart(["a", "b", "c"], [1, 1, 1], "T"))
    pct = [float(t.text.rstrip("%")) for t in root.findall(f".//{SVG}text") if t.get("class") == "legend-value"]
    assert abs(sum(pct) - 100) < 1


def test_slices_over_half_use_the_large_arc_flag():
    root = parse(svgcharts.pie_chart(["big", "small"], [3, 1], "T"))
    big, small = [p.get("d") for p in slices(root)]
    assert " 0 1 1 " in big
    assert " 0 0 1 " in small


@pytest.mark.parametrize("values", [[-1, 2], [0, 0], []])
def test_pie_rejects_bad_numbers(values):
    with pytest.raises(ValueError):
        svgcharts.pie_chart(["a", "b"][: len(values)], values, "T")


def chart_page():
    return svgcharts.html_page("Sales", "Source: s.csv", svgcharts.bar_chart(["a"], [1], "Sales", "x", "y"))


def last_root_rule(page):
    style = page.split("<style>")[1].split("</style>")[0]
    return style.rsplit(":root {", 1)[1].split("}", 1)[0]


SAMPLE_SVGS = {
    "bar": lambda: svgcharts.bar_chart(["a", "b"], [1, 2], "T", "x", "y"),
    "grouped": lambda: svgcharts.bar_chart(["a", "b"], {"p": [1, 2], "q": [3, 4]}, "T", "x", "y"),
    "line": lambda: svgcharts.line_chart(["a", "b"], {"p": [1, 2], "q": [3, 4]}, "T", "x", "y"),
    "pie": lambda: svgcharts.pie_chart(["a", "b", "c"], [3, 2, 1], "T"),
}


@pytest.mark.parametrize("kind", list(SAMPLE_SVGS))
def test_every_chart_kind_passes_the_svg_safety_check(kind):
    assert svgcharts.safe_svg(SAMPLE_SVGS[kind]())


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="http://evil.example/x.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:red"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><text/></a></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><rect/>',
    '<!DOCTYPE svg [<!ENTITY x "y">]><svg xmlns="http://www.w3.org/2000/svg"/>',
    '<div xmlns="http://www.w3.org/1999/xhtml"/>',
    "not xml at all",
])
def test_unsafe_svg_is_rejected(svg):
    assert not svgcharts.safe_svg(svg)


def test_parse_page_round_trips_special_characters():
    svg = svgcharts.bar_chart(["a"], [1], "T", "x", "y")
    title, subtitle = "A <b> & 'q' \"d\" $5", "from <file> & more"
    assert svgcharts.parse_page(svgcharts.html_page(title, subtitle, svg)) == (title, subtitle, svg)


def test_parse_page_rejects_other_html():
    assert svgcharts.parse_page("<html><body>hello</body></html>") is None


def test_generated_pages_are_genuine_and_edited_ones_are_not():
    page = chart_page()
    assert svgcharts.is_genuine_page(page)
    assert not svgcharts.is_genuine_page(page.replace("</main>", "<script>alert(1)</script></main>"))
    assert not svgcharts.is_genuine_page("<html><body>hello</body></html>")


def test_export_forces_the_requested_theme():
    assert svgcharts.LIGHT_VARS in last_root_rule(svgcharts.export_page(chart_page(), "light"))
    assert svgcharts.DARK_VARS in last_root_rule(svgcharts.export_page(chart_page(), "dark"))


def test_export_adds_the_fill_the_window_layout():
    assert "export layout" in svgcharts.export_page(chart_page(), "light")
    assert "export layout" not in chart_page()


def test_export_keeps_title_subtitle_and_chart():
    exported = svgcharts.export_page(chart_page(), "light")
    assert svgcharts.parse_page(exported) == svgcharts.parse_page(chart_page())


def test_export_keeps_the_script_blocking_policy_first():
    page = svgcharts.export_page(chart_page(), "dark")
    assert "default-src 'none'" in page
    assert page.index("Content-Security-Policy") < page.index("<style>") < page.index("<svg")


def test_export_refuses_non_charts_and_tampered_charts():
    with pytest.raises(ValueError):
        svgcharts.export_page("<html><body>hi</body></html>")
    evil = svgcharts.html_page("T", "S", '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>')
    with pytest.raises(ValueError):
        svgcharts.export_page(evil)


def test_export_rejects_unknown_themes():
    with pytest.raises(ValueError):
        svgcharts.export_page(chart_page(), "sepia")


def test_pages_define_a_default_series_color():
    assert "--c: var(--c0)" in chart_page()
