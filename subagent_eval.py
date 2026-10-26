"""Compare local research tasks with and without the read-only delegate tool."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from agent import Agent
from config import settings
from subagent import LAST_RUN_METRICS, effective_tool_menu
from tools import TOOL_FUNCTIONS
from tools.delegate import register_delegate
from tools import workspace
from tools.registry import remove_tool

CASE_SYMBOLS = (
    ("rebuild_search_index", "module_17.py"),
    ("McpSupervisor", "module_08.py"),
    ("rollback_cancelled_turn", "module_31.py"),
)
FILLER_COUNT = 36


@dataclass(frozen=True)
class Score:
    case: str
    delegated: bool
    passed: bool
    peak_context: int
    total_tokens: int
    seconds: float
    pointers_verified: int
    pointers_dropped: int


def _make_project(root: Path, target_file: str, symbol: str) -> None:
    for index in range(FILLER_COUNT):
        path = root / f"module_{index:02d}.py"
        if path.name == target_file:
            if symbol == "McpSupervisor":
                content = f"class {symbol}:\n    pass\n"
            else:
                content = f"def {symbol}():\n    return None\n"
        else:
            content = f"def helper_{index}():\n    return 'project module {index}'\n"
        path.write_text(content, encoding="utf-8")


async def _case(symbol: str, expected_file: str, delegated: bool) -> Score:
    prior_workspace = workspace.WORKSPACE
    with tempfile.TemporaryDirectory(prefix="jinni-subagent-eval-") as temporary:
        root = Path(temporary).resolve()
        _make_project(root, expected_file, symbol)
        workspace.WORKSPACE = root
        try:
            if "delegate" in TOOL_FUNCTIONS:
                remove_tool("delegate")
            register_delegate(delegated)
            tools = effective_tool_menu()
            if delegated:
                tools.add("delegate")
            prompt = (
                f"Find the project file that defines {symbol}. Use the available read-only tools. "
                "Reply with only its path. Do not guess if the tools do not find it."
            )
            agent = Agent(
                project_active=True,
                system_prompt="You research a codebase carefully. Use tools before answering, and give a concise result.",
                tool_menu=tools,
                no_memory=True,
            )
            peak = 0
            started = time.perf_counter()
            agent.messages.append({"role": "user", "content": prompt})
            for _ in range(max(3, settings.max_steps)):
                content, calls, used = await agent.stream_response()
                peak = max(peak, used)
                if not calls:
                    agent.messages.append({"role": "assistant", "content": content})
                    break
                agent.messages.append({
                    "role": "assistant", "content": content,
                    "tool_calls": [{
                        "id": call.id, "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    } for call in calls],
                })
                results = await agent.run_tools(calls)
                for call, result in zip(calls, results):
                    agent.messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            else:
                content = ""
            elapsed = time.perf_counter() - started
            metrics = LAST_RUN_METRICS if delegated else {}
            child_tokens = int(metrics.get("total_tokens", 0)) if delegated else 0
            verified = int(metrics.get("verified", 0)) if delegated else 0
            dropped = int(metrics.get("dropped", 0)) if delegated else 0
            await agent.client.close()
            return Score(
                symbol, delegated, expected_file.casefold() in content.casefold(), peak,
                agent.stats["prompt_tokens"] + agent.stats["completion_tokens"] + child_tokens,
                elapsed, verified, dropped,
            )
        finally:
            workspace.WORKSPACE = prior_workspace


async def evaluate() -> list[Score]:
    scores = []
    for symbol, filename in CASE_SYMBOLS:
        scores.append(await _case(symbol, filename, False))
        scores.append(await _case(symbol, filename, True))
    return scores


def render(scores: list[Score]) -> str:
    lines = ["case | delegate | result | peak context | total tokens | seconds | pointers verified/dropped",
             "--- | --- | --- | ---: | ---: | ---: | ---:"]
    for score in scores:
        lines.append(
            f"{score.case} | {'on' if score.delegated else 'off'} | "
            f"{'pass' if score.passed else 'fail'} | {score.peak_context} | {score.total_tokens} | "
            f"{score.seconds:.1f} | {score.pointers_verified}/{score.pointers_dropped}"
        )
    for delegated in (False, True):
        group = [row for row in scores if row.delegated is delegated]
        if group:
            passed = sum(row.passed for row in group)
            lines.append(f"delegate {'on' if delegated else 'off'} pass rate: {passed}/{len(group)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        print(render(asyncio.run(evaluate())))
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(f"subagent evaluation failed: {type(error).__name__}: {error}")


if __name__ == "__main__":
    main()
