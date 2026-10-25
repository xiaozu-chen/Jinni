import json
import subprocess
from types import SimpleNamespace

from tools import static_checks
from tools.static_checks import check_python


def test_py_compile_checks_without_creating_bytecode(workspace):
    (workspace / "good.py").write_text("answer = 42\n", encoding="utf-8")
    (workspace / "bad.py").write_text("def broken(:\n", encoding="utf-8")

    assert "syntax OK" in check_python("good.py")
    assert "syntax error on line 1" in check_python("bad.py")
    assert not list(workspace.rglob("*.pyc"))


def test_static_checkers_restrict_paths_and_checker_names(workspace):
    assert check_python("../jinni.py").startswith("Error:")
    assert check_python("notes.txt").startswith("Error:")
    assert check_python("x.py", "powershell").startswith("Error:")


def test_ruff_runs_fixed_read_only_command_in_workspace(workspace, monkeypatch):
    (workspace / "sample.py").write_text("pass\n", encoding="utf-8")
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=1, stdout="sample.py:1:1: F401 unused", stderr="")

    monkeypatch.setattr(static_checks.shutil, "which", lambda name: "C:/tools/ruff.exe")
    monkeypatch.setattr(static_checks.subprocess, "run", fake_run)

    result = check_python("sample.py", "ruff")

    assert "F401" in result
    assert seen["command"] == ["C:/tools/ruff.exe", "check", "--no-cache", "--output-format", "concise", "sample.py"]
    assert seen["kwargs"]["cwd"] == workspace
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["timeout"] == static_checks.CHECK_TIMEOUT_SECONDS


def test_pyright_summarizes_json_diagnostics(workspace, monkeypatch):
    (workspace / "sample.py").write_text("answer = 42\n", encoding="utf-8")
    report = {
        "summary": {"errorCount": 1, "warningCount": 2, "informationCount": 0},
        "generalDiagnostics": [{
            "severity": "error", "message": "type mismatch",
            "range": {"start": {"line": 4, "character": 0}},
        }],
    }
    monkeypatch.setattr(static_checks.shutil, "which", lambda name: "C:/tools/pyright.exe")
    monkeypatch.setattr(
        static_checks.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=json.dumps(report), stderr=""),
    )

    result = check_python("sample.py", "pyright")

    assert "1 error(s), 2 warning(s)" in result
    assert "5: error: type mismatch" in result


def test_missing_checker_and_timeout_are_reported(workspace, monkeypatch):
    (workspace / "sample.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(static_checks.shutil, "which", lambda name: None)
    assert "not installed" in check_python("sample.py", "ruff")

    monkeypatch.setattr(static_checks.shutil, "which", lambda name: "ruff")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(static_checks.subprocess, "run", timeout)
    assert "time limit" in check_python("sample.py", "ruff")
