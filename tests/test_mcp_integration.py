import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from config import McpServerConfig
from mcp_client import McpManager
from tools import registry

SERVER = str(Path(__file__).parent / "fixtures" / "echo_server.py")


def config(**overrides):
    fields = dict(name="t", command=sys.executable, args=(SERVER,),
                  tools=("echo", "slow", "crash"), call_timeout=10.0)
    fields.update(overrides)
    return McpServerConfig(**fields)


def test_happy_path(clean_registry):
    async def scenario():
        manager = McpManager((config(),))
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
        manager = McpManager((config(),))
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
