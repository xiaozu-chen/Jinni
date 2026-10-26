import pytest

pytest.importorskip("ddgs")

from tools import search


def fake_ddgs(results=None, error=None):
    class Fake:
        def __init__(self, **kwargs):
            pass

        def text(self, query, **kwargs):
            if error:
                raise error
            return results

    return Fake


def test_search_formats_results(monkeypatch):
    results = [{"title": "Python", "href": "https://python.org", "body": "The language"}]
    monkeypatch.setattr(search, "DDGS", fake_ddgs(results))
    out = search.web_search("python")

    assert "Python" in out
    assert "https://python.org" in out
    assert "untrusted" in out


def test_search_no_results(monkeypatch):
    monkeypatch.setattr(search, "DDGS", fake_ddgs([]))
    assert search.web_search("zzz") == "No results found."


def test_search_failure_is_an_observation(monkeypatch):
    monkeypatch.setattr(search, "DDGS", fake_ddgs(error=RuntimeError("blocked")))
    assert search.web_search("python").startswith("Error")


def test_search_snippets_save_csv_provenance_and_warn_on_chart(workspace, monkeypatch):
    from tools.charts import make_chart
    from tools.provenance import read_csv_provenance

    results = [{
        "title": "Quarterly sales",
        "href": "https://example.com/sales",
        "body": "Q1: $1.2M; Q2: $1.5M",
    }]
    monkeypatch.setattr(search, "DDGS", fake_ddgs(results))

    message = search.search_snippets_for_chart("quarterly sales")

    assert "unverified" in message
    assert "https://example.com/sales" in message
    csv_path = next(workspace.glob("search-snippets-*.csv"))
    record = read_csv_provenance(csv_path)
    assert record is not None
    assert record["kind"] == "snippet"
    assert record["query"] == "quarterly sales"
    assert "1200000.0" in csv_path.read_text(encoding="utf-8")

    chart_result = make_chart(csv_path.name, "label", "value")
    page = next((workspace / "charts").glob("*.html")).read_text(encoding="utf-8")
    assert chart_result.startswith("Saved")
    assert "search snippets for quarterly sales" in page
    assert "numbers unverified" in page
    assert "values came from search snippets" in chart_result

    csv_path.write_text(csv_path.read_text(encoding="utf-8") + "edited,10,,unknown,https://example.com,manual\n", encoding="utf-8")
    make_chart(csv_path.name, "label", "value")
    changed_page = next((workspace / "charts").glob("*.html")).read_text(encoding="utf-8")
    assert "numbers unverified" in changed_page
    assert "date unavailable" in changed_page
