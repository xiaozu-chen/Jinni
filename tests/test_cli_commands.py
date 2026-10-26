from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import McpServerConfig, load_settings, settings
from agent import Agent
from jinni import (
    config_text,
    enable_input_history,
    help_text,
    mcp_restart_target,
    show_memories,
    stats_text,
    undo_last_turn,
)


def test_help_lists_the_interactive_commands():
    help_output = help_text()

    assert "/undo" in help_output
    assert "/project [NAME]" in help_output
    assert "/audit [COUNT]" in help_output
    assert "/tasks" in help_output
    assert "/save [NAME]" in help_output
    assert "/load NAME" in help_output
    assert "exit" in help_output


def test_mcp_restart_target_parses_all_or_one_server():
    assert mcp_restart_target("restart") == ""
    assert mcp_restart_target("restart fixture") == "fixture"
    assert mcp_restart_target("restart  fixture  ") == "fixture"
    assert mcp_restart_target("status") is None


def test_input_history_stays_off_for_non_interactive_streams(monkeypatch):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    assert not enable_input_history()


def test_input_history_loads_readline_for_interactive_streams(monkeypatch):
    import builtins
    import io
    import sys
    from types import ModuleType

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    original_import = builtins.__import__

    def import_readline(name, *args, **kwargs):
        if name == "readline":
            return ModuleType("readline")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(builtins, "__import__", import_readline)

    assert enable_input_history()


def test_settings_load_from_toml_and_keep_defaults(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text(
        'model = "test-model"\n'
        'max_steps = 12\n'
        'embed_enabled = false\n'
        'memory_db = "state/memory.db"\n'
        'embed_prefixes = [["nomic", "query: ", "document: "]]\n'
        '[[mcp_servers]]\n'
        'name = "fixture"\n'
        'command = "python"\n'
        'args = ["server.py"]\n'
        'tools = ["get_table"]\n'
        'env = { DATA_KEY = "private" }\n',
        encoding="utf-8",
    )

    loaded = load_settings(path)

    assert loaded.model == "test-model"
    assert loaded.max_steps == 12
    assert loaded.embed_enabled is False
    assert loaded.memory_db == Path("state/memory.db")
    assert loaded.keep_recent == settings.keep_recent
    assert loaded.embed_prefixes == (("nomic", "query: ", "document: "),)
    assert loaded.mcp_servers == (McpServerConfig(
        name="fixture", command="python", args=("server.py",),
        tools=("get_table",), env=(("DATA_KEY", "private"),),
    ),)


@pytest.mark.parametrize(
    "text, message",
    [
        ('unknown_key = "value"\n', "unknown settings"),
        ('max_steps = true\n', "max_steps must be an integer"),
    ],
)
def test_settings_reject_unknown_keys_and_wrong_types(tmp_path, text, message):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_settings(path)


def test_config_shows_effective_settings_without_secrets():
    config = replace(
        settings,
        model="test-model",
        mcp_enabled=True,
        mcp_servers=(McpServerConfig(
            name="private-server", command="server", env=(("TOKEN", "secret-value"),),
            tools=("read_data",),
        ),),
    )

    output = config_text(config)

    assert "model: test-model" in output
    assert "private-server (read_data)" in output
    assert "secret-value" not in output
    assert "TOKEN" not in output
    assert "base_url" not in output


def test_undo_removes_latest_user_turn_and_refreshes_prompt():
    agent = SimpleNamespace(
        messages=[
            {"role": "system", "content": "initial"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "latest"},
            {"role": "assistant", "content": "more"},
        ],
        apply_memory=lambda: None,
    )

    result = undo_last_turn(agent)

    assert "removed" in result
    assert [message.get("content") for message in agent.messages] == ["initial", "first", "answer"]


def test_undo_without_a_chat_turn_is_safe():
    agent = SimpleNamespace(messages=[{"role": "system", "content": "initial"}], apply_memory=lambda: None)

    assert undo_last_turn(agent) == "(no chat turn to undo)"
    assert len(agent.messages) == 1


def test_memory_command_searches_and_filters_with_session_provenance(memory_store, capsys):
    memory_store.add("fact", "Likes jasmine tea.")
    memory_store.add("event", "Read a report about tea exports.")
    agent = SimpleNamespace(memory=memory_store)

    show_memories(agent, "facts")
    facts = capsys.readouterr().out
    assert "Likes jasmine tea." in facts
    assert "Read a report" not in facts
    assert memory_store.session_id in facts

    show_memories(agent, "search exports")
    assert "Read a report about tea exports." in capsys.readouterr().out


def test_stats_summarizes_tokens_timing_and_tool_counts():
    agent = Agent()
    agent.stats.update(laps=2, prompt_tokens=120, completion_tokens=30, seconds=4.0)
    agent.tool_counts.update({"read_file": 2, "search_files": 1})

    output = stats_text(agent)

    assert "tokens: 150 total (120 prompt, 30 generated)" in output
    assert "2.0s per lap average" in output
    assert "read_file: 2" in output
