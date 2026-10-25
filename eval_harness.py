"""Measure expected tool selection across local model and prompt variants."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config import settings
from tools import TOOL_SCHEMAS

DEFAULT_CASES = Path(__file__).with_name("eval_cases.json")


@dataclass(frozen=True)
class EvalCase:
    prompt: str
    expected_tools: tuple[str, ...]


@dataclass(frozen=True)
class EvalResult:
    variant: str
    prompt: str
    expected: tuple[str, ...]
    selected: tuple[str, ...]
    skipped: bool = False

    @property
    def correct(self) -> bool:
        return self.selected == self.expected


def load_cases(path: str | Path = DEFAULT_CASES) -> list[EvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("evaluation cases must be a non-empty JSON list")
    cases = []
    for item in raw:
        if (not isinstance(item, dict) or not isinstance(item.get("prompt"), str)
                or not item["prompt"].strip() or not isinstance(item.get("expected_tools"), list)
                or any(not isinstance(name, str) or not name for name in item["expected_tools"])):
            raise ValueError("each case needs a prompt and expected_tools list")
        cases.append(EvalCase(item["prompt"], tuple(item["expected_tools"])))
    return cases


def parse_menu_sizes(value: str, tool_count: int) -> list[int]:
    sizes = []
    for item in value.split(","):
        item = item.strip().lower()
        size = tool_count if item == "all" else int(item)
        if not 1 <= size <= tool_count:
            raise ValueError(f"menu size must be between 1 and {tool_count}, or 'all'")
        if size not in sizes:
            sizes.append(size)
    if not sizes:
        raise ValueError("provide at least one menu size")
    return sizes


async def run_variant(
    client: httpx.AsyncClient,
    cases: list[EvalCase],
    *,
    model: str,
    thinking: bool,
    menu_size: int,
    system_prompt: str,
    schemas: list[dict[str, Any]] | None = None,
) -> list[EvalResult]:
    schemas = TOOL_SCHEMAS if schemas is None else schemas
    menu = schemas[:menu_size]
    available = {schema["function"]["name"] for schema in menu}
    results = []
    label = f"{model} / thinking={'on' if thinking else 'off'} / tools={menu_size}"
    for case in cases:
        if any(name not in available for name in case.expected_tools):
            results.append(EvalResult(label, case.prompt, case.expected_tools, (), skipped=True))
            continue
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": case.prompt},
                ],
                "tools": menu,
                "tool_choice": "auto",
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": thinking},
            },
        )
        response.raise_for_status()
        body = response.json()
        calls = body["choices"][0]["message"].get("tool_calls") or []
        selected = tuple(call["function"]["name"] for call in calls)
        results.append(EvalResult(label, case.prompt, case.expected_tools, selected))
    return results


def render_results(results: list[EvalResult], server_context: int | None = None) -> str:
    groups: dict[str, list[EvalResult]] = {}
    for result in results:
        groups.setdefault(result.variant, []).append(result)
    lines = ["variant | score | selected tools"]
    lines.append("--- | ---: | ---")
    for variant, rows in groups.items():
        scored = [row for row in rows if not row.skipped]
        correct = sum(row.correct for row in scored)
        percent = 100 * correct / len(scored) if scored else 0
        lines.append(f"{variant} | {correct}/{len(scored)} ({percent:.0f}%) |")
        lines.extend(
            f"  {row.prompt} | {'skip' if row.skipped else 'pass' if row.correct else 'miss'} | "
            f"{', '.join(row.selected) or '(none)'}"
            for row in rows
        )
    if server_context is not None:
        lines.append(f"\nServer context label: {server_context} tokens (configure the local server to match).")
    return "\n".join(lines)


async def evaluate(args: argparse.Namespace) -> list[EvalResult]:
    cases = load_cases(args.cases)
    sizes = parse_menu_sizes(args.menu_sizes, len(TOOL_SCHEMAS))
    prompts = {"default": settings.system_prompt}
    if args.prompts:
        loaded = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in loaded.items()):
            raise ValueError("prompt file must be a JSON object mapping names to prompt text")
        prompts.update(loaded)

    results = []
    async with httpx.AsyncClient(base_url=settings.base_url, timeout=settings.request_timeout) as client:
        for model in args.models.split(","):
            for thinking in args.thinking.split(","):
                if thinking not in {"on", "off"}:
                    raise ValueError("thinking values must be on or off")
                for size in sizes:
                    for name, prompt in prompts.items():
                        rows = await run_variant(
                            client, cases, model=model.strip(), thinking=thinking == "on",
                            menu_size=size, system_prompt=prompt,
                        )
                        rows = [EvalResult(f"{name} / {row.variant}", row.prompt, row.expected, row.selected, row.skipped) for row in rows]
                        results.extend(rows)
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--models", default=settings.model, help="comma-separated model names")
    parser.add_argument("--thinking", default="off,on", help="comma-separated on/off values")
    parser.add_argument("--menu-sizes", default="8,all", help="comma-separated tool counts or 'all'")
    parser.add_argument("--prompts", type=Path, help="JSON object of named system prompt variants")
    parser.add_argument("--server-context", type=int, help="label a run; reconfigure the server to match")
    args = parser.parse_args(argv)
    if args.server_context is not None and args.server_context < 1:
        parser.error("--server-context must be positive")
    try:
        results = asyncio.run(evaluate(args))
    except (OSError, ValueError, httpx.HTTPError, KeyError, IndexError) as error:
        parser.error(f"evaluation failed: {type(error).__name__}: {error}")
    print(render_results(results, args.server_context))


if __name__ == "__main__":
    main()
