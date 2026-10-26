import logging
import pkgutil
from importlib import import_module

from .registry import (
    NEEDS_APPROVAL, REMEMBERABLE, SCOPES, SUBAGENT_SAFE, TOOL_FUNCTIONS, TOOL_GROUPS, TOOL_SCHEMAS,
    tool_names, tool_schemas,
)

__all__ = ["NEEDS_APPROVAL", "REMEMBERABLE", "SCOPES", "SUBAGENT_SAFE", "TOOL_FUNCTIONS", "TOOL_GROUPS", "TOOL_SCHEMAS", "tool_names", "tool_schemas", "LOAD_ERRORS", "load_plugins"]

log = logging.getLogger("jinni.tools")
SKIP = {"registry"}

def load_plugins() -> list[str]:
    errors: list[str] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        if info.name in SKIP or info.name.startswith("_"):
            continue
        try:
            import_module(f"{__name__}.{info.name}")
        except Exception as e:
            log.exception("could not load tool module %s", info.name)
            errors.append(f"{info.name}: {type(e).__name__}: {e}")
    return errors

LOAD_ERRORS = load_plugins()

from config import settings as _settings

if _settings.subagents_enabled:
    from subagent import effective_tool_menu

    effective_tool_menu()
