"""Pure tool approval decisions and session-local untrusted-content tracking."""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from tools.registry import NEEDS_APPROVAL, TOOL_GROUPS

ApprovalMode = Literal["ask", "auto-edit", "full-access"]
Decision = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    requires_approval: bool
    group: str = "core"
    isolated: bool = False
    mcp_remembered: bool = False

AUTO_EDIT_TOOLS = frozenset({"write_file", "edit_file", "apply_patch"})
ISOLATED_COMMAND_TOOLS = frozenset({"run_tests", "run_powershell"})
TAINTING_TOOLS = frozenset({
    "fetch_url", "fetch_table", "web_search", "search_snippets_for_chart", "recall",
})
NEVER_AVAILABLE_TOOLS = frozenset({"delete_file"})
APPROVAL_TOOLS = frozenset({"run_powershell"})
FULL_ACCESS_BUDGET = 20
FULL_ACCESS_SECONDS = 30 * 60

FULL_ACCESS_WARNING = """FULL ACCESS skips eligible approval prompts for this session only.

Jinni can write and edit files inside the active managed project and use public web sources.
It remains blocked from files outside the project, private network addresses, unallowlisted
MCP tools, and deleting files. Isolated commands may run without an approval prompt.

Web pages, search results, remembered notes, and MCP results can contain malicious instructions.
As soon as one of those sources is used, Full Access turns off and approvals are required again.

Full Access expires after 20 tool calls or 30 minutes. Type FULL ACCESS to enable it; anything
else cancels."""

SESSION_TAINTED: ContextVar[bool] = ContextVar("jinni_session_tainted", default=False)


def describe_tool(name: str, *, mcp_remembered: bool = False) -> ToolPolicy:
    group = TOOL_GROUPS.get(name, "core")
    return ToolPolicy(
        name=name,
        requires_approval=name in NEEDS_APPROVAL or name in APPROVAL_TOOLS or group == "mcp",
        group=group,
        isolated=name in ISOLATED_COMMAND_TOOLS,
        mcp_remembered=mcp_remembered,
    )


def permission_decision(
    tool: ToolPolicy,
    mode: ApprovalMode | str,
    project: bool,
    tainted: bool,
) -> Decision:
    """Return allow/ask/deny without reading or changing session state."""
    if tool.name in NEVER_AVAILABLE_TOOLS:
        return "deny"
    group = tool.group
    if group == "project" and not project:
        return "deny"
    if not tool.requires_approval:
        return "allow"
    if tainted:
        return "ask"
    if mode == "ask":
        return "ask"
    if mode == "auto-edit":
        return "allow" if project and tool.name in AUTO_EDIT_TOOLS else "ask"
    if mode == "full-access":
        if group == "mcp":
            return "allow" if tool.mcp_remembered else "ask"
        if tool.name in {"remember", "forget"}:
            return "ask"
        if tool.name in ISOLATED_COMMAND_TOOLS:
            return "allow" if tool.isolated else "ask"
        return "allow"
    return "ask"


def taints_session(tool: ToolPolicy) -> bool:
    return tool.name in TAINTING_TOOLS or tool.group == "mcp"
