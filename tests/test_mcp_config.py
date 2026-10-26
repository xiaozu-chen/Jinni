import json

import pytest

from config import McpServerConfig
from mcp_config import load_mcp_servers, resolve_mcp_servers


def test_load_mcp_server_definitions_from_json(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"servers": [{
        "name": "fixture",
        "command": "python",
        "args": ["fixture.py"],
        "env": {"FIXTURE_MODE": "sales"},
        "tools": ["get_table"],
        "remember": ["get_table"],
        "resources": ["file:///reports/sales"],
        "prompts": ["summarize"],
        "call_timeout": 12.5,
        "mode": "auto",
    }]}), encoding="utf-8")

    assert load_mcp_servers(path) == (McpServerConfig(
        name="fixture", command="python", args=("fixture.py",),
        env=(("FIXTURE_MODE", "sales"),), tools=("get_table",),
        remember=("get_table",), call_timeout=12.5, mode="auto",
        resources=("file:///reports/sales",), prompts=("summarize",),
    ),)


@pytest.mark.parametrize("servers,reason", [
    ([{"name": "same", "command": "a"}, {"name": "same", "command": "b"}], "unique"),
    ([{"name": "fixture", "command": "python", "remember": ["write"], "tools": []}], "allowlisted"),
    ([{"name": "fixture", "command": "python", "extra": True}], "supported"),
    ([{"name": "fixture", "command": "python", "call_timeout": 0}], "between"),
])
def test_json_config_rejects_unsafe_or_invalid_server_fields(tmp_path, servers, reason):
    path = tmp_path / "servers.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    with pytest.raises(ValueError, match=reason):
        load_mcp_servers(path)


def test_missing_or_invalid_json_falls_back_to_builtin_config(tmp_path):
    fallback = (McpServerConfig(name="built-in", command="python"),)
    missing, warning = resolve_mcp_servers(tmp_path / "missing.json", fallback)
    assert missing == fallback and not warning

    invalid_file = tmp_path / "bad.json"
    invalid_file.write_text("not json", encoding="utf-8")
    loaded, warning = resolve_mcp_servers(invalid_file, fallback)
    assert loaded == fallback
    assert "using built-in" in warning
