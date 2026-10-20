import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from openai import OpenAI

import json

from tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

client = OpenAI(base_url="http://localhost:8080/v1", api_key="not-needed")

SYSTEM_PROMPT = "You are Jinni, a helpful local AI agent. Keep answers concise."

messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def chat(user_text):
    messages.append({"role": "user", "content": user_text})

    stream = client.chat.completions.create(
        model="qwen3",
        messages=messages,
        stream=True,
    )

    reply = ""
    for chunk in stream:
        if not chunk.choices:
            continue
        piece = chunk.choices[0].delta.content or ""
        print(piece, end="", flush=True)
        reply += piece
    print()

    messages.append({"role": "assistant", "content": reply})


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