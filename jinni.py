import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from openai import OpenAI

import json

from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

SYSTEM_PROMPT = "You are Jinni, a helpful local AI agent. Keep answers concise."

MAX_STEPS = 8

messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def run_tool(tc):
    name = tc.function.name
    try:
        args = json.loads(tc.function.arguments or "{}")
        print(f"  [tool] {name}({args})")
        if name not in TOOL_FUNCTIONS:
            return f"Error: unknown tool '{name}'"
        return str(TOOL_FUNCTIONS[name](**args))
    except Exception as e:
        return f"Error: {e}"


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
