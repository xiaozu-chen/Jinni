from collections.abc import Callable
from typing import Any, cast

from server.mcp_server import build_server


class FakeMCPServer:
    def __init__(self, name):
        self.name = name
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self):
        def register(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            return function

        return register


def test_server_exposes_only_the_fixed_read_only_tools(workspace, memory_store):
    (workspace / "note.txt").write_text("workspace note", encoding="utf-8")
    memory_store.add("fact", "Likes cats.")

    server = cast(FakeMCPServer, build_server(FakeMCPServer))

    assert set(server.tools) == {"list_files", "read_file", "recall"}
    assert "note.txt" in server.tools["list_files"]()
    assert server.tools["read_file"]("note.txt") == "workspace note"
    assert "Likes cats." in server.tools["recall"]("cats")
