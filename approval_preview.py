import difflib
import json
import ast

from tools import workspace
from tools.workspace import safe_path

MAX_ARGUMENT_SUMMARY = 320
MAX_PREVIEW_BYTES = 100_000
MAX_PREVIEW_CHARS = 6_000
MAX_PREVIEW_LINES = 100


def summarize_arguments(arguments: dict, limit: int = MAX_ARGUMENT_SUMMARY) -> str:
    summary = json.dumps(arguments, ensure_ascii=False, default=str)
    return summary if len(summary) <= limit else summary[:limit] + "…[truncated]"


def change_preview(tool_name: str, arguments: dict) -> str | None:
    if tool_name not in ("write_file", "edit_file"):
        return None
    path = arguments.get("path")
    if not isinstance(path, str):
        return "Change preview unavailable: the path is invalid."
    try:
        full = safe_path(path)
        relative = full.relative_to(workspace.WORKSPACE).as_posix()
        if full.exists():
            if not full.is_file():
                return "Change preview unavailable: the target is not a file."
            if full.stat().st_size > MAX_PREVIEW_BYTES:
                return "Change preview unavailable: the existing file is too large."
            old = full.read_text(encoding="utf-8")
        else:
            old = ""
        if tool_name == "write_file":
            new = arguments.get("content")
            if not isinstance(new, str):
                return "Change preview unavailable: the new content is invalid."
            label = "overwrite" if full.exists() else "new file"
        else:
            old_text, new_text = arguments.get("old_text"), arguments.get("new_text")
            if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
                return "Change preview unavailable: the edit is invalid."
            count = old.count(old_text)
            if count != 1:
                return f"Change preview unavailable: the source text matches {count} times."
            new = old.replace(old_text, new_text, 1)
            label = "edit"
        diff = list(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"before/{relative}", tofile=f"after/{relative}", n=3,
        ))
        if not diff:
            return f"{label}: no text changes."
        output = "".join(diff)
        if len(diff) > MAX_PREVIEW_LINES or len(output) > MAX_PREVIEW_CHARS:
            output = "".join(diff[:MAX_PREVIEW_LINES])[:MAX_PREVIEW_CHARS]
            output += "\n[diff preview truncated]"
        heading = "Existing file will be overwritten." if tool_name == "write_file" and full.exists() else ""
        return f"{heading}\n{output.rstrip()}" if heading else output.rstrip()
    except Exception as error:
        return f"Change preview unavailable: {type(error).__name__}."


def validate_python_change(tool_name: str, arguments: dict) -> str | None:
    path = arguments.get("path")
    if not isinstance(path, str) or not path.lower().endswith(".py"):
        return None
    try:
        full = safe_path(path)
        if tool_name == "write_file":
            source = arguments.get("content")
        elif tool_name == "edit_file":
            old_text, new_text = arguments.get("old_text"), arguments.get("new_text")
            if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
                return None  # The file tool will give the more useful argument error.
            existing = full.read_text(encoding="utf-8")
            if existing.count(old_text) != 1:
                return None
            source = existing.replace(old_text, new_text, 1)
        else:
            return None
        if not isinstance(source, str):
            return None
        ast.parse(source, filename=path)
    except SyntaxError as error:
        return f"Error: Python syntax error on line {error.lineno}: {error.msg}."
    except (OSError, UnicodeError, ValueError):
        return None
    return None
