"""Supervise the optional local embedding process used by semantic memory search."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx


class EmbeddingServer:
    def __init__(self, settings, log_path: str | Path = "workspace/.jinni/embedding-server.log") -> None:
        self.settings = settings
        self.log_path = Path(log_path)
        self.process: subprocess.Popen | None = None
        self._log = None

    @property
    def configured(self) -> bool:
        return self.settings.embed_enabled and bool(self.settings.embed_server_command)

    def _health_url(self) -> str:
        parts = urlsplit(self.settings.embed_url)
        path = parts.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        return urlunsplit((parts.scheme, parts.netloc, f"{path}/health", "", ""))

    def start(self) -> str:
        if not self.configured:
            return "embedding server management is not configured"
        if self.process is not None and self.process.poll() is None:
            return "embedding server is already running"
        executable = shutil.which(self.settings.embed_server_command)
        if executable is None and Path(self.settings.embed_server_command).is_file():
            executable = str(Path(self.settings.embed_server_command).resolve())
        if executable is None:
            return "embedding server executable was not found"

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._log = self.log_path.open("ab")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.process = subprocess.Popen(
                [executable, *self.settings.embed_server_args],
                stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
                shell=False, creationflags=flags, env=os.environ.copy(),
            )
        except OSError as error:
            self._close_log()
            self.process = None
            return f"embedding server could not start ({type(error).__name__})"

        deadline = time.monotonic() + self.settings.embed_server_start_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.stop()
                return "embedding server exited before becoming ready"
            try:
                response = httpx.get(self._health_url(), timeout=0.5, trust_env=False)
                if response.is_success:
                    return "embedding server is ready"
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        self.stop()
        return f"embedding server did not become ready within {self.settings.embed_server_start_timeout:g}s"

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self.settings.embed_server_stop_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.settings.embed_server_stop_timeout)
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None
