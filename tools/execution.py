"""Project-scoped test and optional PowerShell tools, both AppContainer-only."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from config import settings
from .registry import tool
from . import workspace
from .sandbox import (
    OUTPUT_LIMIT, create_sandbox_profile, delete_sandbox_profile, run_isolated,
)

MAX_TIMEOUT = 300
MAX_SCRIPT_CHARS = 12_000
MAX_PROJECT_FILES = 10_000
MAX_PROJECT_BYTES = 200_000_000
_SKIP_COPY_DIRS = {".git", ".jinni", ".pytest_cache", ".venv", "venv", "__pycache__", "node_modules", "build", "dist", "workspace"}
_PYTEST_BOOTSTRAP = r'''
import asyncio.proactor_events as proactor_events
import asyncio.windows_events as windows_events
import os
import shutil
import signal
import sys
import tempfile
import uuid
from pathlib import Path


class WakeHandle:
    def fileno(self):
        return -1

    def close(self):
        pass


def make_self_pipe(loop):
    loop._ssock = loop._csock = WakeHandle()
    loop._internal_fds += 1


def ignore_wakeup(loop):
    pass


def close_self_pipe(loop):
    loop._ssock = loop._csock = None
    loop._internal_fds -= 1


# Windows' Proactor self-pipe requires loopback; short IOCP polls keep asyncio awake, nya.
proactor_events.BaseProactorEventLoop._make_self_pipe = make_self_pipe
proactor_events.BaseProactorEventLoop._write_to_self = ignore_wakeup
proactor_events.BaseProactorEventLoop._close_self_pipe = close_self_pipe
windows_events.ProactorEventLoop._loop_self_reading = lambda loop, *args: None
original_select = windows_events.IocpProactor.select


def poll_without_loopback(proactor, timeout=None):
    bounded = 0.01 if timeout is None else min(timeout, 0.01)
    return original_select(proactor, bounded)


windows_events.IocpProactor.select = poll_without_loopback
signal.set_wakeup_fd = lambda *args, **kwargs: -1

source = Path(sys.argv[3])
project = Path.cwd() / "project"
skip = {".git", ".jinni", ".pytest_cache", ".venv", "venv", "__pycache__",
        "node_modules", "build", "dist", "workspace"}
shutil.copytree(source, project, ignore=lambda _path, names: {name for name in names if name in skip})
os.chdir(project)
temp = project / f".jinni-pytest-tmp-{uuid.uuid4().hex}"
temp.mkdir()
os.environ["TEMP"] = os.environ["TMP"] = str(temp)
tempfile.tempdir = str(temp)
config = next((project / name for name in (
    "pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
    "pyproject.toml", "tox.ini", "setup.cfg",
) if (project / name).is_file()), project / "pytest.ini")
if not config.exists():
    config.write_text("[pytest]\n", encoding="utf-8")
import pytest
sink = open(sys.argv[2], "w", encoding="utf-8", errors="replace")
sys.stdout = sys.stderr = sink
raise SystemExit(pytest.main([
    "-q", "-s", "-p", "no:cacheprovider", "-c", str(config),
    "-o", "addopts=", "--basetemp", str(temp), sys.argv[1],
]))
'''


def _managed_project() -> Path:
    configured = Path(workspace.WORKSPACE).expanduser()
    if configured.is_symlink():
        raise ValueError("the active project folder cannot be a symbolic link")
    root = configured.resolve()
    managed = (root / ".jinni" / "managed-project").is_file() and (root / ".git").is_dir()
    if (not workspace.PROJECT_ACTIVE and not managed) or not root.is_dir():
        raise ValueError("select a project before running project code")
    return root


def _checked_target(root: Path, path: str) -> Path:
    requested = Path(path)
    if not path or requested.is_absolute() or any(part in {"..", ""} for part in requested.parts):
        raise ValueError("choose a relative test path inside the active project")
    target = root / requested
    current = root
    for part in requested.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("test paths cannot follow symbolic links")
    target = target.resolve()
    if not target.is_relative_to(root) or not target.exists() or not (target.is_file() or target.is_dir()):
        raise ValueError("the test path must name an existing file or folder inside the project")
    return target


def _validate_timeout(timeout: int) -> None:
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT:
        raise ValueError(f"timeout must be an integer from 1 to {MAX_TIMEOUT} seconds")


def _validate_project_for_tests(root: Path) -> None:
    file_count = 0
    total_bytes = 0
    for folder, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(folder)
        dirs[:] = [name for name in dirs if name not in _SKIP_COPY_DIRS]
        for name in dirs + files:
            path = base / name
            if path.is_symlink():
                raise ValueError("the test snapshot cannot include symbolic links")
            if path.is_file():
                file_count += 1
                total_bytes += path.stat().st_size
                if file_count > MAX_PROJECT_FILES or total_bytes > MAX_PROJECT_BYTES:
                    raise ValueError("the test snapshot exceeds 10,000 files or 200 MB")



def _format_result(label: str, code: int, output: str, truncated: bool) -> str:
    note = "\n[output truncated at 64,000 characters]" if truncated else ""
    return f"{label} exited with status {code}.\n{output[:OUTPUT_LIMIT]}{note}"


@tool(
    "Run the project's tests with the fixed pytest command inside a no-network Windows AppContainer.",
    params={"path": "relative test file or folder (defaults to tests)", "timeout": "timeout in seconds (1-300)"},
    approval=True,
    group="project",
)
def run_tests(path: str = "tests", timeout: int = 120) -> str:
    """Snapshot the project and run its fixed pytest command inside AppContainer."""
    _validate_timeout(timeout)
    root = _managed_project()
    target = _checked_target(root, path)
    if os.name != "nt":
        return "Error: isolated tests require Windows AppContainer support."
    profile, profile_temp = create_sandbox_profile()
    try:
        _validate_project_for_tests(root)
        with tempfile.TemporaryDirectory(prefix="jinni-test-") as folder:
            scratch = Path(folder)
            output = scratch / "test-output.txt"
            read_only = {
                sys.prefix, sys.base_prefix, str(Path(sys.base_prefix) / "DLLs"),
                os.environ.get("SystemRoot", r"C:\Windows"),
            }
            git_paths: tuple[str, ...] = ()
            git = shutil.which("git")
            if git:
                git_command_dir = Path(git).resolve().parent
                git_root = git_command_dir.parent if git_command_dir.name.casefold() == "cmd" else git_command_dir
                read_only.add(str(git_root))
                git_paths = (str(git_command_dir), str(git_root / "bin"))
            try:
                code, text, truncated = run_isolated(
                    sys.executable,
                    ["-I", "-c", _PYTEST_BOOTSTRAP,
                     target.relative_to(root).as_posix(), str(output), str(root)],
                    profile_temp, scratch, timeout, output,
                    sorted({item for item in read_only if item} | {str(root)}), profile,
                    (str(root / ".git"), str(root / ".jinni")),
                    git_paths, disallow_win32k=False,
                )
            except (OSError, RuntimeError, TimeoutError) as error:
                return f"Error: isolated tests did not run ({error})."
    finally:
        delete_sandbox_profile(profile)
    return _format_result("pytest", code, text, truncated)


def _powershell_executable() -> str:
    command = shutil.which("pwsh") or shutil.which("powershell")
    if not command:
        raise RuntimeError("PowerShell is not installed")
    return str(Path(command).resolve())


if settings.powershell_enabled:
    @tool(
        "Run an approved isolated PowerShell script. The active project is the JinniProject: drive (also $env:JINNI_PROJECT_ROOT).",
        params={"script": "PowerShell script, up to 12,000 characters", "timeout": "timeout in seconds (1-300)"},
        approval=True,
        group="project",
    )
    def run_powershell(script: str, timeout: int = 60) -> str:
        if not isinstance(script, str) or not script.strip() or len(script) > MAX_SCRIPT_CHARS:
            raise ValueError("script must contain 1 to 12,000 characters")
        _validate_timeout(timeout)
        root = _managed_project()
        if os.name != "nt":
            return "Error: isolated PowerShell requires Windows AppContainer support."
        try:
            executable = _powershell_executable()
        except RuntimeError as error:
            return f"Error: {error}."
        profile, profile_temp = create_sandbox_profile()
        try:
            with tempfile.TemporaryDirectory(prefix="jinni-powershell-") as folder:
                scratch = Path(folder)
                output = scratch / "powershell-output.txt"
                quoted_output = str(output).replace("'", "''")
                quoted_root = str(root).replace("'", "''")
                wrapped = (
                    f"& {{ $env:JINNI_PROJECT_ROOT = '{quoted_root}'; "
                    "New-PSDrive -Name JinniProject -PSProvider FileSystem "
                    "-Root $env:JINNI_PROJECT_ROOT | Out-Null; Set-Location JinniProject:\\; "
                    f"\n{script}\n}} *> '{quoted_output}'"
                )
                read_only = {
                    os.environ.get("SystemRoot", r"C:\Windows"),
                    str(Path(executable).parent),
                }
                try:
                    code, text, truncated = run_isolated(
                        executable,
                        ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", wrapped],
                        profile_temp, scratch, timeout, output, sorted(read_only), profile,
                        deny=(str(root / ".git"), str(root / ".jinni")),
                        path_extra=(str(Path(executable).parent),),
                        # The PowerShell host needs Win32k startup calls; AppContainer still blocks the network, nya.
                        capabilities="registryRead", disallow_win32k=False,
                        read_write=(str(root),),
                    )
                except (OSError, RuntimeError, TimeoutError) as error:
                    return f"Error: isolated PowerShell did not run ({error})."
        finally:
            delete_sandbox_profile(profile)
        return _format_result("PowerShell", code, text, truncated)
