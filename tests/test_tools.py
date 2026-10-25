import sys
import httpx

import pytest

from tools import NEEDS_APPROVAL, TOOL_FUNCTIONS, TOOL_SCHEMAS
from tools import web
from tools.basic import calculate
from tools.files import MAX_READ, edit_file, list_files, read_file, write_file
from tools.web import check_public_url, fetch_table, fetch_url, host_scope
from tools.provenance import read_csv_provenance
from tools.workspace import safe_path

@pytest.mark.parametrize("path", ["poem.txt", "notes/poem.txt", "notes/../mm.txt", "."])
def test_safe_path_allows_inside(workspace, path):
    assert safe_path(path).is_relative_to(workspace)


@pytest.mark.parametrize("path", ["../jinni.py", "notes/../../jinni.py", "../../etc/passwd"])
def test_safe_path_blocks_escape(workspace, path):
    with pytest.raises(ValueError):
        safe_path(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-style paths")
@pytest.mark.parametrize("path", ["..\\jinni.py", "C:/Windows/win.ini", "C:\\Windows\\win.ini"])
def test_safe_path_blocks_windows_escape(workspace, path):
    with pytest.raises(ValueError):
        safe_path(path)


def test_write_then_read(workspace):
    assert "Wrote" in write_file("notes/a.txt", "hello")
    assert read_file("notes/a.txt") == "hello"
    assert (workspace / "notes" / "a.txt").exists()


def test_write_outside_is_refused(workspace):
    result = write_file("../evil.txt", "x")
    assert result.startswith("Error")
    assert not (workspace.parent / "evil.txt").exists()


def test_missing_file_error_is_clean(workspace):
    result = read_file("nope.txt")
    assert result.startswith("Error")
    assert str(workspace) not in result


def test_read_is_capped(workspace):
    (workspace / "big.txt").write_text("a" * 10000, encoding="utf-8")
    assert len(read_file("big.txt")) == MAX_READ


def test_list_empty_folder(workspace):
    assert list_files(".") == "(empty folder)"

def test_every_schema_has_a_function():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == set(TOOL_FUNCTIONS)
    assert NEEDS_APPROVAL <= names


def test_edit_replaces_once(workspace):
    (workspace / "a.txt").write_text("buy milk and eggs", encoding="utf-8")
    assert "Edited" in edit_file("a.txt", "milk", "oat milk")
    assert read_file("a.txt") == "buy oat milk and eggs"


def test_edit_missing_text(workspace):
    (workspace / "a.txt").write_text("hello", encoding="utf-8")
    assert edit_file("a.txt", "nope", "x").startswith("Error")
    assert read_file("a.txt") == "hello"


def test_edit_ambiguous_text_changes_nothing(workspace):
    (workspace / "a.txt").write_text("cat cat", encoding="utf-8")
    assert "2 times" in edit_file("a.txt", "cat", "dog")
    assert read_file("a.txt") == "cat cat"


def test_edit_empty_old_text(workspace):
    (workspace / "a.txt").write_text("hello", encoding="utf-8")
    assert edit_file("a.txt", "", "x").startswith("Error")


@pytest.mark.parametrize("expr,answer", [
    ("2+3*4", "14"), ("17*23", "391"), ("2**10", "1024"), ("10/4", "2.5"),
])
def test_calculate_works(expr, answer):
    assert calculate(expr) == answer


@pytest.mark.parametrize("expr", [
    "__import__('os').system('dir')", "9**9**9", "1/0", "abs(-1)",
])
def test_calculate_refuses_bad_input(expr):
    assert calculate(expr).startswith("Error")


@pytest.mark.parametrize("url", [
    "http://localhost:8080", "http://127.0.0.1", "http://192.168.1.1",
    "http://169.254.169.254", "file:///etc/passwd", "ftp://example.com",
])
def test_url_check_blocks_private_and_odd(url):
    with pytest.raises(ValueError):
        check_public_url(url)


def test_url_check_allows_public_ip():
    check_public_url("http://8.8.8.8")


def test_fetch_refuses_localhost():
    assert fetch_url("http://localhost:8080").startswith("Error")


def test_fetch_extracts_text(monkeypatch):
    page = "<html><head><title>t</title></head><body><script>bad()</script><p>Hello</p></body></html>"

    def fake_get(url, **kwargs):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, text=page,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web.httpx, "get", fake_get)
    monkeypatch.setattr(web, "check_public_url", lambda url: None)

    result = fetch_url("https://example.com")
    assert "Hello" in result
    assert "bad()" not in result
    assert "untrusted" in result


