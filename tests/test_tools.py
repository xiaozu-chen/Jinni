import sys
import httpx

import pytest

from tools import NEEDS_APPROVAL, TOOL_FUNCTIONS, TOOL_SCHEMAS
from tools import web
from tools.basic import calculate
from tools.files import (MAX_READ, apply_patch, code_outline, delete_file, edit_file, find_files,
                         list_files, project_tree, read_file, search_files, write_file)
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


def test_read_file_returns_numbered_line_ranges(workspace):
    (workspace / "lines.txt").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    assert read_file("lines.txt", start=2, end=3) == "2: two\n3: three\n"
    assert read_file("lines.txt", start=0, end=3).startswith("Error:")


def test_read_file_caps_range_size(workspace):
    (workspace / "lines.txt").write_text("line\n" * 250, encoding="utf-8")

    assert "at most 200 lines" in read_file("lines.txt", start=1, end=201)


def test_search_files_returns_file_line_and_snippet(workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "sample.py").write_text("first\nneedle here\n", encoding="utf-8")

    assert search_files("needle") == "src/sample.py:2: needle here"
    assert "src/sample.py:2" in search_files("needl.", regex=True)


def test_search_files_rejects_complex_patterns_and_limits_scope(workspace):
    (workspace / "sample.txt").write_text("needle", encoding="utf-8")

    assert "too complex" in search_files("(a+)+$", regex=True)
    assert "too complex" in search_files("a{100000}", regex=True)
    assert search_files("needle", path="missing").startswith("Error:")


def test_find_files_matches_globs_and_blocks_parent_patterns(workspace):
    (workspace / "src").mkdir()
    (workspace / "src" / "sample.py").write_text("pass", encoding="utf-8")
    (workspace / "readme.md").write_text("readme", encoding="utf-8")

    assert find_files("**/*.py") == "src/sample.py"
    assert find_files("../*.py").startswith("Error:")


def test_code_outline_lists_definitions_and_reports_syntax_errors(workspace):
    (workspace / "module.py").write_text("class Cat:\n    def purr(self): pass\n", encoding="utf-8")
    (workspace / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    outline = code_outline("module.py")
    assert "1: class Cat" in outline
    assert "2: function purr" in outline
    assert "syntax error on line 1" in code_outline("broken.py")


def test_project_tree_respects_depth_and_entry_caps(workspace):
    (workspace / "one").mkdir()
    (workspace / "one" / "two").mkdir()
    (workspace / "one" / "two" / "leaf.txt").write_text("leaf", encoding="utf-8")
    (workspace / "root.txt").write_text("root", encoding="utf-8")

    tree = project_tree(max_depth=1)
    assert "one/" in tree and "root.txt" in tree
    assert "two/" not in tree
    assert "output capped" in project_tree(max_entries=1)


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


def test_apply_patch_replaces_multiple_exact_ranges(workspace):
    (workspace / "a.txt").write_text("one\nmiddle\nthree\n", encoding="utf-8")

    result = apply_patch("a.txt", [
        {"old_text": "one", "new_text": "1"},
        {"old_text": "three", "new_text": "3"},
    ])

    assert result == "Applied 2 patch(es) to a.txt."
    assert read_file("a.txt") == "1\nmiddle\n3\n"


def test_apply_patch_is_all_or_nothing(workspace):
    (workspace / "a.txt").write_text("one middle three", encoding="utf-8")
    patches = [
        {"old_text": "one", "new_text": "1"},
        {"old_text": "missing", "new_text": "2"},
    ]

    assert apply_patch("a.txt", patches).startswith("Error:")
    assert read_file("a.txt") == "one middle three"


def test_apply_patch_rejects_overlapping_source_ranges(workspace):
    (workspace / "a.txt").write_text("one middle three", encoding="utf-8")

    result = apply_patch("a.txt", [
        {"old_text": "one middle", "new_text": "first"},
        {"old_text": "middle", "new_text": "second"},
    ])

    assert "overlap" in result
    assert read_file("a.txt") == "one middle three"


def test_edit_empty_old_text(workspace):
    (workspace / "a.txt").write_text("hello", encoding="utf-8")
    assert edit_file("a.txt", "", "x").startswith("Error")


def test_delete_file_moves_file_into_reversible_trash(workspace):
    (workspace / "notes").mkdir()
    (workspace / "notes" / "keep.txt").write_text("still here", encoding="utf-8")

    result = delete_file("notes/keep.txt")

    assert "Moved notes/keep.txt to .trash/notes/keep.txt" in result
    assert not (workspace / "notes" / "keep.txt").exists()
    assert (workspace / ".trash" / "notes" / "keep.txt").read_text(encoding="utf-8") == "still here"


def test_delete_file_refuses_directories_and_trash_contents(workspace):
    (workspace / "folder").mkdir()
    (workspace / ".trash").mkdir()
    (workspace / ".trash" / "old.txt").write_text("parked", encoding="utf-8")

    assert delete_file("folder").startswith("Error:")
    assert delete_file(".trash/old.txt").startswith("Error:")


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
    assert check_public_url("http://8.8.8.8") == ["8.8.8.8"]


def test_url_check_rejects_a_mixed_public_and_private_dns_answer(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("8.8.8.8", 443)),
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ])

    with pytest.raises(ValueError, match="private or local"):
        check_public_url("https://rebound.example")


