import asyncio
import inspect
import sys
from types import SimpleNamespace

import pytest

from config import McpServerConfig
from mcp_client import (McpServer, build_parameters, find_command, format_result, plain,
                        register_server_tools, shrink_schema, tool_name, validate_arguments)
from tools import registry

SCHEMA = {"type": "object", "properties": {"q": {"type": "string", "description": "x" * 500}}}


class FakeServer:
    def __init__(self, tool_names, **cfg):
        self.cfg = McpServerConfig(name="ddgs", command="ddgs", **cfg)
        self.tools = [SimpleNamespace(name=n, description=f"{n} does things", input_schema=SCHEMA)
                      for n in tool_names]
        self.calls = []

    async def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return "ok"


def result(content=None, structured=None, is_error=False):
    return SimpleNamespace(content=content or [], structured_content=structured, is_error=is_error)


def text(value):
    return SimpleNamespace(type="text", text=value)


def test_shrink_truncates_descriptions_and_drops_titles():
    schema = {"title": "Args", "type": "object",
              "properties": {"q": {"type": "string", "title": "Q", "description": "x" * 500}}}
    shrunk = shrink_schema(schema)
    assert "title" not in shrunk
    assert "title" not in shrunk["properties"]["q"]
    assert len(shrunk["properties"]["q"]["description"]) == 160


def test_shrink_keeps_parameters_named_like_keywords():
    schema = {"type": "object", "properties": {
        "title": {"type": "string", "description": "the title"},
        "description": {"type": "string", "description": "the description"}}}
    assert set(shrink_schema(schema)["properties"]) == {"title", "description"}


def test_shrink_flattens_optional_types():
    schema = {"type": "object", "properties": {"timelimit": {
        "anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "description": "d"}}}
    assert shrink_schema(schema)["properties"]["timelimit"] == {"type": "string", "description": "d"}


def test_non_object_schema_falls_back_to_no_parameters():
    empty = {"type": "object", "properties": {}}
    assert build_parameters(SimpleNamespace(input_schema={"type": "string"})) == empty
    assert build_parameters(SimpleNamespace()) == empty


def test_validate_arguments_checks_required_types_and_extra_fields():
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"],
        "additionalProperties": False,
    }

    assert validate_arguments(schema, {"query": "cats"}) == []
    assert "query is required" in validate_arguments(schema, {})[0]
    assert "must be string" in validate_arguments(schema, {"query": 3})[0]
    assert "extra is not allowed" in validate_arguments(schema, {"query": "cats", "extra": True})[0]


def test_validate_arguments_checks_nested_values_and_refs():
    schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"$ref": "#/$defs/entry"}},
        },
        "required": ["items"],
        "$defs": {"entry": {"type": "object", "properties": {
            "count": {"type": "integer", "minimum": 1},
        }, "required": ["count"]}},
    }

    assert validate_arguments(schema, {"items": [{"count": 2}]}) == []
    assert "minimum" in validate_arguments(schema, {"items": [{"count": 0}]})[0]


def test_bad_schema_fails_validation_closed():
    assert validate_arguments(None, {}) == ["the server did not advertise an object input schema"]


def test_tool_names_are_sanitized():
    assert tool_name("my server", "do/it!") == "my_server_do_it_"
    assert len(tool_name("s" * 80, "t")) == 64


def test_plain_removes_control_characters():
    out = plain("\x1b[31mred\x1b[0m\nline")
    assert "\x1b" not in out and "\n" not in out


def test_find_command():
    assert find_command(sys.executable) is not None
    assert find_command("definitely-not-a-real-command") is None


def test_results_are_labelled_as_data():
    out = format_result(result([text("hello")]), "ddgs")
    assert "hello" in out and "not instructions" in out and "ddgs" in out


def test_mcp_text_output_strips_terminal_escape_sequences():
    out = format_result(result([text("\x1b[31munsafe\x1b[0m")]), "fixture")

    assert "\x1b" not in out
    assert "unsafe" in out


def test_error_results_start_with_error():
    assert format_result(result([text("boom")], is_error=True), "s").startswith("Error: boom")


def test_non_text_blocks_are_omitted():
    out = format_result(result([SimpleNamespace(type="image", data="AAAA"), text("caption")]), "s")
    assert "AAAA" not in out
    assert "image content omitted" in out
    assert "caption" in out


def test_long_results_are_truncated():
    out = format_result(result([text("x" * 100)]), "s", limit=10)
    assert "[output truncated]" in out
    assert "x" * 11 not in out


def test_structured_content_is_the_fallback():
    assert '"answer": 42' in format_result(result(structured={"answer": 42}), "s")


def test_only_allowlisted_tools_are_exposed(clean_registry):
    server = FakeServer(["search_text", "extract_content", "search_books"], tools=("search_text",))
    reg = register_server_tools(server)
    assert reg.exposed == ["ddgs_search_text"]
    assert reg.hidden == ["extract_content", "search_books"]
    assert list(registry.TOOL_FUNCTIONS) == ["ddgs_search_text"]
    assert "ddgs_search_text" in registry.NEEDS_APPROVAL
    assert "ddgs_search_text" not in registry.REMEMBERABLE


def test_remember_is_opt_in(clean_registry):
    server = FakeServer(["search_text"], tools=("search_text",), remember=("search_text",))
    register_server_tools(server)
    assert "ddgs_search_text" in registry.REMEMBERABLE


