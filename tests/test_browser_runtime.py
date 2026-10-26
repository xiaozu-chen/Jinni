import subprocess

import pytest

import browser_runtime


class FakeProcess:
    pid = 1234
    returncode = 0

    def __init__(self, timeout: bool = False):
        self.timeout = timeout
        self.calls = 0
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired("browser", timeout if timeout is not None else 0.0)
        return b"out", b"err"

    def kill(self):
        self.killed = True


def test_success_returns_process_output(monkeypatch):
    process = FakeProcess()
    monkeypatch.setattr(browser_runtime.subprocess, "Popen", lambda *args, **kwargs: process)

    result = browser_runtime.run_browser_command(["browser"], 3)

    assert result.stdout == b"out"
    assert result.stderr == b"err"
    assert result.returncode == 0


def test_windows_timeout_kills_and_waits_for_the_process_tree(monkeypatch):
    process = FakeProcess(timeout=True)
    commands = []
    monkeypatch.setattr(browser_runtime, "IS_WINDOWS", True)
    monkeypatch.setattr(browser_runtime.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(browser_runtime.subprocess, "run", lambda command, **kwargs: commands.append(command))

    with pytest.raises(subprocess.TimeoutExpired):
        browser_runtime.run_browser_command(["browser"], 3)

    assert commands == [["taskkill", "/PID", "1234", "/T", "/F"]]
    assert process.calls == 2
    assert not process.killed
