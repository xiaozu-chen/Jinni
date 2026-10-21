import json
import sys

from openai import OpenAI

from config import (
    BASE_URL, MODEL, SYSTEM_PROMPT, MAX_STEPS,
    CONTEXT_LIMIT, COMPACT_AT, SUMMARIZE_AT, KEEP_TURNS,
    MEMORY_FILE, GRAY, RESET,
)
from context import compact, to_transcript
from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, NEEDS_APPROVAL

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

client = OpenAI(base_url=BASE_URL, api_key="not-needed")

messages = [{"role": "system", "content": SYSTEM_PROMPT}]
summary = ""
SHOW_THINKING = True

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

        print(f"  (context: {used}/{CONTEXT_LIMIT})")
        if used > CONTEXT_LIMIT * COMPACT_AT:
            n = compact(messages)
            if n:
                print(f"  (compacted {n} old tool results)")
        if used > CONTEXT_LIMIT * SUMMARIZE_AT:
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
