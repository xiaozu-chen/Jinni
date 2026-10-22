import json
import httpx
import openai

from agent import Agent

from agent import run_tool
from models import ToolCall


def make_call(name, args):
    return ToolCall(id="1", name=name, arguments=json.dumps(args))


def test_unknown_tool():
    result = run_tool(make_call("hack_pc", {}))
    assert "unknown tool" in result


def test_bad_json_does_not_crash():
    result = run_tool(ToolCall(id="1", name="list_files", arguments="{not json"))
    assert result.startswith("Error")


def test_wrong_argument_names_do_not_crash():
    result = run_tool(make_call("read_file", {"wrong": 1}))
    assert result.startswith("Error")


def test_declined_write_does_not_write(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "n")
    result = run_tool(make_call("write_file", {"path": "a.txt", "content": "x"}))

    assert "declined" in result
    assert not (workspace / "a.txt").exists()


def test_approved_write_works(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    run_tool(make_call("write_file", {"path": "a.txt", "content": "x"}))

    assert (workspace / "a.txt").read_text(encoding="utf-8") == "x"

def test_failed_request_does_not_corrupt_history(monkeypatch):
    def boom(self):
        raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(Agent, "stream_response", boom)
    agent = Agent()
    agent.chat("hello")

    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"