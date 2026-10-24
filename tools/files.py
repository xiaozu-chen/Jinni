from .registry import tool
from .workspace import mark_written, safe_path

MAX_READ = 4000


@tool(
    description="List files and folders inside a directory in the workspace folder.",
    params={"path": "Directory path relative to the workspace. Use '.' for the workspace root."},
)
def list_files(path: str = ".") -> str:
    try:
        folder = safe_path(path)
        return "\n".join(item.name for item in folder.iterdir()) or "(empty folder)"
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except Exception as e:
        return f"Error: {e}"


@tool(
    description="Read the text contents of a file in the workspace folder.",
    params={"path": "Path to the file, relative to the workspace."},
)
def read_file(path: str) -> str:
    try:
        return safe_path(path).read_text(encoding="utf-8")[:MAX_READ]
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except Exception as e:
        return f"Error: {e}"


@tool(
    description="Create a new file or completely overwrite one. For small changes to an existing file, use edit_file instead.",
    params={
        "path": "File path relative to the workspace.",
        "content": "The full text to write into the file.",
    },
    approval=True,
)
def write_file(path: str, content: str) -> str:
    try:
        full = safe_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        mark_written(full)
        return f"Wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    description="Replace one exact piece of text in an existing workspace file. old_text must match exactly once. Prefer this over write_file for small changes.",
    params={
        "path": "File path relative to the workspace.",
        "old_text": "The exact existing text to replace.",
        "new_text": "The text to put in its place.",
    },
    approval=True,
)
def edit_file(path: str, old_text: str, new_text: str) -> str:
    try:
        if not old_text:
            return "Error: old_text must not be empty."
        full = safe_path(path)
        text = full.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            return "Error: old_text was not found. Read the file again and copy the text exactly."
        if count > 1:
            return f"Error: old_text appears {count} times. Include more surrounding text so it matches once."
        full.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        mark_written(full)
        return f"Edited {path}: replaced 1 occurrence."
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except Exception as e:
        return f"Error: {e}"