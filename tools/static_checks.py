import json
import os
import shutil
import subprocess
import tokenize
from pathlib import Path

from . import workspace
from .registry import tool
from .workspace import safe_path

MAX_SOURCE_BYTES = 1_000_000
MAX_CHECK_OUTPUT = 12_000
CHECK_TIMEOUT_SECONDS = 20


def _source_file(path: str) -> tuple[Path, str] | str:
    try:
        full = safe_path(path)
        if full.suffix.lower() != ".py":
            return "Error: static checks accept Python files only."
        if full.stat().st_size > MAX_SOURCE_BYTES:
            return f"Error: Python files larger than {MAX_SOURCE_BYTES // 1000} KB are not checked."
        with tokenize.open(full) as stream:
            source = stream.read()
        return full, source
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, UnicodeError, ValueError) as error:
        return f"Error: could not read '{path}' ({type(error).__name__})."


def _run_checker(checker: str, path: str, full: Path) -> str:
    executable = shutil.which(checker)
    if executable is None:
        return f"{checker} is not installed or not on PATH."
    relative = full.relative_to(workspace.WORKSPACE).as_posix()
    if checker == "ruff":
        command = [executable, "check", "--no-cache", "--output-format", "concise", relative]
    else:
        command = [executable, relative, "--outputjson"]
    env_names = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
    env = {name: os.environ[name] for name in env_names if name in os.environ}
    try:
        result = subprocess.run(
            command,
            cwd=workspace.WORKSPACE,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECK_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: {checker} exceeded the {CHECK_TIMEOUT_SECONDS}-second time limit."
    except OSError as error:
        return f"Error: could not start {checker} ({type(error).__name__})."
    output = (result.stdout or result.stderr).strip()
    if checker == "pyright" and output:
        try:
            report = json.loads(output)
            summary = report.get("summary", {})
            diagnostics = report.get("generalDiagnostics", [])
            lines = [
                f"pyright: {summary.get('errorCount', 0)} error(s), "
                f"{summary.get('warningCount', 0)} warning(s), "
                f"{summary.get('informationCount', 0)} note(s)."
            ]
            for item in diagnostics[:50]:
                position = item.get("range", {}).get("start", {})
                line = position.get("line", 0) + 1
                lines.append(f"{line}: {item.get('severity', 'note')}: {item.get('message', '')}")
            output = "\n".join(lines)
            if len(diagnostics) > 50:
                output += "\n[diagnostics capped at 50]"
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass
    if not output:
        output = f"{checker}: no diagnostics."
    if result.returncode not in (0, 1):
        output = f"Error: {checker} exited with status {result.returncode}.\n{output}"
    return output[:MAX_CHECK_OUTPUT] + ("\n[output capped]" if len(output) > MAX_CHECK_OUTPUT else "")


@tool(
    description="Check one Python file with py_compile, Ruff, or Pyright. Checks are bounded and never apply fixes.",
    params={
        "path": "Python file path relative to the workspace.",
        "checker": "One of py_compile, ruff, or pyright.",
    },
    group="project",
)
def check_python(path: str, checker: str = "py_compile") -> str:
    if checker not in {"py_compile", "ruff", "pyright"}:
        return "Error: checker must be py_compile, ruff, or pyright."
    loaded = _source_file(path)
    if isinstance(loaded, str):
        return loaded
    full, source = loaded
    if checker == "py_compile":
        try:
            compile(source, path, "exec")
            return "py_compile: syntax OK (no bytecode written)."
        except SyntaxError as error:
            return f"py_compile: syntax error on line {error.lineno}: {error.msg}."
    return _run_checker(checker, path, full)
