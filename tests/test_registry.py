import pytest

import tools
from tools import registry
from tools.registry import tool


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "TOOL_FUNCTIONS", {})
    monkeypatch.setattr(registry, "TOOL_SCHEMAS", [])
    monkeypatch.setattr(registry, "NEEDS_APPROVAL", set())


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
                "write_file", "edit_file", "fetch_url"}
    assert expected <= set(tools.TOOL_FUNCTIONS)


def test_dangerous_tools_require_approval():
    assert {"write_file", "edit_file", "fetch_url"} <= tools.NEEDS_APPROVAL


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