import pytest

pytest.importorskip("ddgs")

from tools import _search


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
    monkeypatch.setattr(_search, "DDGS", fake_ddgs(results))
    out = _search.web_search("python")

    assert "Python" in out
    assert "https://python.org" in out
    assert "untrusted" in out


def test_search_no_results(monkeypatch):
    monkeypatch.setattr(_search, "DDGS", fake_ddgs([]))
    assert _search.web_search("zzz") == "No results found."


def test_search_failure_is_an_observation(monkeypatch):
    monkeypatch.setattr(_search, "DDGS", fake_ddgs(error=RuntimeError("blocked")))
    assert _search.web_search("python").startswith("Error")