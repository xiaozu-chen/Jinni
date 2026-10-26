"""Append redacted tool-call decisions and provide a bounded recent-history view."""

import json
from datetime import datetime, timezone

from tools import workspace

AUDIT_DIR = "data/logs"
AUDIT_FILE = "audit.jsonl"
REDACTED_KEYS = {"content", "old_text", "new_text"}
MAX_AUDIT_ROWS = 5000
MAX_VIEW_ROWS = 100
MAX_ARGUMENT_RECORD_CHARS = 1000


def _safe_value(value, key: str = ""):
    lowered = key.lower()
    if lowered in REDACTED_KEYS or any(word in lowered for word in ("password", "secret", "token", "api_key")):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(name): _safe_value(item, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…[truncated]"
    return value


def _safe_arguments(arguments: dict):
    safe = _safe_value(arguments)
    encoded = json.dumps(safe, ensure_ascii=False, default=str)
    if len(encoded) > MAX_ARGUMENT_RECORD_CHARS:
        return {"summary": encoded[:MAX_ARGUMENT_RECORD_CHARS] + "…[truncated]"}
    return safe


def record_call(tool_name: str, arguments: dict, approval: str) -> None:
    folder = workspace.WORKSPACE / AUDIT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / AUDIT_FILE
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            if sum(1 for _ in stream) >= MAX_AUDIT_ROWS:
                raise OSError("the audit log reached its size limit")
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool_name,
        "approval": approval,
        "arguments": _safe_arguments(arguments),
    }
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def recent_calls(count: int = 20) -> str:
    if not 1 <= count <= MAX_VIEW_ROWS:
        return f"Error: choose between 1 and {MAX_VIEW_ROWS} audit entries."
    path = workspace.WORKSPACE / AUDIT_DIR / AUDIT_FILE
    if not path.is_file():
        return "(no approved tool calls recorded yet)"
    try:
        with path.open(encoding="utf-8") as stream:
            rows = stream.readlines()[-count:]
        entries = [json.loads(row) for row in rows]
    except (OSError, json.JSONDecodeError):
        return "Error: the audit log could not be read."
    if not entries:
        return "(no approved tool calls recorded yet)"
    return "\n".join(
        f"{entry.get('at', '?')} [{entry.get('approval', '?')}] "
        f"{entry.get('tool', '?')} {json.dumps(entry.get('arguments', {}), ensure_ascii=False)}"
        for entry in entries
    )
