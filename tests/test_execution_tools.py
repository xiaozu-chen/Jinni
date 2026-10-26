import struct
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

import tools.execution as execution
from config import Settings, load_settings
from tools import NEEDS_APPROVAL, TOOL_GROUPS
from tools.sandbox import _is_appcontainer, run_isolated, sandbox_spec


def managed_project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / ".jinni").mkdir(parents=True)
    (root / ".jinni" / "managed-project").write_text("managed\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / "tests").mkdir()
    monkeypatch.setattr(execution.workspace, "WORKSPACE", root)
    return root


def test_run_tests_is_an_approved_project_tool():
    assert TOOL_GROUPS["run_tests"] == "project"
    assert "run_tests" in NEEDS_APPROVAL


def test_managed_project_and_relative_test_path_are_required(tmp_path, monkeypatch):
    root = managed_project(tmp_path, monkeypatch)
    assert execution._checked_target(root, "tests") == root / "tests"
    with pytest.raises(ValueError, match="relative test path"):
        execution._checked_target(root, "../outside")
    (tmp_path / "outside").mkdir()
    with pytest.raises(ValueError, match="inside the project"):
        execution._checked_target(root, "missing")


def test_test_path_refuses_symlinks(tmp_path, monkeypatch):
    root = managed_project(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test.py").write_text("pass\n", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("the current Windows account cannot create symlinks")
    with pytest.raises(ValueError, match="symbolic links"):
        execution._checked_target(root, "linked/test.py")


@pytest.mark.parametrize("timeout", [0, 301, True, 1.5])
def test_execution_timeout_is_bounded(timeout):
    with pytest.raises(ValueError, match="timeout must be an integer"):
        execution._validate_timeout(timeout)


def test_execution_output_is_capped():
    rendered = execution._format_result("pytest", 0, "x" * 70_000, True)
    assert len(rendered) < 64_100
    assert "output truncated" in rendered


def test_sandbox_spec_enables_appcontainer_without_network_capabilities(tmp_path):
    encoded = sandbox_spec([str(tmp_path)], [str(tmp_path.parent)])
    assert encoded[4:8] == b"SBOX"
    table = struct.unpack_from("<I", encoded, 0)[0]
    vtable = table - struct.unpack_from("<i", encoded, table)[0]
    assert encoded[vtable + 4 + 1 * 2] != 0
    capabilities_offset = struct.unpack_from("<H", encoded, vtable + 4 + 6 * 2)[0]
    assert capabilities_offset != 0
    capability_slot = table + capabilities_offset
    capability_string = capability_slot + struct.unpack_from("<I", encoded, capability_slot)[0]
    assert struct.unpack_from("<I", encoded, capability_string)[0] == 0
    assert encoded[vtable + 4 + 7 * 2] != 0
    assert encoded[vtable + 4 + 8 * 2] != 0
    assert encoded[vtable + 4 + 11 * 2] != 0


def test_project_test_snapshot_has_file_and_size_limits(tmp_path, monkeypatch):
    root = managed_project(tmp_path, monkeypatch)
    (root / "venv").mkdir()
    (root / "venv" / "ignored.py").write_text("ignored\n", encoding="utf-8")
    execution._validate_project_for_tests(root)
    (root / "source.py").write_text("code\n", encoding="utf-8")
    monkeypatch.setattr(execution, "MAX_PROJECT_FILES", 0)
    with pytest.raises(ValueError, match="10,000 files or 200 MB"):
        execution._validate_project_for_tests(root)


def test_windows_appcontainer_blocks_outside_files_and_network(tmp_path):
    if os.name != "nt" or _is_appcontainer():
        pytest.skip("requires a normal Windows host process to launch AppContainer")
    secret = tmp_path.parent / "jinni-sandbox-secret.txt"
    secret.write_text("secret", encoding="utf-8")
    allowed = tmp_path / "allowed.txt"
    output = tmp_path / "probe.txt"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    code = '''
import pathlib, socket, sys
rows = []
pathlib.Path(sys.argv[1]).write_text("allowed")
try:
    pathlib.Path(sys.argv[2]).read_text()
    rows.append("outside=read")
except Exception:
    rows.append("outside=blocked")
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[3])), timeout=1)
    rows.append("network=connected")
except Exception:
    rows.append("network=blocked")
pathlib.Path(sys.argv[4]).write_text("\\n".join(rows))
'''
    try:
        result = run_isolated(
            sys.executable,
            ["-I", "-c", code, str(allowed), str(secret), str(listener.getsockname()[1]), str(output)],
            tmp_path, tmp_path, 10, output,
            [sys.prefix, sys.base_prefix, os.environ.get("SystemRoot", r"C:\Windows")],
        )
        assert result[0] == 0
        assert allowed.read_text(encoding="utf-8") == "allowed"
        assert "outside=blocked" in result[1]
        assert "network=blocked" in result[1]
    finally:
        listener.close()
        secret.unlink(missing_ok=True)


def test_powershell_is_off_by_default_and_can_be_enabled_in_toml(tmp_path):
    assert Settings().powershell_enabled is False
    config = tmp_path / "settings.toml"
    config.write_text("powershell_enabled = true\n", encoding="utf-8")
    assert load_settings(config).powershell_enabled is True


def test_settings_reject_non_boolean_powershell_flag(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text('powershell_enabled = "yes"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="powershell_enabled must be true or false"):
        load_settings(config)
