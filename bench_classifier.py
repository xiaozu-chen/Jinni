"""Measure how well the configured small model routes requests to thinking on/off."""

from __future__ import annotations

import argparse
import asyncio
import time

from openai import AsyncOpenAI

from config import settings
from thinking_classifier import (
    THINKING_CLASSIFIER_PROMPT, THINKING_CLASSIFIER_SCHEMA, parse_thinking_label,
)

PROMPTS = (
    ("on", "Review this Python function for a race condition, explain the interleavings, and suggest a fix."),
    ("on", "Plan a backward-compatible database migration while the service continues reading and writing."),
    ("on", "These logs show a latency spike followed by timeouts. Find the likely cause and outline how to confirm it."),
    ("on", "Compare these API designs against the requirements and recommend one, explaining the tradeoffs."),
    ("on", "Derive the time complexity of this recursive algorithm and show the reasoning."),
    ("on", "Design a retry policy that handles transient errors but preserves cancellation and idempotency."),
    ("on", "A test fails only under concurrency. Identify possible shared-state races and propose a regression test."),
    ("on", "Reconcile these conflicting acceptance criteria. State assumptions and give a consistent interpretation."),
    ("on", "Given these monthly costs and changing revenue, calculate the breakeven month and explain the steps."),
    ("on", "Investigate this intermittent KeyError from the traceback and identify the smallest safe code change."),
    ("on", "Design a test matrix for this parser, including edge cases and the invariants each test should check."),
    ("on", "Evaluate the caching options for this workload, including invalidation, consistency, and memory costs."),
    ("on", "Trace how this nullable value can reach the database write through these nested callbacks."),
    ("on", "Plan a staged refactor that minimizes downtime and includes a rollback path."),
    ("on", "Review this SQL query plan, find the expensive operation, and suggest an optimization that preserves results."),
    ("off", "What does HTTP stand for?"),
    ("off", "Convert 90 minutes to hours."),
    ("off", "Which number is larger: 17 or 23?"),
    ("off", "Define CSV in one sentence."),
    ("off", "Translate 'good morning' into Spanish."),
    ("off", "What file extension do Python scripts usually use?"),
    ("off", "Is True a Python boolean value?"),
    ("off", "Give me one synonym for quick."),
    ("off", "Sort these two words alphabetically: pear, apple."),
    ("off", "What day comes immediately after Monday?"),
    ("off", "Summarize this sentence in fewer words: The server is currently unavailable."),
    ("off", "Say hello in French."),
    ("off", "Format this date as ISO: March 4, 2026."),
    ("off", "Count the letters in the word cat."),
    ("off", "What is the capital of Peru?"),
)


async def evaluate(client: AsyncOpenAI, model: str) -> tuple[int, int, int]:
    correct = 0
    on_total = on_correct = off_total = off_correct = 0
    errors = 0
    elapsed = 0.0

    for index, (expected, prompt) in enumerate(PROMPTS, 1):
        start = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": THINKING_CLASSIFIER_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=16,
                response_format={"type": "json_object"},
                extra_body={"json_schema": THINKING_CLASSIFIER_SCHEMA},
            )
            raw = response.choices[0].message.content
            selected = parse_thinking_label(raw)
        except Exception as error:
            selected = None
            raw = f"API error: {type(error).__name__}"
            errors += 1
        if selected is None and not (
            isinstance(raw, str) and raw.startswith("API error:")
        ):
            errors += 1
        elapsed += time.perf_counter() - start

        is_correct = selected is not None and selected == (expected == "on")
        correct += int(is_correct)
        if expected == "on":
            on_total += 1
            on_correct += int(is_correct)
        else:
            off_total += 1
            off_correct += int(is_correct)
        label = "on" if selected is True else "off" if selected is False else f"invalid ({raw!r})"
        print(f"{index:02d} {'OK' if is_correct else 'MISS'} expected={expected:3} got={label:24} {prompt}")

    print(f"\nAccuracy: {correct}/{len(PROMPTS)} ({correct / len(PROMPTS):.1%})")
    print(f"Thinking on:  {on_correct}/{on_total}")
    print(f"Thinking off: {off_correct}/{off_total}")
    print(f"API errors or invalid labels: {errors}")
    print(f"Average response time: {elapsed / len(PROMPTS):.2f}s")
    return correct, errors, len(PROMPTS)


async def run_benchmark(model: str, base_url: str, timeout: float) -> tuple[int, int, int]:
    client = AsyncOpenAI(
        base_url=base_url,
        api_key="not-needed",
        timeout=timeout,
        max_retries=0,
    )
    try:
        return await evaluate(client, model)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=settings.thinking_classifier_model,
                        help="model alias served by the classifier endpoint")
    parser.add_argument("--base-url", default=settings.thinking_classifier_base_url,
                        help="OpenAI-compatible classifier URL")
    parser.add_argument("--timeout", type=float, default=settings.thinking_classifier_timeout,
                        help="per-request timeout in seconds")
    args = parser.parse_args()
    if not args.model:
        parser.error("set thinking_classifier_model in settings.toml or pass --model")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    _, errors, _ = asyncio.run(run_benchmark(args.model, args.base_url, args.timeout))
    return int(errors > 0)


if __name__ == "__main__":
    raise SystemExit(main())
