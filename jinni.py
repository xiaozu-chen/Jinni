import asyncio
import sys
import logging

from config import settings
from logger import setup_logging
from agent import Agent

from tools import LOAD_ERRORS, TOOL_FUNCTIONS

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

log = logging.getLogger("jinni.cli")


def main():
    setup_logging()
    log.info("started, model=%s", settings.model)
    for err in LOAD_ERRORS:
        log.warning("plugin skipped: %s", err)
        print(f"  (plugin skipped: {err})")
    print(f"  ({len(TOOL_FUNCTIONS)} tools loaded)")
    agent = Agent()
    agent.load_memory()
    print("Jinni online.")
    if agent.summary:
        print("  (memory loaded)")

    with asyncio.Runner() as runner:
        try:
            while True:
                user_text = input("you > ").strip()
                if user_text.lower() in ("exit", "quit"):
                    break
                if not user_text:
                    continue
                if user_text == "/think":
                    agent.thinking_on = not agent.thinking_on
                    print(f"  (thinking: {'on' if agent.thinking_on else 'off'})")
                    continue
                if user_text == "/parallel":
                    agent.parallel_tools = not agent.parallel_tools
                    print(f"  (parallel tools: {'on' if agent.parallel_tools else 'off'})")
                    continue
                if user_text == "/memory":
                    print(agent.summary or "  (no memories yet)")
                    continue
                if user_text == "/forget":
                    agent.forget()
                    print("  (memory wiped)")
                    continue
                print("jinni > ", end="")
                try:
                    runner.run(agent.chat(user_text))
                except KeyboardInterrupt:
                    print("\n (interruped, that turn was dropped)")
        except (KeyboardInterrupt, EOFError):
            print()
    
        print("  (saving memory...)")
        try:
            runner.run(agent.summarize_history(keep=0))
        except Exception as e:
            log.exception("could not save memory")
            print(f"  (could not save memory: {e})")

    
if __name__ == "__main__":
    main()