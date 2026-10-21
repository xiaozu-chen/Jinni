import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from openai import OpenAI

import json

from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, NEEDS_APPROVAL

client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

SYSTEM_PROMPT = "You are Jinni, a helpful local AI agent. Keep answers concise."

MAX_STEPS = 8

CONTEX_LIMIT = 16384
COMPACT_AT = 0.7
KEEP_RECENT = 3

SUMMARIZE_AT = 0.8
KEEP_TURNS = 2
summary = ""

MEMORY_FILE = Path("memory.txt")

SHOW_THINKING = True
GRAY = "\033[90m"
RESET = "\033[0m"

messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def run_tool(call):
    name = call["name"]
    try:
        args = json.loads(call["arguments"] or "{}")
        print(f"  [tool] {name}({args})")
        if name not in TOOL_FUNCTIONS:
            return f"Error: unknown tool '{name}'"
        if name in NEEDS_APPROVAL:
            answer = input(f"  allow {name}? (y/n) >").strip().lower()
            if answer != "y":
                return "The user declined this action. It was their choice, not a technical error. Do not retry; ask what they want instead."
        return str(TOOL_FUNCTIONS[name](**args))
    except Exception as e:
        return f"Error: {e}"
        

def compact(messages):
    tool_idxs = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    old = tool_idxs[:-KEEP_RECENT]
    shrunk = 0
    for i in old:
        text = messages[i]["content"]
        if len(text) > 200:
            messages[i]["content"] = text[:150] + " ...[trimmed to save context]"
            shrunk += 1
    return shrunk

def to_transcript(msgs):
    lines = []
    for m in msgs:
        if m["role"] == "user":
            lines.append(f"User: {m['content']}")
        elif m["role"] == "assistant":
            if m.get("content"):
                lines.append(f" Jinni: {m['content']}")
            for tc in m.get("tool_calls", []):
                f = tc["function"]
                lines.append(f"Jinni used {f['name']}({f['arguments'][:200]})")
        elif m["role"] == "tool":
            lines.append(f"Tool result: {m['content'][:300]}")
    return "\n".join(lines)

def apply_memory():
    text = SYSTEM_PROMPT
    if summary:
        text += "\n\nYour memory of earlier conversation:\n" + summary
    messages[0]["content"] = text

def save_memory():
    MEMORY_FILE.write_text(summary, encoding='utf-8')

def load_memory():
    global summary
    if MEMORY_FILE.exists():
        summary = MEMORY_FILE.read_text(encoding="utf-8").strip()
        apply_memory()

def summarize_history(keep=KEEP_TURNS):
    global summary
    user_idxs = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if len(user_idxs) <= keep:
        return False

    cut = user_idxs[-keep] if keep else len(messages)
    old = messages[1:cut]

    prompt = (
        "/no_think\n"
        "Summarize this conversation as notes for your own memory. "
        "Only write facts that actually appeared. Do NOT guess goals. "
        "Include: the user's name if given, exact file names read or written, "
        "decisions made, and unfinished tasks. "
        "Skip any category that has nothing. "
        "Under 150 words, bullet points.\n\n"
    )
    if summary:
        prompt += f"Previous notes:\n{summary}\n\n"
    prompt += "New conversation:\n" + to_transcript(old)

    response = client.chat.completions.create(
        model="qwen3",
        messages=[{"role": "user", "content": prompt}],
    )
    summary = response.choices[0].message.content.strip()

    apply_memory()
    save_memory()
    del messages[1:cut]
    print(f"  (summarized {len(old)} messages into notes)")
    print(f"  notes: {summary}")
    return True

def stream_response():
    stream = client.chat.completions.create(
        model="qwen3",
        messages=messages,
        tools=TOOL_SCHEMAS,
        stream=True,
        stream_options={"include_usage": True}
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
        if thought and SHOW_THINKING:
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

def chat(user_text):
    messages.append({"role": "user", "content": user_text})

    for step in range(MAX_STEPS):
        content, calls, used = stream_response()

        print(f"  (context: {used}/{CONTEX_LIMIT})")
        if used > CONTEX_LIMIT * COMPACT_AT:
            n = compact(messages)
            if n:
                print(f"  (compacted {n} old tool results)")
        if used > CONTEX_LIMIT * SUMMARIZE_AT:
            summarize_history()

        if not calls:
            messages.append({"role": "assistant", "content": content})
            return

        messages.append({
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
            messages.append({
                "role": "tool",
                "tool_call_id": c["id"],
                "content": result,
            })

    print("(hit the step limit, stopping)")


def main():
    global SHOW_THINKING, summary
    load_memory()
    print("JINNI ONLINE")
    if summary:
        print("  (memory loaded)")

    try:
        while True:
            user_text = input("you > ").strip()
            if user_text.lower() in ("exit", "quit"):
                break
            if not user_text:
                continue
            if user_text == "/think":
                SHOW_THINKING = not SHOW_THINKING
                print(f"  (thinking display: {'on' if SHOW_THINKING else 'off'})")
                continue
            if user_text == "/memory":
                print(summary or "  (no memories yet)")
                continue
            if user_text == "/forget":
                summary = ""
                MEMORY_FILE.unlink(missing_ok=True)
                del messages[1:]
                apply_memory()
                print("  (memory wiped)")
                continue
            print("jinni > ", end="")
            chat(user_text)
    except (KeyboardInterrupt, EOFError):
        print()

    print("  (saving memory...)")
    try:
        summarize_history(keep=0)
    except Exception as e:
        print(f"  (could not save memory: {e})")


if __name__ == "__main__":
    main()
