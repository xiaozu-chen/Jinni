"""Run small code-editing tasks in temporary folders without executing model output."""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config import settings

DEFAULT_CASES = Path(__file__).with_name("coding_eval_cases.json")
MAX_FILE_BYTES = 100_000
MAX_TOOL_CALLS = 20

TOOL_DEFINITIONS = [
    ("read_file", "Read a scratch project file", {"path": {"type": "string"}}, ["path"]),
    ("edit_file", "Replace exact text in a scratch project file", {
        "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
    }, ["path", "old_text", "new_text"]),
    ("write_file", "Write a scratch project file", {
        "path": {"type": "string"}, "content": {"type": "string"},
    }, ["path", "content"]),
    ("list_files", "List files in the scratch project", {}, []),
    ("search_files", "Search scratch project text", {"query": {"type": "string"}}, ["query"]),
]


@dataclass(frozen=True)
class CodingCase:
    name: str
    prompt: str
    files: dict[str, str]
    contains: dict[str, list[str]]
    absent: dict[str, list[str]]
    ordered: dict[str, list[str]]


@dataclass(frozen=True)
class CodingResult:
    case: str
    model: str
    thinking: bool
    menu_size: int
    passed: bool
    detail: str


def load_cases(path: str | Path = DEFAULT_CASES) -> list[CodingCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not 5 <= len(raw) <= 10:
        raise ValueError("coding eval must contain 5 to 10 cases")
    cases = []
    for item in raw:
        if (not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key]
                for key in ("name", "prompt")) or not isinstance(item.get("files"), dict)
                or not item["files"] or any(not isinstance(k, str) or not isinstance(v, str)
                for k, v in item["files"].items())):
            raise ValueError("each coding case needs a name, prompt, and text files")
        for key in ("contains", "absent", "ordered"):
            checks = item.get(key, {})
            if (not isinstance(checks, dict) or any(
                    not isinstance(file, str) or not isinstance(values, list)
                    or any(not isinstance(value, str) for value in values)
                    for file, values in checks.items())):
                raise ValueError(f"case {item['name']} has invalid {key} checks")
        cases.append(CodingCase(
            item["name"], item["prompt"], item["files"], item.get("contains", {}),
            item.get("absent", {}), item.get("ordered", {}),
        ))
    return cases


def build_tools(count: int) -> list[dict[str, Any]]:
    tools = [{
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, **({"required": required} if required else {})},
        },
    } for name, description, properties, required in TOOL_DEFINITIONS]
    if not 1 <= count <= len(tools):
        raise ValueError(f"tool count must be between 1 and {len(tools)}")
    return tools[:count]


