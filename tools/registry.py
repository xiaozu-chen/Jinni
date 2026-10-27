"""Register tool functions, model schemas, approval policy, and project visibility."""

import inspect
from collections.abc import Callable
from typing import Any

TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {}
TOOL_SCHEMAS: list[dict[str, Any]] = []
NEEDS_APPROVAL: set[str] = set()
REMEMBERABLE: set[str] = set()
TOOL_GROUPS: dict[str, str] = {}
SUBAGENT_SAFE: set[str] = set()

ScopeFn = Callable[[dict[str, Any]], str]
SCOPES: dict[str, ScopeFn] = {}

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


CHAT_WORKSPACE_TOOLS = frozenset({
    "list_files", "read_file", "search_files", "find_files", "write_file",
    "edit_file", "apply_patch", "delete_file", "make_chart", "fetch_table",
    "search_snippets_for_chart", "search_workspace_files",
})


def tool_names(project_active: bool | None = None, workspace_kind: str = "project") -> set[str]:
    visible = {
        name for name in TOOL_FUNCTIONS
        if name != "delete_file"
        if project_active is not False or TOOL_GROUPS.get(name, "core") != "project"
    }
    if workspace_kind == "chat":
        visible = {
            name for name in visible
            if TOOL_GROUPS.get(name, "core") != "project" or name in CHAT_WORKSPACE_TOOLS
        }
        visible |= CHAT_WORKSPACE_TOOLS & TOOL_FUNCTIONS.keys()
        # Chat workspaces are for research and artifacts, not executing project commands.
        visible -= {"run_tests", "run_powershell"}
    return visible


def tool_schemas(
    project_active: bool | None = None,
    names: set[str] | None = None,
    workspace_kind: str = "project",
) -> list[dict[str, Any]]:
    visible = tool_names(project_active, workspace_kind)
    if names is not None:
        visible &= names
    return [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in visible]


def add_tool(name: str, 
             fn: Callable[..., Any], 
             description: str, 
             parameters: dict[str, Any], 
             approval: bool = False, 
             remember: bool = False,
             group: str = "core",
             subagent_safe: bool = False,
             scope: ScopeFn | None = None) -> None:
    """Keep the function, schema, group, and approval sets in sync as one registration."""
    if remember and not approval:
        raise ValueError("remember=True only makes sense together with approval=True")
    if scope and not remember:
        raise ValueError("scope only makes sense together with remember=True")
    if name in TOOL_FUNCTIONS:
        raise ValueError(f"tool '{name}' is already registered")
    TOOL_FUNCTIONS[name] = fn
    TOOL_SCHEMAS.append({
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    })
    TOOL_GROUPS[name] = group
    if approval:
        NEEDS_APPROVAL.add(name)
    if remember:
        REMEMBERABLE.add(name)
    if scope:
        SCOPES[name] = scope
    if subagent_safe and not approval:
        SUBAGENT_SAFE.add(name)


def remove_tool(name: str) -> None:
    TOOL_FUNCTIONS.pop(name, None)
    NEEDS_APPROVAL.discard(name)
    REMEMBERABLE.discard(name)
    SCOPES.pop(name, None)
    TOOL_GROUPS.pop(name, None)
    SUBAGENT_SAFE.discard(name)
    TOOL_SCHEMAS[:] = [s for s in TOOL_SCHEMAS if s["function"]["name"] != name]


def tool(description: str, 
             params: dict[str, Any] | None = None,
         approval: bool = False, 
         remember: bool = False, 
         scope: ScopeFn | None = None,
         group: str = "core",
         subagent_safe: bool = False):
    """Turn a documented Python function into a model-visible schema entry."""
    if remember and not approval:
        raise ValueError("remember=True only make sense together with approval=True")
    if scope and not remember:
        raise ValueError("scope only makes sense together with remember=True")
    params = params or {}

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        name = fn.__name__
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in inspect.signature(fn).parameters.items():
            if pname not in params:
                raise ValueError(f"tool '{name}': parameter '{pname}' needs a description")
            parameter_spec = params[pname]
            if isinstance(parameter_spec, dict):
                properties[pname] = parameter_spec
            else:
                properties[pname] = {
                    "type": JSON_TYPES.get(p.annotation, "string"),
                    "description": parameter_spec,
                }
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required

        add_tool(name, fn, description, schema, approval, remember, group, subagent_safe, scope)
        return fn

    return decorator


