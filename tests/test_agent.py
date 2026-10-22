import asyncio
import json
import time

import httpx
import openai
import pytest

from agent import Agent, authorize, execute
from models import ToolCall
from tools import TOOL_FUNCTIONS


def make_call(name, args):
    return ToolCall(id="1", name=name, arguments=json.dumps(args))


def test_unknown_tool():
    args, message = authorize(make_call("hack_pc", {}))
    assert args is None
    assert "unknown tool" in message


def test_bad_json_does_not_crash():
    args, message = authorize(ToolCall(id="1", name="list_files", arguments="{not json"))
    assert args is None
    assert message.startswith("Error")


def test_wrong_argument_names_do_not_crash():
    call = make_call("read_file", {"wrong": 1})
    args, _ = authorize(call)
    result = asyncio.run(execute(call, args))
    assert result.startswith("Error")


def test_declined_write_does_not_write(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    args, message = authorize(make_call("write_file", {"path": "a.txt", "content": "x"}))

    assert args is None
    assert "declined" in message
    assert not (workspace / "a.txt").exists()


def test_approved_write_works(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    call = make_call("write_file", {"path": "a.txt", "content": "x"})
    args, _ = authorize(call)
    asyncio.run(execute(call, args))

    assert (workspace / "a.txt").read_text(encoding="utf-8") == "x"


def slow_calls(monkeypatch):
    def slow():
        time.sleep(0.3)
        return "done"

    monkeypatch.setitem(TOOL_FUNCTIONS, "slow", slow)
    return [ToolCall(id=str(i), name="slow", arguments="{}") for i in range(3)]


def test_tools_run_in_parallel(monkeypatch):
    calls = slow_calls(monkeypatch)
    agent = Agent()

    start = time.perf_counter()
    results = asyncio.run(agent.run_tools(calls))

    assert results == ["done"] * 3
    assert time.perf_counter() - start < 0.7


def test_tools_run_one_by_one_when_parallel_is_off(monkeypatch):
    calls = slow_calls(monkeypatch)
    agent = Agent()
    agent.parallel_tools = False

    start = time.perf_counter()
    results = asyncio.run(agent.run_tools(calls))

    assert results == ["done"] * 3
    assert time.perf_counter() - start >= 0.85


def test_failed_request_does_not_corrupt_history(monkeypatch):
    async def boom(self):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(Agent, "stream_response", boom)
    agent = Agent()
    asyncio.run(agent.chat("hello"))

    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"


def test_cancel_rolls_back_the_turn(monkeypatch):
    async def hang(self):
        await asyncio.sleep(10)

    monkeypatch.setattr(Agent, "stream_response", hang)
    agent = Agent()

    async def scenario():
        task = asyncio.create_task(agent.chat("hello"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(agent.messages) == 1

def test_failure_after_tool_lap_rolls_back_whole_turn(monkeypatch):
    laps = iter([("", [ToolCall(id="1", name="get_current_time", arguments="{}")], 100)])

    async def flaky(self):
        try:
            return next(laps)
        except StopIteration:
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(Agent, "stream_response", flaky)
    agent = Agent()
    asyncio.run(agent.chat("what time is it?"))

    assert len(agent.messages) == 1