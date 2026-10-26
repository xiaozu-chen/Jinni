import inspect
from collections.abc import Callable
from typing import Any

TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {}
TOOL_SCHEMAS: list[dict[str, Any]] = []
NEEDS_APPROVAL: set[str] = set()
REMEMBERABLE: set[str] = set()

ScopeFn = Callable[[dict[str, Any]], str]
SCOPES: dict[str, ScopeFn] = {}

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def add_tool(name: str, 
             fn: Callable[..., Any], 
             description: str, 
             parameters: dict[str, Any], 
             approval: bool = False, 
             remember: bool = False) -> None:
    #
    if name in TOOL_FUNCTIONS:
        raise ValueError(f"tool '{name}' is already registered")
    TOOL_FUNCTIONS[name] = fn
    TOOL_SCHEMAS.append({
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    })
    if approval:
        NEEDS_APPROVAL.add(name)
    if remember:
        REMEMBERABLE.add(name)


def remove_tool(name: str) -> None:
    TOOL_FUNCTIONS.pop(name, None)
    NEEDS_APPROVAL.discard(name)
    REMEMBERABLE.discard(name)
    SCOPES.pop(name, None)
    TOOL_SCHEMAS[:] = [s for s in TOOL_SCHEMAS if s["function"]["name"] != name]


def tool(description: str, 
             params: dict[str, Any] | None = None,
         approval: bool = False, 
         remember: bool = False, 
         scope: ScopeFn | None = None):
    #
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

        add_tool(name, fn, description, schema, approval, remember)
        if scope:
            SCOPES[name] = scope
        return fn

    return decorator


