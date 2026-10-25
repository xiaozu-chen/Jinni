from __future__ import annotations

import os
import signal
import subprocess

IS_WINDOWS = os.name == "nt"


def run_browser_command(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run a browser command and clear its process tree if it times out."""
    windows = IS_WINDOWS
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if windows else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
        start_new_session=not windows,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if windows:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise subprocess.TimeoutExpired(command, timeout) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