def _safe_file(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or any(part in {".", "..", ".git", ".jinni"} for part in relative.parts):
        raise ValueError("path must stay inside the scratch project")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symbolic links are not allowed")
    path = candidate.resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path must stay inside the scratch project")
    return path


def execute_scratch_tool(root: Path, name: str, arguments: dict[str, Any]) -> str:
    if name == "list_files":
        return "\n".join(sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())) or "(empty)"
    if name == "search_files":
        query = arguments.get("query")
        if not isinstance(query, str) or not query:
            raise ValueError("query must be non-empty text")
        matches = []
        for path in root.rglob("*"):
            if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
                text = path.read_text(encoding="utf-8")
                matches.extend(f"{path.relative_to(root).as_posix()}:{line_no}: {line[:200]}"
                               for line_no, line in enumerate(text.splitlines(), 1) if query.casefold() in line.casefold())
        return "\n".join(matches[:100]) or "(no matches)"

    path = _safe_file(root, arguments.get("path", ""))
    if name == "read_file":
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("file is missing or too large")
        return path.read_text(encoding="utf-8")
    if name == "write_file":
        content = arguments.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("file content is invalid or too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return "file written"
    if name == "edit_file":
        old, new = arguments.get("old_text"), arguments.get("new_text")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ValueError("old_text and new_text must be strings, and old_text cannot be empty")
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("file is missing or too large")
        content = path.read_text(encoding="utf-8")
        if content.count(old) != 1:
            raise ValueError("old_text must match exactly once")
        path.write_text(content.replace(old, new), encoding="utf-8")
        return "file edited"
    raise ValueError("tool is not available in the coding eval")


def score_case(root: Path, case: CodingCase) -> tuple[bool, str]:
    errors = []
    for filename, values in case.contains.items():
        path = _safe_file(root, filename)
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        errors.extend(f"{filename} is missing {value!r}" for value in values if value not in content)
    for filename, values in case.absent.items():
        path = _safe_file(root, filename)
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        errors.extend(f"{filename} still contains {value!r}" for value in values if value in content)
    for filename, values in case.ordered.items():
        path = _safe_file(root, filename)
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        positions = [content.find(value) for value in values]
        if any(position < 0 for position in positions) or positions != sorted(positions):
            errors.append(f"{filename} does not contain the required structure in order")
    for path in root.rglob("*.py"):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            errors.append(f"{path.relative_to(root).as_posix()} has invalid Python syntax: {type(error).__name__}")
    return not errors, "; ".join(errors) if errors else "all source checks passed"


async def run_case(
    client: httpx.AsyncClient,
    case: CodingCase,
    *,
    model: str,
    thinking: bool,
    menu_size: int,
) -> CodingResult:
    tools = build_tools(menu_size)
    with tempfile.TemporaryDirectory(prefix="jinni-coding-eval-") as temporary:
        root = Path(temporary).resolve()
        for name, content in case.files.items():
            path = _safe_file(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Complete the coding task using only the provided scratch-file tools. Do not run commands or claim success without editing the files."},
            {"role": "user", "content": case.prompt},
        ]
        available_tools = {tool["function"]["name"] for tool in tools}
        calls_made = 0
        try:
            while calls_made < MAX_TOOL_CALLS:
                response = await client.post("/chat/completions", json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": thinking},
                })
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
                calls = message.get("tool_calls") or []
                messages.append({
                    "role": "assistant", "content": message.get("content"), "tool_calls": calls,
                })
                if not calls:
                    break
                for call in calls:
                    calls_made += 1
                    function = call["function"]
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be an object")
                        tool_name = function["name"]
                        if tool_name not in available_tools:
                            raise ValueError("tool is not included in this evaluation menu")
                        output = execute_scratch_tool(root, tool_name, arguments)
                    except (KeyError, json.JSONDecodeError, OSError, UnicodeError, ValueError) as error:
                        output = f"Error: {type(error).__name__}: {error}"
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": output})
                    if calls_made >= MAX_TOOL_CALLS:
                        break
            passed, detail = score_case(root, case)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            passed, detail = False, f"model request failed: {type(error).__name__}"
        return CodingResult(case.name, model, thinking, menu_size, passed, detail)


async def evaluate(args: argparse.Namespace) -> list[CodingResult]:
    cases = load_cases(args.cases)
    tools = build_tools(len(TOOL_DEFINITIONS))
    sizes = []
    for value in args.tool_counts.split(","):
        size = len(tools) if value.strip().lower() == "all" else int(value)
        if size not in sizes:
            build_tools(size)
            sizes.append(size)
    if not sizes:
        raise ValueError("provide at least one tool count")
    thinking_values = [value.strip().lower() for value in args.thinking.split(",")]
    if not thinking_values or any(value not in {"on", "off"} for value in thinking_values):
        raise ValueError("thinking values must be on or off")
    results = []
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=settings.request_timeout) as client:
        for model in (name.strip() for name in args.models.split(",") if name.strip()):
            for thinking in dict.fromkeys(thinking_values):
                for menu_size in sizes:
                    for case in cases:
                        results.append(await run_case(
                            client, case, model=model, thinking=thinking == "on", menu_size=menu_size,
                        ))
    return results


def render_results(results: list[CodingResult]) -> str:
    groups: dict[tuple[str, bool, int], list[CodingResult]] = {}
    for result in results:
        groups.setdefault((result.model, result.thinking, result.menu_size), []).append(result)
    lines = ["model | thinking | tools | score", "--- | --- | ---: | ---:"]
    for (model, thinking, menu), rows in groups.items():
        passed = sum(row.passed for row in rows)
        lines.append(f"{model} | {'on' if thinking else 'off'} | {menu} | {passed}/{len(rows)}")
        lines.extend(f"  {row.case}: {'pass' if row.passed else 'fail'} ({row.detail})" for row in rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--models", default=settings.model, help="comma-separated local model names")
    parser.add_argument("--thinking", default="off,on", help="comma-separated on/off values")
    parser.add_argument("--tool-counts", default="3,all", help="comma-separated tool counts or 'all'")
    args = parser.parse_args(argv)
    try:
        print(render_results(asyncio.run(evaluate(args))))
    except (OSError, ValueError, httpx.HTTPError, json.JSONDecodeError) as error:
        parser.error(f"coding evaluation failed: {type(error).__name__}: {error}")


if __name__ == "__main__":
    main()
