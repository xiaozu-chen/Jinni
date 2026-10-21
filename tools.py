from datetime import datetime
from pathlib import Path

WORKSPACE = Path("workspace").resolve()
WORKSPACE.mkdir(exist_ok=True)

MAX_READ = 4000

def safe_path(path):
    full = (WORKSPACE / path).resolve()
    if not full.is_relative_to(WORKSPACE):
        raise ValueError("path is outside the workspace")
    return full

def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def list_files(path="."):
    try:
        folder = safe_path(path)
        return "\n".join(item.name for item in folder.iterdir()) or "(empty folder)"
    except Exception as e:
        return f"Error: {e}"

def read_file(path):
    try:
        return safe_path(path).read_text(encoding="utf-8")[:MAX_READ]
    except Exception as e:
        return f"Error: {e}"

def write_file(path, content):
    try:
        full = safe_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} characters to {path}"
    except Exception as e:
        return f"Error: {e}"

TOOL_FUNCTIONS = {
    "get_current_time": get_current_time,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
}

NEEDS_APPROVAL = {"write_file"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and folders inside a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path. Use '.' for current folder."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a text file in the workspace folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the workspace."},
                    "content": {"type": "string", "description": "The full text to write into the file."}
                },
                "required": ["path", "content"]
            },
        },
    },
]