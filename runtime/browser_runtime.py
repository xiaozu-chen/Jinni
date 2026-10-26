from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from typing import cast

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
                if process.pid is not None:
                    kill_process_group = cast(Callable[[int, int], None], getattr(os, "killpg"))
                    kill_signal = getattr(signal, "SIGKILL", None)
                    if kill_signal is not None:
                        kill_process_group(process.pid, int(kill_signal))
            except ProcessLookupError:
                pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise subprocess.TimeoutExpired(command, timeout) from None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
