import asyncio
import httpx
import pytest

from bench.eval_harness import EvalCase, load_cases, parse_menu_sizes, run_variant


def test_load_cases_checks_the_case_shape(tmp_path):
    cases_file = tmp_path / "cases.json"
    cases_file.write_text('[{"prompt":"Find files.","expected_tools":["find_files"]}]', encoding="utf-8")

    assert load_cases(cases_file) == [EvalCase("Find files.", ("find_files",))]

    cases_file.write_text('[{"prompt":"","expected_tools":[]}]', encoding="utf-8")
    with pytest.raises(ValueError, match="prompt and expected_tools"):
        load_cases(cases_file)


def test_parse_menu_sizes_accepts_all_and_rejects_bad_counts():
    assert parse_menu_sizes("2, all,2", 5) == [2, 5]
    with pytest.raises(ValueError, match="between 1 and 5"):
        parse_menu_sizes("6", 5)


def test_run_variant_scores_expected_calls_and_skips_unavailable_tools():
    request_bodies = []

    def respond(request):
        import json

        body = json.loads(request.content)
        request_bodies.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"function": {"name": "find_files"}}
        ]}}]})

    schemas = [
        {"type": "function", "function": {"name": "find_files"}},
        {"type": "function", "function": {"name": "list_files"}},
    ]
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="http://test/v1") as client:
            return await run_variant(
                client,
                [EvalCase("Find files.", ("find_files",)), EvalCase("List files.", ("list_files",))],
                model="fixture-model", thinking=True, menu_size=1,
                system_prompt="Be concise.", schemas=schemas,
            )

    results = asyncio.run(scenario())

    assert results[0].correct
    assert results[1].skipped
    assert len(request_bodies) == 1
    assert request_bodies[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert len(request_bodies[0]["tools"]) == 1
