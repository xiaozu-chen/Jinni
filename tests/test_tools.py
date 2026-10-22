import sys
import httpx

import pytest

from tools import NEEDS_APPROVAL, TOOL_FUNCTIONS, TOOL_SCHEMAS
from tools import web
from tools.basic import calculate
from tools.files import MAX_READ, edit_file, list_files, read_file, write_file
from tools.web import check_public_url, fetch_url
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