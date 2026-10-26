import asyncio
import json as jsonlib
from typing import Any, cast

import pytest

from coding_eval import (
    CodingCase,
    build_tools,
    execute_scratch_tool,
    load_cases,
    run_case,
    score_case,
)


def test_benchmark_has_five_small_tasks_and_file_only_tools():
    cases = load_cases()
    tools = build_tools(3)

    assert len(cases) == 5
    assert [tool["function"]["name"] for tool in tools] == ["read_file", "edit_file", "write_file"]
    assert all("shell" not in tool["function"]["name"] for tool in build_tools(5))


def test_scratch_file_tools_confine_paths_and_edit_exactly_once(tmp_path):
    (tmp_path / "app.py").write_text("answer = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stay inside"):
        execute_scratch_tool(tmp_path, "read_file", {"path": "../outside.py"})
    with pytest.raises(ValueError, match="exactly once"):
        execute_scratch_tool(tmp_path, "edit_file", {
            "path": "app.py", "old_text": "missing", "new_text": "fixed",
        })


def test_static_scoring_checks_source_conditions_and_python_syntax(tmp_path):
    case = CodingCase(
        name="simple", prompt="", files={},
        contains={"answer.py": ["answer = 42"]}, absent={}, ordered={},
    )
    (tmp_path / "answer.py").write_text("answer = 42\n", encoding="utf-8")

    assert score_case(tmp_path, case) == (True, "all source checks passed")

    (tmp_path / "answer.py").write_text("def broken(:\n", encoding="utf-8")
    passed, detail = score_case(tmp_path, case)
    assert not passed
    assert "invalid Python syntax" in detail


def test_run_case_applies_model_tool_calls_and_scores_in_scratch():
    case = CodingCase(
        name="limit", prompt="Fix the slice", files={"app.py": "items[:count + 1]"},
        contains={"app.py": ["items[:max(0, count)]"]},
        absent={"app.py": ["count + 1"]}, ordered={},
    )

    class Response:
        def __init__(self, message):
            self.message = message

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": self.message}]}

    class Client:
        def __init__(self):
            self.turn = 0

        async def post(self, _path, json):
            self.turn += 1
            if self.turn == 1:
                return Response({"tool_calls": [{
                    "id": "edit-1", "function": {
                        "name": "edit_file",
                        "arguments": jsonlib.dumps({
                            "path": "app.py", "old_text": "items[:count + 1]",
                            "new_text": "items[:max(0, count)]",
                        }),
                    },
                }]})
            return Response({"content": "done"})

    result = asyncio.run(run_case(cast(Any, Client()), case, model="fixture", thinking=False, menu_size=3))

    assert result.passed
    assert result.detail == "all source checks passed"
