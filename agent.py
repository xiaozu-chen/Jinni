import json
import time

from openai import OpenAI

from config import settings, GRAY, RESET
from context import compact, to_transcript
from models import Message, ToolCall
from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, NEEDS_APPROVAL

def run_tool(call: ToolCall) -> str:
    try:
        args = json.loads(call.arguments or "{}")
        print(f"  [tool] {call.name}({args})")
        if call.name not in TOOL_FUNCTIONS:
            return f"Error: unknown tool '{call.name}'"
        if call.name in NEEDS_APPROVAL:
            answer = input(f"  allow {call.name}? (y/n) > ").strip().lower()
            if answer != "y":
                return "The user declined this action. It was their choice, not a technical error. Do not retry; ask what they want instead."
        return str(TOOL_FUNCTIONS[call.name](**args))
    except Exception as e:
        return f"Error: {e}"

class Agent:
    def __init__(self) -> None:
        self.client = OpenAI(base_url=settings.base_url, api_key="not-needed")
        self.messages: list[Message] = [{"role": "system", "content": settings.system_prompt}]
        self.summary: str = ""
        self.thinking_on: bool = settings.thinking_default

    def apply_memory(self) -> None:
        text = settings.system_prompt
        if self.summary:
            text += "\n\nYour memory of earlier conversation:\n" + self.summary
        self.messages[0]["content"] = text

    def save_memory(self) -> None:
        settings.memory_file.write_text(self.summary, encoding="utf-8")

    def load_memory(self) -> None:
        if settings.memory_file.exists():
            self.summary = settings.memory_file.read_text(encoding="utf-8").strip()
            self.apply_memory()

    def forget(self) -> None:
        self.summary = ""
        settings.memory_file.unlink(missing_ok=True)
        del self.messages[1:]
        self.apply_memory()


    def stream_response(self) -> tuple[str, list[ToolCall], int]:
        start = time.perf_counter()
        first = None
        generated = 0
        stream = self.client.chat.completions.create(
            model=settings.model,
            messages=self.messages,
            tools=TOOL_SCHEMAS,
            stream=True,
            stream_options={"include_usage": True},
            extra_body={"chat_template_kwargs": {"enable_thinking": self.thinking_on}},
        )

        content = ""
        calls: dict[int, dict[str, str]] = {}
        used = 0
        thinking = False

        for chunk in stream:
            if chunk.usage:
                used = chunk.usage.prompt_tokens
                generated = chunk.usage.completion_tokens
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            thought = getattr(delta, "reasoning_content", None)
            if first is None and (thought or delta.content or delta.tool_calls):
                first = time.perf_counter() - start
            if thought and self.thinking_on:
                if not thinking:
                    print(f"{GRAY}[thinking] ", end="")
                    thinking = True
                print(f"{GRAY}{thought}{RESET}", end="", flush=True)

            if delta.content:
                if thinking:
                    print(f"{RESET}\n")
                    thinking = False
                print(delta.content, end="", flush=True)
                content += delta.content

            for tc in delta.tool_calls or []:
                slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        if thinking:
            print(RESET)
        if content:
            print()

        total = time.perf_counter() - start
        if first is not None and total > first and generated:
            speed = generated / (total - first)
            print(f"  (first token {first:.1f}s | total {total:.1f}s | {generated} tokens | {speed:.0f} tok/s)")

        tool_calls = [
            ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"]) for i, c, in sorted(calls.items())
        ]
        return content, tool_calls, used

    def summarize_history(self, keep: int = settings.keep_turns) -> bool:
        user_idxs = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_idxs) <= keep:
            return False

        cut = user_idxs[-keep] if keep else len(self.messages)
        old = self.messages[1:cut]

        prompt = (
            "Summarize this conversation as notes for your own memory. "
            "Only write facts that actually appeared. Do NOT guess goals. "
            "Include: the user's name if given, exact file names read or written, "
            "decisions made, and unfinished tasks. "
            "Skip any category that has nothing. "
            "Under 150 words, bullet points.\n\n"
        )
        if self.summary:
            prompt += f"Previous notes:\n{self.summary}\n\n"
        prompt += "New conversation:\n" + to_transcript(old)

        response = self.client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        self.summary = (response.choices[0].message.content or "").strip()

        self.apply_memory()
        self.save_memory()
        del self.messages[1:cut]
        print(f"  (summarized {len(old)} messages into notes)")
        print(f"  notes: {self.summary}")
        return True

    def chat(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})

        for step in range(settings.max_steps):
            content, calls, used = self.stream_response()

            print(f"  (context: {used}/{settings.context_limit})")
            if used > settings.context_limit * settings.compact_at:
                n = compact(self.messages)
                if n:
                    print(f"  (compacted {n} old tool results)")
            if used > settings.context_limit * settings.summarize_at:
                self.summarize_history()

            if not calls:
                self.messages.append({"role": "assistant", "content": content})
                return

            self.messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in calls
                ],
            })

            for c in calls:
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": c.id,
                    "content": run_tool(c),
                })

        print("(hit the step limit, stopping)")