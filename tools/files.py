"""Provide project-confined file discovery, reads, edits, patches, and reversible deletes."""

import ast
import fnmatch
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from .registry import tool
from . import workspace as workspace_tools
from .provenance import write_typed_csv_provenance
from patching import apply_exact_patches
from .workspace import mark_written, safe_path

MAX_READ = 4000
MAX_RANGE_LINES = 200
MAX_RANGE_READ = 12000
MAX_SCAN_FILES = 1000
MAX_FIND_ENTRIES = 200
MAX_FILE_BYTES = 1_000_000
MAX_SEARCH_HITS = 50
MAX_PATTERN_CHARS = 256
MAX_DEPTH = 10
MAX_OUTPUT_CHARS = 12000
MAX_PATCH_FILE_BYTES = 1_000_000
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".trash", ".jinni"}
log = logging.getLogger("jinni.tools.files")


def _mark_typed_csv(path: Path) -> str:
    if path.suffix.lower() != ".csv":
        return ""
    try:
        write_typed_csv_provenance(path, path.read_bytes())
    except OSError:
        log.exception("could not save typed-data provenance for %s", path.name)
        return " (warning: its typed-data marker could not be saved)"
    return ""


def _workspace_entries(base: Path, max_depth: int = MAX_DEPTH):
    entries = []
    truncated = False
    for root, dirs, files in os.walk(base, followlinks=False):
        folder = Path(root)
        depth = len(folder.relative_to(base).parts)
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIRS and not (folder / name).is_symlink()
        )
        if depth >= max_depth:
            if dirs:
                truncated = True
            dirs[:] = []
        for name in dirs + sorted(files):
            path = folder / name
            if path.is_symlink():
                continue
            if len(entries) >= MAX_SCAN_FILES:
                return entries, True
            entries.append(path)
    return entries, truncated


def _bounded_output(lines: list[str], capped: bool = False) -> str:
    output = "\n".join(lines)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS]
        capped = True
    if capped:
        output += "\n[output capped]"
    return output


def _valid_pattern(pattern: str) -> str | None:
    if not pattern or len(pattern) > MAX_PATTERN_CHARS:
        return "the pattern must contain 1 to 256 characters"
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return "absolute patterns are not allowed"
    if ".." in normalized.split("/"):
        return "parent-folder patterns are not allowed"
    return None