def test_pinned_target_preserves_http_host_and_tls_name():
    target, headers, extensions = web._pinned_target(
        "https://example.com:8443/path?q=1", ["8.8.8.8"]
    )

    assert target == "https://8.8.8.8:8443/path?q=1"
    assert headers == {"Host": "example.com:8443"}
    assert extensions == {"sni_hostname": "example.com"}


def test_fetch_refuses_localhost():
    assert fetch_url("http://localhost:8080").startswith("Error")


def test_unexpected_fetch_error_is_logged_with_traceback(monkeypatch, caplog):
    def broken_fetch(_url):
        raise RuntimeError("fixture defect")

    monkeypatch.setattr(web, "_fetch_page", broken_fetch)

    assert fetch_url("https://example.com").startswith("Error:")
    assert any(
        record.name == "jinni.tools.web" and record.exc_info
        and record.exc_info[0] is RuntimeError
        for record in caplog.records
    )


def test_fetch_extracts_text(monkeypatch):
    page = "<html><head><title>t</title></head><body><script>bad()</script><p>Hello</p></body></html>"

    monkeypatch.setattr(web, "_fetch_page", lambda url: ("text/html", page))
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

        def stream(self, method, url, **kwargs):
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
    ("https://docs.shop.example.co.uk/x", "example.co.uk"),
    ("not a url", ""),
    ("http://[bad", ""),
])
def test_host_scope(url, expected):
    assert host_scope({"url": url}) == expected


def test_cross_site_redirect_is_not_followed(monkeypatch):
    calls = []
    response = httpx.Response(
        302, headers={"location": "https://evil.example/steal"},
        request=httpx.Request("GET", "https://good.example/page"),
    )
    monkeypatch.setattr(web.httpx, "Client", _web_client([response], calls))
    monkeypatch.setattr(web, "check_public_url", lambda url: None)

    result = fetch_url("https://good.example/page")

    assert result.startswith("Error")
    assert "different site" in result
    assert calls == ["https://good.example/page"]


def test_same_site_redirect_is_followed(monkeypatch):
    responses = [
        httpx.Response(
            301, headers={"location": "https://www.good.example/page"},
            request=httpx.Request("GET", "https://good.example/page"),
        ),
        httpx.Response(
            200, headers={"content-type": "text/plain"}, text="hello",
            request=httpx.Request("GET", "https://www.good.example/page"),
        ),
    ]
    calls = []
    monkeypatch.setattr(web.httpx, "Client", _web_client(responses, calls))
    monkeypatch.setattr(web, "check_public_url", lambda url: None)

    assert "hello" in fetch_url("https://good.example/page")
    assert calls == ["https://good.example/page", "https://www.good.example/page"]


def _web_client(responses, calls=None):
    calls = [] if calls is None else calls

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            calls.append(url)
            response = responses.pop(0)

            class Stream:
                def __enter__(self):
                    return response

                def __exit__(self, *args):
                    response.close()
                    return False

            return Stream()

    return Client


def test_fetch_url_enforces_download_cap_and_warns_on_large_context(monkeypatch):
    response = httpx.Response(
        200, headers={"content-type": "text/plain"}, content=b"x" * (web.MAX_FETCH_BYTES + 1),
        request=httpx.Request("GET", "https://example.com"),
    )
    monkeypatch.setattr(web.httpx, "Client", _web_client([response]))
    monkeypatch.setattr(web, "check_public_url", lambda url: None)
    assert "too large" in fetch_url("https://example.com")

    monkeypatch.setattr(web, "_fetch_page", lambda url: ("text/plain", "x" * web.MAX_FETCH))
    result = fetch_url("https://example.com")
    assert "large result" in result
