import csv
import io

from presentation.search_snippet_data import extract_points, points_csv


def test_extracts_explicit_label_value_pairs_and_normalizes_units():
    points = extract_points([{
        "title": "Quarterly sales",
        "href": "https://example.com/sales",
        "body": "Q1: $1.2M; Q2: $1.5M",
    }], "quarterly sales")

    assert [(point.label, point.value, point.unit) for point in points] == [
        ("Q1", "1200000.0", "USD"),
        ("Q2", "1500000.0", "USD"),
    ]
    rows = list(csv.DictReader(io.StringIO(points_csv(points).decode("utf-8"))))
    assert rows[0]["source_url"] == "https://example.com/sales"
    assert rows[0]["snippet"] == "Q1: $1.2M; Q2: $1.5M"


def test_single_value_fallback_ignores_year_and_keeps_source_title():
    points = extract_points([{
        "title": "Company revenue grew",
        "href": "https://example.com/report",
        "body": "Revenue reached $2.4 billion in 2025.",
    }], "company revenue")

    assert len(points) == 1
    assert points[0].label == "Company revenue grew"
    assert points[0].value == "2400000000.0"
    assert points[0].unit == "USD"


def test_ambiguous_values_and_unsafe_sources_are_skipped():
    results = [
        {"title": "Several figures", "href": "https://example.com", "body": "Revenue 12 and 15."},
        {"title": "Unsafe", "href": "javascript:alert(1)", "body": "Q1: 12"},
    ]

    assert extract_points(results, "revenue") == []


def test_csv_escapes_formula_like_source_text():
    points = extract_points([{
        "title": "=HYPERLINK(\"https://bad.example\")",
        "href": "https://example.com/report",
        "body": "Revenue reached $12",
    }], "revenue")

    rows = list(csv.DictReader(io.StringIO(points_csv(points).decode("utf-8"))))
    assert rows[0]["source_title"].startswith("'=")