@tool(
    description="List files and folders inside a directory in the workspace folder.",
    params={"path": "Directory path relative to the workspace. Use '.' for the workspace root."},
    group="project",
)
def list_files(path: str = ".") -> str:
    try:
        folder = safe_path(path)
        return "\n".join(item.name for item in folder.iterdir()) or "(empty folder)"
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, ValueError) as e:
        log.warning("list_files could not list %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Read a text file in the workspace; ranged reads include line numbers and are capped.",
    params={
        "path": "Path to the file, relative to the workspace.",
        "start": "Optional first line number (1-based). Leave 0 for the original beginning-of-file read.",
        "end": "Optional last line number (inclusive). Leave 0 to read up to 200 lines from start.",
    },
    group="project",
    subagent_safe=True,
)
def read_file(path: str, start: int = 0, end: int = 0) -> str:
    try:
        full = safe_path(path)
        if start == 0 and end == 0:
            with full.open(encoding="utf-8") as stream:
                return stream.read(MAX_READ)
        if start < 1 or end < 0 or (end and end < start):
            return "Error: ranged reads need start >= 1 and end = 0 or end >= start."
        last = end or start + MAX_RANGE_LINES - 1
        if last - start + 1 > MAX_RANGE_LINES:
            return f"Error: a ranged read can return at most {MAX_RANGE_LINES} lines."
        selected = []
        with full.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if number < start:
                    continue
                if number > last:
                    break
                selected.append(f"{number}: {line.rstrip()}\n")
        output = "".join(selected)
        if len(output) > MAX_RANGE_READ:
            return output[:MAX_RANGE_READ] + "\n[output truncated]"
        return output
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, UnicodeError, ValueError) as e:
        log.warning("read_file could not read %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Search text or regular expressions in small text files under a workspace directory. Results include file, line number, and a short snippet; output is capped.",
    params={
        "query": "Text to search for, or a regular expression when regex is true.",
        "path": "Workspace directory to search, defaulting to the workspace root.",
        "regex": "Set true to treat query as a regular expression; false searches literal text.",
    },
    group="project",
    subagent_safe=True,
)
def search_files(query: str, path: str = ".", regex: bool = False) -> str:
    if not query.strip():
        return "Error: search text must not be empty."
    if len(query) > MAX_PATTERN_CHARS:
        return f"Error: search text is limited to {MAX_PATTERN_CHARS} characters."
    try:
        folder = safe_path(path)
        if not folder.is_dir():
            return f"Error: '{path}' is not a workspace directory."
        matcher = None
        if regex:
            quantifiers = re.findall(r"(?<!\\)[*+?]|\{", query)
            repeats = re.findall(r"\{(\d+)(?:,(\d*))?\}", query)
            oversized_repeat = any(
                int(upper or lower) > 1000 for lower, upper in repeats
            )
            if (len(quantifiers) > 12 or oversized_repeat or re.search(r"\\[1-9]", query)
                    or re.search(r"\([^)]*[*+?{][^)]*\)[*+?{]", query)):
                return "Error: this regular expression is too complex to search safely."
            try:
                matcher = re.compile(query, re.IGNORECASE)
            except re.error as e:
                return f"Error: invalid regular expression ({e})."
        query_folded = query.casefold()
        hits = []
        entries, scan_capped = _workspace_entries(folder)
        for file in entries:
            if not file.is_file():
                continue
            try:
                with file.open("rb") as stream:
                    content = stream.read(MAX_FILE_BYTES + 1)
                if len(content) > MAX_FILE_BYTES or b"\x00" in content:
                    continue
                for number, line in enumerate(content.decode("utf-8").splitlines(), 1):
                    found = matcher.search(line) if matcher else query_folded in line.casefold()
                    if found:
                        relative = file.relative_to(folder).as_posix()
                        snippet = " ".join(line.strip().split())[:160]
                        hits.append(f"{relative}:{number}: {snippet}")
                        if len(hits) >= MAX_SEARCH_HITS:
                            return _bounded_output(hits, capped=True)
            except (OSError, UnicodeError):
                continue
        if not hits:
            hits = ["No matches found."]
        return _bounded_output(hits, capped=scan_capped)
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, ValueError) as e:
        log.warning("search_files could not search %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Find files and folders by glob pattern under a workspace directory. Search depth and result count are capped.",
    params={
        "pattern": "Glob such as '*.py' or '**/*.md'.",
        "path": "Workspace directory to search, defaulting to the workspace root.",
    },
    group="project",
    subagent_safe=True,
)
def find_files(pattern: str, path: str = ".") -> str:
    pattern_error = _valid_pattern(pattern)
    if pattern_error:
        return f"Error: {pattern_error}."
    try:
        folder = safe_path(path)
        if not folder.is_dir():
            return f"Error: '{path}' is not a workspace directory."
        found = []
        entries, scan_capped = _workspace_entries(folder)
        for entry in entries:
            relative = entry.relative_to(folder).as_posix()
            matched = fnmatch.fnmatchcase(relative, pattern.replace("\\", "/"))
            if not matched and pattern.startswith("**/"):
                matched = fnmatch.fnmatchcase(relative, pattern[3:].replace("\\", "/"))
            if matched:
                found.append(relative)
                if len(found) == MAX_FIND_ENTRIES:
                    return _bounded_output(found, capped=True)
        if not found:
            found = ["No files found."]
        return _bounded_output(found, capped=scan_capped)
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, ValueError) as e:
        log.warning("find_files could not scan %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Show classes and functions declared in a Python file, with line numbers.",
    params={"path": "Python file path relative to the workspace."},
    group="project",
    subagent_safe=True,
)
def code_outline(path: str) -> str:
    try:
        full = safe_path(path)
        if full.stat().st_size > MAX_FILE_BYTES:
            return f"Error: files larger than {MAX_FILE_BYTES // 1000} KB are not outlined."
        source = full.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=full.name)
        entries = [
            (node.lineno, "class" if isinstance(node, ast.ClassDef) else "function", node.name)
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        entries.sort()
        output = [f"{line}: {kind} {name}" for line, kind, name in entries]
        return _bounded_output(output or ["No classes or functions found."], capped=len(output) > MAX_SCAN_FILES)
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except SyntaxError as e:
        return f"Error: syntax error on line {e.lineno}: {e.msg}"
    except (OSError, UnicodeError, ValueError) as e:
        log.warning("code_outline could not read %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Show a bounded tree of workspace files and folders.",
    params={
        "path": "Workspace directory to show, defaulting to the workspace root.",
        "max_depth": "Maximum folder depth, from 1 to 8.",
        "max_entries": "Maximum entries to show, from 1 to 500.",
    },
    group="project",
    subagent_safe=True,
)
def project_tree(path: str = ".", max_depth: int = 3, max_entries: int = 300) -> str:
    if not 1 <= max_depth <= 8 or not 1 <= max_entries <= 500:
        return "Error: max_depth must be 1 to 8 and max_entries must be 1 to 500."
    try:
        folder = safe_path(path)
        if not folder.is_dir():
            return f"Error: '{path}' is not a workspace directory."
        lines = ["."]
        remaining = max_entries
        truncated = False

        def visit(directory: Path, depth: int) -> None:
            nonlocal remaining, truncated
            if depth >= max_depth or remaining <= 0:
                return
            entries = []
            with os.scandir(directory) as scan:
                for item in scan:
                    entries.append(item)
                    if len(entries) > max_entries:
                        truncated = True
                        break
            entries.sort(key=lambda item: (not item.is_dir(follow_symlinks=False), item.name.casefold()))
            for item in entries:
                if remaining <= 0:
                    truncated = True
                    return
                if item.is_symlink() or (item.is_dir(follow_symlinks=False) and item.name in SKIP_DIRS):
                    continue
                is_directory = item.is_dir(follow_symlinks=False)
                lines.append(f"{'  ' * depth}{item.name}{'/' if is_directory else ''}")
                remaining -= 1
                if is_directory:
                    visit(item, depth + 1)

        visit(folder, 0)
        return _bounded_output(lines, capped=truncated or remaining == 0)
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, ValueError) as e:
        log.warning("project_tree could not scan %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Create a new file or completely overwrite one. For small changes to an existing file, use edit_file instead.",
    params={
        "path": "File path relative to the workspace.",
        "content": "The full text to write into the file.",
    },
    approval=True,
    group="project",
)
def write_file(path: str, content: str) -> str:
    try:
        full = safe_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        mark_written(full)
        marker_note = _mark_typed_csv(full)
        return f"Wrote {len(content)} characters to {path}{marker_note}"
    except (OSError, UnicodeError, ValueError) as e:
        log.warning("write_file could not write %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Replace one exact piece of text in an existing workspace file. old_text must match exactly once. Prefer this over write_file for small changes.",
    params={
        "path": "File path relative to the workspace.",
        "old_text": "The exact existing text to replace.",
        "new_text": "The text to put in its place.",
    },
    approval=True,
    group="project",
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
        updated = text.replace(old_text, new_text, 1)
        full.write_text(updated, encoding="utf-8")
        mark_written(full)
        marker_note = _mark_typed_csv(full)
        return f"Edited {path}: replaced 1 occurrence.{marker_note}"
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, UnicodeError, ValueError) as e:
        log.warning("edit_file could not edit %s: %s", path, e)
        return f"Error: {e}"


