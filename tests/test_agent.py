import asyncio
import json
import time
from dataclasses import replace
from typing import Any, cast

import httpx
import openai
import pytest
from types import SimpleNamespace

from memory import Proposal

from agent import Agent, authorize, execute
from agent_events import AgentEvent
from models import ToolCall
from tools import TOOL_FUNCTIONS
import agent as agent_mod
from audit import recent_calls
from approval_preview import MAX_ARGUMENT_SUMMARY, summarize_arguments
from tools.web import trust_urls_from_text


def make_call(name, args):
    return ToolCall(id="1", name=name, arguments=json.dumps(args))


def test_thinking_classifier_selects_a_strict_mode(monkeypatch):
    agent = Agent()
    requests = []

    class Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="on"),
            )])

    agent.thinking_classifier = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()),
    )
    monkeypatch.setattr(
        agent_mod, "settings",
        replace(agent_mod.settings, thinking_classifier_model="tiny-router"),
    )
    selected = asyncio.run(agent.classify_thinking("Analyze this algorithm's complexity."))

    assert selected is True
    assert agent.thinking_on is True
    assert requests[0]["model"] == "tiny-router"
    assert requests[0]["temperature"] == 0
    assert requests[0]["max_tokens"] == 16
    assert requests[0]["response_format"] == {"type": "json_object"}
    enum = requests[0]["extra_body"]["json_schema"]["properties"]["thinking"]["enum"]
    assert enum == ["on", "off"]
    assert requests[0]["messages"][-1]["content"] == "Analyze this algorithm's complexity."


def test_thinking_classifier_falls_back_on_invalid_output(monkeypatch):
    agent = Agent()
    agent.thinking_on = True

    class Completions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="probably on"),
            )])

    agent.thinking_classifier = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()),
    )
    monkeypatch.setattr(
        agent_mod, "settings", replace(agent_mod.settings, thinking_default=False),
    )

    assert asyncio.run(agent.classify_thinking("Do something")) is False
    assert agent.thinking_on is False


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
    assert args is not None
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
    assert args is not None
    asyncio.run(execute(call, args))

    assert (workspace / "a.txt").read_text(encoding="utf-8") == "x"


