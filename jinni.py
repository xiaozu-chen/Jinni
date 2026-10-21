import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from openai import OpenAI

import json

from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS, NEEDS_APPROVAL

client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

SYSTEM_PROMPT = "You are Jinni, a helpful local AI agent. Keep answers concise."

MAX_STEPS = 8

CONTEX_LIMIT = 2000
COMPACT_AT = 0.7
KEEP_RECENT = 3

messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def run_tool(tc):
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
        print(f"  [tool] {name}({args})")
        if name not in TOOL_FUNCTIONS:
            return f"Error: unknown tool '{name}'"
        if name in NEEDS_APPROVAL:
            answer = input(f"  allow {name}? (y/n) >").strip().lower()
            if answer != "y":
                return "Error: the user denied this action."
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


def chat(user_text):
    messages.append({"role": "user", "content": user_text})

    for step in range(MAX_STEPS):
        print(f"  (step {step + 1})")
        response = client.chat.completions.create(
            model="qwen3",
            messages=messages,
            tools=TOOL_SCHEMAS,
        )
        msg = response.choices[0].message

        used = response.usage.prompt_tokens
        print(f" (context: {used}/{CONTEX_LIMIT})")
        if used > CONTEX_LIMIT * COMPACT_AT:
            n = compact(messages)
            if n:
                print(f"  (compacted {n} old tool results)")

        if not msg.tool_calls:
            print(msg.content)
            messages.append({"role": "assistant", "content": msg.content or ""})
            return

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            result = run_tool(tc)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    print("(hit the step limit, stopping)")


def main():
    print("Jinni online. type 'exit' to leave.")
    while True:
        user_text = input("you > ").strip()
        if user_text.lower() in ("exit", "quit"):
            break
        if not user_text:
            continue
        print("jinni > ", end="")
        chat(user_text)


if __name__ == "__main__":
    main()
