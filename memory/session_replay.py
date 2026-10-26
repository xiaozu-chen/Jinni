"""Record and compare model tool choices without replaying tool side effects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from settings.config import settings

MAX_CASE_BYTES = 2_000_000


def replay_path(workspace: str | Path, name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise ValueError("use a replay name with letters, numbers, _ or -")
    root = Path(workspace).resolve()
    folder = (root / ".jinni" / "replays").resolve()
    if not folder.is_relative_to(root):
        raise ValueError("replay folder must stay inside the workspace")
    target = folder / f"{name}.jsonl"
    if target.is_symlink():
        raise ValueError("replay file cannot be a symbolic link")
    return target


@dataclass(frozen=True)
class ReplayResult:
    expected: tuple[str, ...]
    selected: tuple[str, ...]

    @property
    def correct(self) -> bool:
        return self.expected == self.selected


class SessionRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")

    def record(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], expected: list[str]) -> None:
        row = {"version": 1, "messages": messages, "tools": tools, "expected_tools": expected}
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_CASE_BYTES:
            return
        self._file.write(encoded + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def load_replay(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if source.stat().st_size > 50_000_000:
        raise ValueError("replay file exceeds 50 MB")
    rows = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > MAX_CASE_BYTES:
            raise ValueError(f"replay line {number} exceeds 2 MB")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"replay line {number} is invalid JSON") from error
        if (not isinstance(row, dict) or row.get("version") != 1
                or not isinstance(row.get("messages"), list)
                or not isinstance(row.get("tools"), list)
                or not isinstance(row.get("expected_tools"), list)
                or any(not isinstance(name, str) for name in row["expected_tools"])):
            raise ValueError(f"replay line {number} has an invalid session case")
        rows.append(row)
    if not rows:
        raise ValueError("replay file contains no recorded model requests")
    return rows


async def replay_session(
    path: str | Path,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
) -> list[ReplayResult]:
    rows = load_replay(path)
    results = []
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=settings.request_timeout) as client:
        for row in rows:
            messages = list(row["messages"])
            if system_prompt is not None:
                system = next((item for item in messages if item.get("role") == "system"), None)
                if system is None:
                    messages.insert(0, {"role": "system", "content": system_prompt})
                else:
                    system["content"] = system_prompt
            response = await client.post("/chat/completions", json={
                "model": model or settings.model,
                "messages": messages,
                "tools": row["tools"],
                "tool_choice": "auto",
                "stream": False,
            })
            response.raise_for_status()
            calls = response.json()["choices"][0]["message"].get("tool_calls") or []
            selected = tuple(call["function"]["name"] for call in calls)
            results.append(ReplayResult(tuple(row["expected_tools"]), selected))
    return results


def render_replay(results: list[ReplayResult]) -> str:
    correct = sum(result.correct for result in results)
    lines = [f"Replay tool choice: {correct}/{len(results)} matched"]
    lines.extend(
        f"  {'match' if row.correct else 'changed'}: expected {', '.join(row.expected) or '(no tools)'}; "
        f"selected {', '.join(row.selected) or '(no tools)'}"
        for row in results
    )
    return "\n".join(lines)
