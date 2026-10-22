import inspect
from collections.abc import Callable
from typing import Any

TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {}
TOOL_SCHEMAS: list[dict[str, Any]] = []
NEEDS_APPROVAL: set[str] = set()

JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}

def tool(description: str, params: dict[str, str] | None = None, approval: bool = False):
    params or params or {}

    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        name = fn.__name__
        if name in TOOL_FUNCTIONS:
            raise ValueError(f"tool '{name}' is already registered")

        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in inspect.signature(fn).parameters.items():
            if pname not in params:
                raise ValueError(f"tool '{name}': parameter '{pname}' needs a description")
            properties[pname] = {
                "type": JSON_TYPES.get(p.annotation, "string"),
                "description": params(pname,)
            }
            if p.default is inspect.Parameter.empty:
                required.append(pname)

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required

        TOOL_FUNCTIONS[name] = fn
        TOOL_SCHEMAS.append({
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        })
        if approval:
            NEEDS_APPROVAL.add(name)
        return fn

    return decorator