def test_fetch_table_saves_csv_and_hash_provenance(workspace, monkeypatch):
    page = """<table><tr><th>Month</th><th>Sales</th></tr>
        <tr><td>Jan</td><td>10</td></tr><tr><td>Feb</td><td>15</td></tr></table>"""
    monkeypatch.setattr(web, "_fetch_html", lambda url: page)

    result = fetch_table("https://example.com/reports/sales")

    csv_path = workspace / "example-com-sales.csv"
    assert "Saved table 0" in result
    assert csv_path.read_text(encoding="utf-8") == "Month,Sales\nJan,10\nFeb,15\n"
    record = read_csv_provenance(csv_path)
    assert record["source_url"] == "https://example.com/reports/sales"
    assert record["fetched_at"].startswith("20")
    assert len(record["sha256"]) == 64


def test_fetched_chart_displays_persisted_source_after_restart(workspace, monkeypatch):
    page = "<table><tr><th>Month</th><th>Sales</th></tr><tr><td>Jan</td><td>10</td></tr></table>"
    monkeypatch.setattr(web, "_fetch_html", lambda url: page)
    result = fetch_table("https://example.com/reports/sales")
    assert "unverified" not in result

    from tools.charts import make_chart
    chart_result = make_chart("example-com-sales.csv", "Month", "Sales")
    chart_page = (workspace / "charts" / "example-com-sales-sales-bar.html").read_text(encoding="utf-8")

    assert "https://example.com/reports/sales, fetched 20" in chart_page
    assert "typed by Jinni" not in chart_page
    assert chart_result.startswith("Saved")


def test_fetch_table_selects_a_zero_based_table_and_rejects_duplicates():
    html = "<table><tr><th>a</th></tr><tr><td>1</td></tr></table><table><tr><th>b</th></tr><tr><td>2</td></tr></table>"
    assert web._table_csv(html, 1) == b"b\r\n2\r\n"
    with pytest.raises(ValueError, match="unique"):
        web._table_csv("<table><tr><th>x</th><th>x</th></tr><tr><td>1</td><td>2</td></tr></table>", 0)


def test_fetch_table_blocks_cross_site_redirects(monkeypatch):
    class Response:
        is_redirect = True
        headers = {"location": "https://evil.example/table"}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            class Context:
                def __enter__(self):
                    return Response()

                def __exit__(self, *args):
                    return False

            return Context()

    monkeypatch.setattr(web.httpx, "Client", Client)
    monkeypatch.setattr(web, "check_public_url", lambda url: None)
    with pytest.raises(ValueError, match="different site"):
        web._fetch_html("https://good.example/table")


@pytest.mark.parametrize("url,expected", [
    ("https://www.Mayoclinic.org/a", "mayoclinic.org"),
    ("https://mayoclinic.org./a", "mayoclinic.org"),
    ("https://good.example@evil.example/", "evil.example"),
    ("https://user.github.io/x", "user.github.io"),
    ("not a url", ""),
    ("http://[bad", ""),
])
def test_host_scope(url, expected):
    assert host_scope({"url": url}) == expected


def test_cross_site_redirect_is_not_followed(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(
            302, headers={"location": "https://evil.example/steal"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web.httpx, "get", fake_get)
    monkeypatch.setattr(web, "check_public_url", lambda url: None)

    result = fetch_url("https://good.example/page")

    assert result.startswith("Error")
    assert "evil.example" in result
    assert calls == ["https://good.example/page"]


def test_same_site_redirect_is_followed(monkeypatch):
    def fake_get(url, **kwargs):
        if "www." not in url:
            return httpx.Response(
                301, headers={"location": "https://www.good.example/page"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, text="hello",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(web.httpx, "get", fake_get)
    monkeypatch.setattr(web, "check_public_url", lambda url: None)

    assert "hello" in fetch_url("https://good.example/page")
