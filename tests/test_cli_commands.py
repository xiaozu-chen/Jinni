from dataclasses import replace
from types import SimpleNamespace

from config import McpServerConfig, settings
from agent import Agent
from jinni import config_text, help_text, show_memories, stats_text, undo_last_turn


def test_help_lists_the_interactive_commands():
    help_output = help_text()

    assert "/undo" in help_output
    assert "/audit [COUNT]" in help_output
    assert "/tasks" in help_output
    assert "/save [NAME]" in help_output
    assert "/load NAME" in help_output
    assert "exit" in help_output


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
