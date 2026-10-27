import pytest
from permission.policy import ToolPolicy, permission_decision
from tools.registry import tool_names


@pytest.mark.parametrize(
    ("tool", "mode", "project", "tainted", "isolated", "mcp_remembered", "expected"),
    [
        ("write_file", "ask", True, False, False, False, "ask"),
        ("write_file", "auto-edit", True, False, False, False, "allow"),
        ("write_file", "full-access", True, False, False, False, "allow"),
        ("edit_file", "auto-edit", True, True, False, False, "ask"),
        ("apply_patch", "full-access", True, True, False, False, "ask"),
        ("write_file", "full-access", False, False, False, False, "deny"),
        ("fetch_url", "ask", True, False, False, False, "ask"),
        ("fetch_url", "auto", False, False, False, False, "allow"),
        ("fetch_url", "auto-edit", True, False, False, False, "allow"),
        ("fetch_url", "full-access", True, False, False, False, "allow"),
        ("web_search", "full-access", True, True, False, False, "allow"),
        ("fetch_table", "full-access", True, False, False, False, "ask"),
        ("run_powershell", "full-access", True, False, False, False, "ask"),
        ("run_powershell", "full-access", True, False, True, False, "allow"),
        ("remember", "full-access", True, False, False, False, "ask"),
        ("forget", "full-access", True, False, False, False, "ask"),
        ("delete_file", "ask", True, False, False, False, "deny"),
        ("delete_file", "auto-edit", True, False, False, False, "deny"),
        ("delete_file", "full-access", True, False, False, False, "deny"),
    ],
)
def test_permission_policy_decision_table(
    tool, mode, project, tainted, isolated, mcp_remembered, expected,
):
    policy_tool = ToolPolicy(
        name=tool,
        requires_approval=True,
        group="project" if tool in {"write_file", "edit_file", "apply_patch", "run_tests", "run_powershell"} else "core",
        isolated=isolated,
        mcp_remembered=mcp_remembered,
    )
    assert permission_decision(policy_tool, mode, project, tainted) == expected


def test_mcp_is_asked_unless_its_user_config_marks_it_rememberable():
    tool = ToolPolicy("example_search_text", True, group="mcp")
    assert permission_decision(tool, "full-access", True, False) == "ask"
    remembered = ToolPolicy("example_search_text", True, group="mcp", mcp_remembered=True)
    assert permission_decision(remembered, "full-access", True, False) == "allow"


def test_taint_blocks_file_auto_approval_but_not_safe_research():
    for mode in ("ask", "auto", "auto-edit", "full-access"):
        assert permission_decision(ToolPolicy("write_file", True, group="project"), mode, True, True) == "ask"
        expected_research = "ask" if mode == "ask" else "allow"
        assert permission_decision(ToolPolicy("web_search", True), mode, False, True) == expected_research


def test_free_form_command_is_not_allowed_by_full_access_without_isolation():
    assert permission_decision(
        ToolPolicy("run_powershell", True, group="project", isolated=False),
        "full-access", True, False,
    ) == "ask"


def test_delete_tool_is_not_exposed_to_the_model():
    assert "delete_file" not in tool_names(project_active=True)


