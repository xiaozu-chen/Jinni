from dataclasses import replace
from types import SimpleNamespace

from config import McpServerConfig, settings
from jinni import config_text, help_text, undo_last_turn


def test_help_lists_the_interactive_commands():
    help_output = help_text()

    assert "/undo" in help_output
    assert "/audit [COUNT]" in help_output
    assert "/tasks" in help_output
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