def test_allowlisting_a_missing_tool_is_reported(clean_registry):
    reg = register_server_tools(FakeServer(["search_text"], tools=("search_text", "typo_tool")))
    assert reg.exposed == ["ddgs_search_text"]
    assert any("typo_tool" in p for p in reg.problems)


def test_name_collisions_are_skipped(clean_registry):
    registry.add_tool("ddgs_search_text", lambda: "mine", "mine", {"type": "object", "properties": {}})
    reg = register_server_tools(FakeServer(["search_text"], tools=("search_text",)))
    assert reg.exposed == []
    assert reg.problems
    assert registry.TOOL_FUNCTIONS["ddgs_search_text"]() == "mine"


def test_descriptions_are_labelled_and_capped(clean_registry):
    register_server_tools(FakeServer(["search_text"], tools=("search_text",)))
    function = registry.TOOL_SCHEMAS[0]["function"]
    assert function["description"].startswith("[via MCP server 'ddgs']")
    assert len(function["description"]) <= 300
    assert len(function["parameters"]["properties"]["q"]["description"]) == 160


def test_registered_tool_forwards_to_the_server(clean_registry):
    server = FakeServer(["search_text"], tools=("search_text",))
    register_server_tools(server)
    fn = registry.TOOL_FUNCTIONS["ddgs_search_text"]

    assert inspect.iscoroutinefunction(fn)
    assert asyncio.run(fn(q="cats")) == "ok"
    assert server.calls == [("search_text", {"q": "cats"})]


def test_missing_sdk_fails_soft(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)
    server = McpServer(McpServerConfig(name="t", command="whatever"))

    async def scenario():
        await server.start()
        await server.stop()

    asyncio.run(scenario())
    assert server.state == "down"
    assert "not installed" in server.error


class FakeCallClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return result([text("ok")])

    async def list_tools(self):
        return SimpleNamespace(tools=[])

    async def read_resource(self, uri):
        self.calls.append(("read_resource", uri))
        return SimpleNamespace(contents=[SimpleNamespace(text="resource text")])

    async def get_prompt(self, name, arguments=None):
        self.calls.append(("get_prompt", name, arguments))
        return SimpleNamespace(messages=[SimpleNamespace(
            role="user", content=SimpleNamespace(text="prompt text")
        )])


def ready_server():
    server = McpServer(McpServerConfig(name="fixture", command="fixture", tools=("lookup",)))
    server.state = "up"
    server.client = FakeCallClient()
    server.tools = [SimpleNamespace(
        name="lookup",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"]},
    )]
    return server


def test_server_call_rejects_bad_arguments_before_contacting_server():
    server = ready_server()

    message = asyncio.run(server.call("lookup", {"query": 4}))

    assert "invalid arguments" in message
    assert "must be string" in message
    assert server.client.calls == []


def test_raw_server_call_validates_arguments_and_forwards_valid_calls():
    server = ready_server()

    with pytest.raises(ValueError, match="query is required"):
        asyncio.run(server.call_raw("lookup", {}))
    result_value = asyncio.run(server.call_raw("lookup", {"query": "cats"}))

    assert result_value.content[0].text == "ok"
    assert server.client.calls == [("lookup", {"query": "cats"})]


def test_manager_shutdown_cancels_pending_automatic_restarts(clean_registry):
    from mcp_client import McpManager

    async def scenario():
        manager = McpManager((McpServerConfig(name="fixture", command="fixture"),),
                             restart_initial_delay=10)
        manager._schedule_restart("fixture")
        assert manager._restart_tasks

        await manager.stop()

        assert manager._stopping
        assert not manager._restart_tasks

    asyncio.run(scenario())


def test_server_call_refuses_tools_outside_allowlist():
    server = ready_server()

    message = asyncio.run(server.call("other", {}))

    assert "not allowlisted" in message
    assert server.client.calls == []


def test_resource_read_requires_explicit_allowlist_and_uses_safe_output():
    from dataclasses import replace

    server = ready_server()
    uri = "file:///reports/sales"
    server.cfg = replace(server.cfg, resources=(uri,))
    server.resources = [SimpleNamespace(uri=uri)]

    output = asyncio.run(server.read_resource(uri))
    refused = asyncio.run(server.read_resource("file:///other"))

    assert "resource text" in output and "not instructions" in output
    assert "not allowlisted" in refused
    assert server.client.calls == [("read_resource", uri)]


def test_prompt_read_validates_arguments_and_formats_result():
    from dataclasses import replace

    server = ready_server()
    server.cfg = replace(server.cfg, prompts=("summarize",))
    server.prompts = [SimpleNamespace(name="summarize", arguments=[
        SimpleNamespace(name="topic", required=True),
    ])]

    missing = asyncio.run(server.get_prompt("summarize", {}))
    extra = asyncio.run(server.get_prompt("summarize", {"topic": "sales", "extra": "x"}))
    output = asyncio.run(server.get_prompt("summarize", {"topic": "sales"}))

    assert "required prompt argument" in missing
    assert "unsupported prompt argument" in extra
    assert "prompt text" in output and "not instructions" in output
    assert server.client.calls == [("get_prompt", "summarize", {"topic": "sales"})]
