import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from config import McpServerConfig
from mcp_client import McpManager
from mcp_data import export_mcp_table
from tools import registry

SERVER = str(Path(__file__).parent / "fixtures" / "echo_server.py")
CHART_SERVER = str(Path(__file__).parent / "fixtures" / "chart_data_server.py")


def config(**overrides):
    fields = dict(name="t", command=sys.executable, args=(SERVER,),
                  tools=("echo", "slow", "crash"), call_timeout=10.0)
    fields.update(overrides)
    return McpServerConfig(**fields)


def test_happy_path(clean_registry):
    async def scenario():
        manager = McpManager((config(),), auto_restart=False)
        await manager.start()
        try:
            assert manager.servers["t"].state == "up"
            assert sorted(registry.TOOL_FUNCTIONS) == ["t_crash", "t_echo", "t_slow"]
            out = await registry.TOOL_FUNCTIONS["t_echo"](text="hello")
            assert "hello" in out and "not instructions" in out
        finally:
            await manager.stop()
        assert manager.servers["t"].state == "stopped"
        assert registry.TOOL_FUNCTIONS == {}

    asyncio.run(scenario())


def test_crash_marks_the_server_down_and_restart_recovers(clean_registry):
    async def scenario():
        manager = McpManager((config(),), auto_restart=False)
        await manager.start()
        try:
            out = await registry.TOOL_FUNCTIONS["t_crash"]()
            assert out.startswith("Error")
            assert manager.servers["t"].state == "down"
            assert "t_echo" not in registry.TOOL_FUNCTIONS

            await manager.restart("t")
            assert manager.servers["t"].state == "up"
            assert "hello" in await registry.TOOL_FUNCTIONS["t_echo"](text="hello")
        finally:
            await manager.stop()

    asyncio.run(scenario())


def test_crashed_server_restarts_automatically_with_backoff(clean_registry):
    async def scenario():
        manager = McpManager((config(),), restart_initial_delay=0.01, restart_max_delay=0.02)
        await manager.start()
        try:
            assert (await registry.TOOL_FUNCTIONS["t_crash"]()).startswith("Error")
            async def wait_until_ready():
                while manager.servers["t"].state != "up" or "t_echo" not in registry.TOOL_FUNCTIONS:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(wait_until_ready(), timeout=3)
            assert "hello" in await registry.TOOL_FUNCTIONS["t_echo"](text="hello")
        finally:
            await manager.stop()

    asyncio.run(scenario())


def test_slow_tool_times_out_but_the_server_stays_up(clean_registry):
    async def scenario():
        manager = McpManager((config(call_timeout=0.5),))
        await manager.start()
        try:
            out = await registry.TOOL_FUNCTIONS["t_slow"]()
            assert "did not answer" in out
            assert manager.servers["t"].state == "up"
            assert "hello" in await registry.TOOL_FUNCTIONS["t_echo"](text="hello")
        finally:
            await manager.stop()

    asyncio.run(scenario())


def test_missing_command_fails_soft(clean_registry):
    async def scenario():
        manager = McpManager((config(command="definitely-not-a-real-command"),))
        lines = await manager.start()
        assert manager.servers["t"].state == "down"
        assert "not found" in " ".join(lines)
        assert registry.TOOL_FUNCTIONS == {}
        await manager.stop()

    asyncio.run(scenario())


def test_local_chart_data_fixture_can_be_bridged_to_workspace(workspace):
    async def scenario():
        cfg = McpServerConfig(
            name="fixture", command=sys.executable, args=(CHART_SERVER,),
            tools=("get_table",),
        )
        manager = McpManager((cfg,))
        await manager.start()
        try:
            result = await export_mcp_table(manager, "fixture", "get_table", {"dataset": "sales"})
            assert "Saved MCP table" in result
            csv_path = next(workspace.glob("fixture-get_table-sales-*.csv"))
            assert "month,revenue,returns" in csv_path.read_text(encoding="utf-8")
        finally:
            await manager.stop()

    asyncio.run(scenario())


def test_jinni_read_only_server_exposes_fixed_tools_over_stdio(tmp_path):
    project = Path(__file__).resolve().parents[1]
    server_root = tmp_path / "server-root"
    workspace = server_root / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "note.txt").write_text("from the test workspace", encoding="utf-8")
    runner = tmp_path / "run_jinni_mcp.py"
    runner.write_text(
        "import os, sys\n"
        f"os.chdir({str(server_root)!r})\n"
        f"sys.path.insert(0, {str(project)!r})\n"
        "from mcp_server import main\n"
        "main()\n",
        encoding="utf-8",
    )

    async def scenario():
        allowed = ("list_files", "read_file", "recall")
        manager = McpManager((McpServerConfig(
            name="jinni", command=sys.executable, args=(str(runner),), tools=allowed,
        ),))
        await manager.start()
        try:
            server = manager.servers["jinni"]
            assert server.state == "up"
            assert {tool.name for tool in server.tools} == set(allowed)
            result = await server.call_raw("read_file", {"path": "note.txt"})
            assert "from the test workspace" in result.content[0].text
        finally:
            await manager.stop()

    asyncio.run(scenario())
