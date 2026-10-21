import json

from openai import OpenAI

from config import (
    BASE_URL, MODEL, SYSTEM_PROMPT, MAX_STEPS,
    CONTEXT_LIMIT, COMPACT_AT, SUMMARIZE_AT, KEEP_TURNS,
    MEMORY_FILE, GRAY, RESET,
)
from context import compact, to_transcript
from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, NEEDS_APPROVAL

def run_tool(call):
    name = call["name"]
    try:
        args = json.loads(call["arguments"] or "{}")
        print(f"  [fool] {name}({args})")
        if name not in TOOL_FUNCTIONS:
            return f"Error: unknown tool: '{name}"
        if name in NEEDS_APPROVAL:
            answer = input(f"  allow {name}? (y/n) >").strip.lower()
            if answer != "y":
                return "The user declined this action. It was their choice, not a technical error. Do not retry; ask what they want instead."
        return str(TOOL_FUNCTIONS[name](**args))
    except Exception as e:
        return f"Error: {e}"

class Agent:
    def __init__(self):
        self.client = OpenAI(base_url=BASE_URL, api_key="not-needed")
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.summary = ""
        self.show_thinking = True

    def apply_memory(self):
        text = SYSTEM_PROMPT
        if self.summary:
            text += "\n\nYour memory of earlier conversation:\n" + self.summary
        self.messages[0]["content"] = text

    def save_memory(self):
        MEMORY_FILE.write_text(self.summary, encoding="utf-8")

    def load_memory(self):
        if MEMORY_FILE.exists():
            self.summary = MEMORY_FILE.read_text(encoding="utf-8").strip()
            self.apply_memory()

    def forget(self):
        self.summary = ""
        MEMORY_FILE.unlink(missing_ok=True)
        del self.messages[1:]
        self.apply_memory()


    def stream_response(self):
        stream = self.client.chat.completions.create(
            model=MODEL,
            messages=self.messages,
            tools=TOOL_SCHEMAS,
            stream=True,
            stream_options={"include_usage": True},
        )

        content = ""
        calls = {}
        used = 0
        thinking = False

        for chunk in stream:
            if chunk.usage:
                used = chunk.usage.prompt_tokens
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            thought = getattr(delta, "reasoning_content", None)
            if thought and self.show_thinking:
                if not thinking:
                    print(f"{GRAY}[thinking] ", end="")
                    thinking = True
                print(thought, end="", flush=True)

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

        tool_calls = []
        for i in sorted(calls):
            c = calls[i]
            c["id"] = c["id"] or f"call_{i}"
            tool_calls.append(c)

        return content, tool_calls, used

    def summarize_history(self, keep=KEEP_TURNS):
        user_idxs = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_idxs) <= keep:
            return False

        cut = user_idxs[-keep] if keep else len(self.messages)
        old = self.messages[1:cut]

        prompt = (
            "/no_think\n"
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
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        self.summary = response.choices[0].message.content.strip()

        self.apply_memory()
        self.save_memory()
        del self.messages[1:cut]
        print(f"  (summarized {len(old)} messages into notes)")
        print(f"  notes: {self.summary}")
        return True

    def chat(self, user_text):
        self.messages.append({"role": "user", "content": user_text})

        for step in range(MAX_STEPS):
            content, calls, used = self.stream_response()

            print(f"  (context: {used}/{CONTEXT_LIMIT})")
            if used > CONTEXT_LIMIT * COMPACT_AT:
                n = compact(self.messages)
                if n:
                    print(f"  (compacted {n} old tool results)")
            if used > CONTEXT_LIMIT * SUMMARIZE_AT:
                self.summarize_history()

            if not calls:
                self.messages.append({"role": "assistant", "content": content})
                return

            self.messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"]},
                    }
                    for c in calls
                ],
            })

            for c in calls:
                result = run_tool(c)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "content": result,
                })

        print("(hit the step limit, stopping)")