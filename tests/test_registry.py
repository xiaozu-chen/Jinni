import pytest

import tools
from tools import registry
from tools.registry import tool





def test_schema_is_built_from_the_signature(clean_registry):
    @tool(description="demo", params={"path": "a path", "limit": "how many"})
    def demo(path: str, limit: int = 5) -> str:
        return ""

    schema = registry.TOOL_SCHEMAS[0]["function"]
    props = schema["parameters"]["properties"]
    assert schema["name"] == "demo"
    assert props["path"]["type"] == "string"
    assert props["limit"]["type"] == "integer"
    assert schema["parameters"]["required"] == ["path"]


def test_parameter_without_description_is_rejected(clean_registry):
    with pytest.raises(ValueError):
        @tool(description="demo")
        def demo(path: str) -> str:
            return ""


def test_duplicate_names_are_rejected(clean_registry):
    @tool(description="one")
    def demo() -> str:
        return ""

    with pytest.raises(ValueError):
        @tool(description="two")
        def demo() -> str:
            return ""


def test_approval_flag_is_recorded(clean_registry):
    @tool(description="x", approval=True)
    def risky() -> str:
        return ""

    @tool(description="y")
    def harmless() -> str:
        return ""

    assert registry.NEEDS_APPROVAL == {"risky"}


def test_real_tools_are_discovered():
    expected = {"get_current_time", "calculate", "list_files", "read_file",
                "write_file", "edit_file", "fetch_url", "fetch_table"}
    assert expected <= set(tools.TOOL_FUNCTIONS)


def test_dangerous_tools_require_approval():
    assert {"write_file", "edit_file", "fetch_url", "fetch_table"} <= tools.NEEDS_APPROVAL


def test_broken_plugin_is_skipped_not_fatal(monkeypatch):
    real = tools.import_module

    def fake(name):
        if name == "tools.basic":
            raise ImportError("pretend a dependency is missing")
        return real(name)

    monkeypatch.setattr(tools, "import_module", fake)
    errors = tools.load_plugins()

    assert len(errors) == 1
    assert "basic" in errors[0]

def test_remember_requires_approval(clean_registry):
    with pytest.raises(ValueError):
        @tool(description="x", remember=True)
        def demo() -> str:
            return ""


def test_writes_are_never_rememberable():
    assert not ({"write_file", "edit_file"} & tools.REMEMBERABLE)


def test_network_fetch_is_only_remembered_per_domain():
    assert "fetch_url" in tools.REMEMBERABLE
    assert "fetch_url" in tools.SCOPES
    assert "fetch_table" in tools.REMEMBERABLE
    assert "fetch_table" in tools.SCOPES


def test_scope_requires_remember(clean_registry):
    with pytest.raises(ValueError):
        @tool(description="x", approval=True, scope=lambda args: "k")
        def demo() -> str:
            return ""


def test_add_tool_registers_everywhere(clean_registry):
    registry.add_tool("ext_demo", lambda: "x", "an external tool",
                      {"type": "object", "properties": {}}, approval=True, remember=True)
    assert "ext_demo" in registry.TOOL_FUNCTIONS
    assert registry.TOOL_SCHEMAS[0]["function"]["name"] == "ext_demo"
    assert "ext_demo" in registry.NEEDS_APPROVAL
    assert "ext_demo" in registry.REMEMBERABLE


def test_remove_tool_forgets_everything(clean_registry):
    empty = {"type": "object", "properties": {}}
    registry.add_tool("ext_demo", lambda: "x", "d", empty, approval=True, remember=True)
    registry.add_tool("other", lambda: "y", "d", empty)

    registry.remove_tool("ext_demo")
    registry.remove_tool("ext_demo")   # removing twice is harmless

    assert list(registry.TOOL_FUNCTIONS) == ["other"]
    assert [s["function"]["name"] for s in registry.TOOL_SCHEMAS] == ["other"]
    assert "ext_demo" not in registry.NEEDS_APPROVAL
    assert "ext_demo" not in registry.REMEMBERABLE


def test_add_tool_rejects_duplicates(clean_registry):
    empty = {"type": "object", "properties": {}}
    registry.add_tool("ext_demo", lambda: "x", "d", empty)
    with pytest.raises(ValueError):
        registry.add_tool("ext_demo", lambda: "y", "d", empty)
