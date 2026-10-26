from dataclasses import replace

import httpx

import embedding_server as server_module
from config import settings
from embedding_server import EmbeddingServer


class Process:
    def __init__(self, code=None):
        self.code = code
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = 0

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


def test_embedding_server_starts_configured_process_and_stops_own_child(tmp_path, monkeypatch):
    process = Process()
    commands = []
    config = replace(
        settings, embed_enabled=True, embed_server_command="llama-server",
        embed_server_args=("--embedding", "--host", "127.0.0.1"),
        embed_url="http://127.0.0.1:8081/v1",
    )
    monkeypatch.setattr(server_module.shutil, "which", lambda command: "C:/llama-server.exe")
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda command, **kwargs: commands.append(command) or process)
    monkeypatch.setattr(server_module.httpx, "get", lambda *args, **kwargs: httpx.Response(200))
    server = EmbeddingServer(config, tmp_path / "server.log")

    assert server.start() == "embedding server is ready"
    assert commands == [["C:/llama-server.exe", "--embedding", "--host", "127.0.0.1"]]
    server.stop()
    assert process.terminated
    assert server.process is None


def test_embedding_server_does_not_start_without_configuration(monkeypatch):
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    server = EmbeddingServer(replace(settings, embed_enabled=True, embed_server_command=""))

    assert server.start() == "embedding server management is not configured"


def test_embedding_server_reports_early_child_exit(tmp_path, monkeypatch):
    process = Process(code=1)
    config = replace(settings, embed_enabled=True, embed_server_command="llama-server")
    monkeypatch.setattr(server_module.shutil, "which", lambda command: "llama-server")
    monkeypatch.setattr(server_module.subprocess, "Popen", lambda *args, **kwargs: process)
    server = EmbeddingServer(config, tmp_path / "server.log")

    assert server.start() == "embedding server exited before becoming ready"