@tool(
    description="Apply several exact replacements to one existing file as a single validated change. Every old_text must match exactly once, and no file is written unless all patches pass validation.",
    params={
        "path": "Existing file path relative to the workspace.",
        "patches": {
            "type": "array",
            "description": "One to 20 non-overlapping replacements.",
            "items": {
                "type": "object",
                "properties": {
                    "old_text": {"type": "string", "description": "Exact source text to find once."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    approval=True,
    group="project",
)
def apply_patch(path: str, patches: list[dict[str, str]]) -> str:
    """Validate all exact source ranges first; replace the file only if every patch fits."""
    try:
        full = safe_path(path)
        if not full.is_file():
            return f"Error: '{path}' was not found as a file in the workspace."
        if full.stat().st_size > MAX_PATCH_FILE_BYTES:
            return f"Error: files larger than {MAX_PATCH_FILE_BYTES // 1000} KB cannot be patched."
        original = full.read_text(encoding="utf-8")
        updated = apply_exact_patches(original, patches)
        if full.suffix.lower() == ".py":
            ast.parse(updated, filename=str(full))
        if updated == original:
            return f"No changes needed in {path}."

        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=full.parent,
                prefix=f".{full.name}.", suffix=".patch", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(updated)
            os.replace(temporary, full)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        mark_written(full)
        marker_note = _mark_typed_csv(full)
        return f"Applied {len(patches)} patch(es) to {path}.{marker_note}"
    except SyntaxError as error:
        return f"Error: Python syntax error on line {error.lineno}: {error.msg}."
    except FileNotFoundError:
        return f"Error: '{path}' was not found in the workspace."
    except (OSError, UnicodeError, ValueError) as error:
        log.warning("apply_patch could not patch %s: %s", path, error)
        return f"Error: {error}"


@tool(
    description="Move one workspace file into .trash instead of permanently deleting it.",
    params={"path": "File path relative to the workspace."},
    approval=True,
    group="project",
)
def delete_file(path: str) -> str:
    try:
        candidate = workspace_tools.WORKSPACE / path
        if candidate.is_symlink():
            return "Error: symbolic links cannot be moved to trash."
        full = safe_path(path)
        if not full.is_file():
            return f"Error: '{path}' is not a file in the workspace."
        relative = full.relative_to(workspace_tools.WORKSPACE)
        if relative.parts[0] in (".trash", ".jinni"):
            return "Error: files in the trash or Jinni data folder cannot be moved."
        target = safe_path(f".trash/{relative.as_posix()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stem, suffix = target.stem, target.suffix
            index = 1
            while target.exists():
                target = target.with_name(f"{stem}-{index}{suffix}")
                index += 1
        shutil.move(str(full), str(target))
        return f"Moved {path} to .trash/{relative.as_posix()}"
    except (OSError, ValueError, shutil.Error) as e:
        log.warning("delete_file could not move %s to trash: %s", path, e)
        return f"Error: {e}"
