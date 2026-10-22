import sys

from agent import Agent

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")


def main():
    agent = Agent()
    agent.load_memory()
    print("Jinni online. type 'exit' to leave.")
    if agent.summary:
        print("  (memory loaded)")

    try:
        while True:
            user_text = input("you > ").strip()
            if user_text.lower() in ("exit", "quit"):
                break
            if not user_text:
                continue
            if user_text == "/think":
                agent.thinking_on = not agent.thinking_on
                print(f"  (thinking display: {'on' if agent.thinking_on else 'off'})")
                continue
            if user_text == "/memory":
                print(agent.summary or "  (no memories yet)")
                continue
            if user_text == "/forget":
                agent.forget()
                print("  (memory wiped)")
                continue
            print("jinni > ", end="")
            agent.chat(user_text)
    except (KeyboardInterrupt, EOFError):
        print()

    print("  (saving memory...)")
    try:
        agent.summarize_history(keep=0)
    except Exception as e:
        print(f"  (could not save memory: {e})")


if __name__ == "__main__":
    main()