import logging
import pkgutil
from importlib import import_module

from .registry import NEEDS_APPROVAL, REMEMBERABLE, SCOPES, TOOL_FUNCTIONS, TOOL_SCHEMAS

__all__ = ["NEEDS_APPROVAL", "REMEMBERABLE", "SCOPES", "TOOL_FUNCTIONS", "TOOL_SCHEMAS", "LOAD_ERRORS", "load_plugins"]

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
