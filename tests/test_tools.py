import sys

import pytest

from tools import MAX_READ, list_files, read_file, safe_path, write_file


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