def test_approved_write_shows_bounded_diff_and_redacts_audit(workspace, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    call = make_call("write_file", {"path": "note.txt", "content": "private notes"})

    events = []
    args, _ = authorize(call, emit=events.append)
    assert args is not None
    asyncio.run(execute(call, args))

    prompt = "\n".join(event.text for event in events)
    assert capsys.readouterr().out == ""
    assert "+private notes" in prompt
    audit = recent_calls()
    assert "[approved] write_file" in audit
    assert "[redacted]" in audit
    assert "private notes" not in audit


def test_overwrite_preview_warns_that_existing_file_will_be_replaced(workspace, monkeypatch):
    (workspace / "note.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "n")

    events = []
    authorize(make_call("write_file", {"path": "note.txt", "content": "new"}), emit=events.append)

    assert "Existing file will be overwritten." in "\n".join(event.text for event in events)
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "old"


def test_approval_arguments_are_truncated():
    summary = summarize_arguments({"content": "x" * (MAX_ARGUMENT_SUMMARY * 2)})

    assert len(summary) <= MAX_ARGUMENT_SUMMARY + len("…[truncated]")
    assert summary.endswith("…[truncated]")


def test_invalid_python_write_is_rejected_before_approval(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("invalid Python must not prompt"))
    args, message = authorize(make_call("write_file", {"path": "broken.py", "content": "def nope(:\n"}))

    assert args is None
    assert "syntax error on line 1" in message
    assert not (workspace / "broken.py").exists()


def test_invalid_python_patch_is_rejected_before_approval(workspace, monkeypatch):
    (workspace / "module.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("invalid Python must not prompt"))
    args, message = authorize(make_call("apply_patch", {
        "path": "module.py",
        "patches": [{"old_text": "return 42", "new_text": "return )"}],
    }))

    assert args is None
    assert "syntax error" in message
    assert (workspace / "module.py").read_text(encoding="utf-8") == "def answer():\n    return 42\n"


def test_tools_cannot_access_project_control_files(workspace):
    from tools.workspace import safe_path

    for path in (".git/config", "nested/.jinni/managed-project"):
        with pytest.raises(ValueError, match="control files"):
            safe_path(path)


def test_project_tools_are_hidden_and_refused_without_an_active_project(monkeypatch):
    agent = Agent(project_active=False)
    monkeypatch.setattr(agent_mod, "execute", lambda *args: pytest.fail("hidden tools cannot run"))

    result = asyncio.run(agent.run_tools([make_call("write_file", {"path": "a.txt", "content": "x"})]))

    assert "only after selecting a managed project" in result[0]
    assert "write_file" not in agent.visible_tool_names()


def test_remembered_approval_is_marked_auto(monkeypatch):
    trust_urls_from_text("https://example.com/one https://example.com/two")
    monkeypatch.setattr("builtins.input", lambda _: "a")
    allowed = set()
    authorize(make_call("fetch_url", {"url": "https://example.com/one"}), allowed)
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("remembered approval should not prompt"))
    authorize(make_call("fetch_url", {"url": "https://example.com/two"}), allowed)

    assert "[auto] fetch_url" in recent_calls(2)


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
    assert agent.tool_counts == {"slow": 3}


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
        raise openai.APIConnectionError(request=cast(Any, httpx.Request("POST", "http://x")))

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
            raise openai.APIConnectionError(request=cast(Any, httpx.Request("POST", "http://x")))

    monkeypatch.setattr(Agent, "stream_response", flaky)
    agent = Agent()
    asyncio.run(agent.chat("what time is it?"))

    assert len(agent.messages) == 1


@pytest.fixture
def ping_tool(monkeypatch):
    monkeypatch.setitem(TOOL_FUNCTIONS, "ping", lambda: "pong")
    monkeypatch.setattr(agent_mod, "NEEDS_APPROVAL", agent_mod.NEEDS_APPROVAL | {"ping"})
    monkeypatch.setattr(agent_mod, "REMEMBERABLE", agent_mod.REMEMBERABLE | {"ping"})


def test_always_allow_is_asked_only_once(ping_tool, monkeypatch):
    answers = iter(["a"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    allowed: set[tuple[str, str]] = set()

    first, _ = authorize(make_call("ping", {}), allowed)
    second, _ = authorize(make_call("ping", {}), allowed)

    assert first == {} and second == {}
    assert allowed == {("ping", "*")}


def test_always_is_refused_for_dangerous_tools(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "a")
    allowed: set[tuple[str, str]] = set()

    args, _ = authorize(make_call("write_file", {"path": "a.txt", "content": "x"}), allowed)

    assert args is None
    assert allowed == set()
    assert not (workspace / "a.txt").exists()

def test_domain_approval_covers_only_that_domain(monkeypatch):
    trust_urls_from_text("https://www.mayoclinic.org/diet https://mayoclinic.org/other https://evil.example/x")
    answers = iter(["a", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    allowed: set[tuple[str, str]] = set()

    first, _ = authorize(make_call("fetch_url", {"url": "https://www.mayoclinic.org/diet"}), allowed)
    again, _ = authorize(make_call("fetch_url", {"url": "https://mayoclinic.org/other"}), allowed)
    other, _ = authorize(make_call("fetch_url", {"url": "https://evil.example/x"}), allowed)

    assert first is not None
    assert again is not None
    assert other is None
    assert allowed == {("fetch_url", "mayoclinic.org")}


def test_fetch_refuses_urls_not_given_or_found_in_search(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("untrusted URLs must not reach approval"))
    args, message = authorize(make_call("fetch_url", {"url": "https://guessed.example/page"}))

    assert args is None
    assert "supplied" in message


def test_search_results_authorize_follow_up_fetch(monkeypatch):
    trust_urls_from_text("Search results: https://docs.example.org/guide?ref=1.")
    monkeypatch.setattr("builtins.input", lambda _: "y")

    args, message = authorize(make_call("fetch_url", {"url": "https://docs.example.org/guide?ref=1"}))

    assert args is not None
    assert message == ""


def test_always_allow_for_a_domain_is_persisted(workspace, monkeypatch):
    from approval_store import load_approvals

    trust_urls_from_text("https://example.com/page")
    monkeypatch.setattr("builtins.input", lambda _: "a")

    async def fake_execute(call, args):
        return "fetched"

    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    path = workspace / ".jinni" / "allowed.json"
    agent = Agent(allowed_file=path)
    asyncio.run(agent.run_tools([make_call("fetch_url", {"url": "https://example.com/page"})]))

    assert load_approvals(path) == {("fetch_url", "example.com")}


def test_search_tool_output_adds_trusted_urls(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")

    async def fake_execute(call, args):
        return "1. Docs\n   https://docs.example.org/guide\n   A helpful guide."

    monkeypatch.setattr(agent_mod, "execute", fake_execute)
    agent = Agent()
    asyncio.run(agent.run_tools([make_call("web_search", {"query": "docs"})]))

    args, message = authorize(make_call("fetch_url", {"url": "https://docs.example.org/guide"}))
    assert args is not None and message == ""


def test_non_object_arguments_are_rejected():
    args, message = authorize(ToolCall(id="1", name="list_files", arguments="[1, 2]"))
    assert args is None
    assert message.startswith("Error")

def test_system_prompt_contains_saved_facts(memory_store):
    agent = Agent()
    memory_store.add("fact", "The user's name is Carl.")
    agent.apply_memory()
    assert "Carl" in agent.messages[0]["content"]

    memory_store.clear()
    agent.apply_memory()
    assert "Carl" not in agent.messages[0]["content"]


def test_saved_facts_respect_prompt_character_budget(memory_store, monkeypatch):
    memory_store.add("fact", "old-" + "o" * 120)
    memory_store.add("fact", "new-" + "n" * 120)
    monkeypatch.setattr(agent_mod, "settings", replace(agent_mod.settings, memory_prompt_chars=300))

    agent = Agent()
    prompt = agent.messages[0]["content"]

    memory_block = prompt.split("What you remember", 1)[1]
    assert len("What you remember" + memory_block) <= 300
    assert "new-" in memory_block
    assert "old-" not in memory_block
    assert "omitted" in memory_block


def test_proposals_come_from_the_model_reply(monkeypatch):
    async def fake_request(self, **kwargs):
        message = SimpleNamespace(content="FACT: Likes cats.\nSUMMARY: Said hi.")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(Agent, "request", fake_request)
    agent = Agent()
    agent.messages.append({"role": "user", "content": "hi, I like cats"})

    assert asyncio.run(agent.propose_memories()) == [
        Proposal("fact", "Likes cats."),
        Proposal("event", "Said hi."),
    ]


def test_no_proposals_for_an_empty_session(monkeypatch):
    async def explode(self, **kwargs):
        raise AssertionError("the model should not be called")

    monkeypatch.setattr(Agent, "request", explode)
    assert asyncio.run(Agent().propose_memories()) == []

def test_async_tools_are_awaited(monkeypatch):
    async def greet(name: str) -> str:
        return f"hi {name}"

    monkeypatch.setitem(TOOL_FUNCTIONS, "greet", greet)
    call = make_call("greet", {"name": "Carl"})
    args, _ = authorize(call)
    assert args is not None
    assert asyncio.run(execute(call, args)) == "hi Carl"


def test_step_limit_offers_to_continue(monkeypatch):
    monkeypatch.setattr(agent_mod, "settings", replace(agent_mod.settings, max_steps=1))
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    responses = iter([
        ("", [make_call("get_current_time", {})], 10),
        ("finished", [], 10),
    ])
    calls = []

    async def fake_stream(self):
        calls.append(True)
        return next(responses)

    monkeypatch.setattr(Agent, "stream_response", fake_stream)
    agent = Agent()

    asyncio.run(agent.chat("continue please"))

    assert len(calls) == 2
    assert agent.messages[-1] == {"role": "assistant", "content": "finished"}


def test_start_subtask_keeps_a_short_reference_and_resets_history(monkeypatch, memory_store):
    requests = []
    events = []

    async def fake_request(self, **kwargs):
        requests.append(kwargs)
        message = SimpleNamespace(content="Project uses pytest. Update parser.py; test remains pending.")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(Agent, "request", fake_request)
    agent = Agent(store=memory_store, project_guidance="Use the existing formatter.", event_sink=events.append)
    agent.summary = "Earlier compaction notes"
    agent.messages.extend([
        {"role": "user", "content": "Fix the parser"},
        {"role": "assistant", "content": "I will inspect parser.py"},
        {"role": "tool", "content": "old tool output"},
    ])

    result = asyncio.run(agent.start_subtask("Add coverage for empty input"))

    assert result == "fresh subtask context started"
    assert "untrusted" in requests[0]["messages"][0]["content"]
    assert "Earlier compaction notes" in requests[0]["messages"][1]["content"]
    assert "parser.py" in requests[0]["messages"][1]["content"]
    assert len(agent.messages) == 3
    assert "existing formatter" in agent.messages[0]["content"]
    assert "untrusted and possibly incomplete" in agent.messages[1]["content"]
    assert agent.messages[2]["content"] == "New subtask: Add coverage for empty input"
    assert agent.summary == ""
    assert events[-1].kind == "status"


def test_start_subtask_rejects_empty_or_oversized_task():
    agent = Agent()

    with pytest.raises(ValueError, match="between 1 and 2,000"):
        asyncio.run(agent.start_subtask("  "))


def test_step_limit_stops_when_user_says_no(monkeypatch, capsys):
    monkeypatch.setattr(agent_mod, "settings", replace(agent_mod.settings, max_steps=1))
    monkeypatch.setattr("builtins.input", lambda _: "n")
    calls = []

    async def fake_stream(self):
        calls.append(True)
        return "", [make_call("get_current_time", {})], 10

    monkeypatch.setattr(Agent, "stream_response", fake_stream)
    events: list[AgentEvent] = []
    agent = Agent(event_sink=events.append)

    asyncio.run(agent.chat("one more thing"))

    assert len(calls) == 1
    assert "stopped at the step limit" in "\n".join(event.text for event in events)
    assert capsys.readouterr().out == ""
    assert agent.messages[-1]["role"] == "tool"
