import asyncio
import sys
import logging

import webbrowser
from config import settings
from logger import setup_logging
from agent import Agent
from review import review
from tools import LOAD_ERRORS, NEEDS_APPROVAL, TOOL_FUNCTIONS
from tools.workspace import find_chart
from semantic import EmbedError, catch_up, hybrid_search
from mcp_client import McpManager

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

log = logging.getLogger("jinni.cli")


def show_memories(agent: Agent) -> None:
    items = agent.memory.list_all()
    if not items:
        print("  (no memories yet)")
    for m in items:
        print(f"  #{m.id} [{m.kind}] {m.created} {m.text}")


def forget_command(agent: Agent, arg: str) -> None:
    if arg == "all":
        count = len(agent.memory.list_all())
        if count and input(f"  delete ALL {count} memories? (y/n) > ").strip().lower() == "y":
            print(f"  ({agent.memory.clear()} memories deleted)")
    elif arg.isdigit():
        print("  (forgotten)" if agent.memory.delete(int(arg)) else "  (no memory with that number)")
    else:
        print("  usage: /forget 12  or  /forget all")

def main() -> None:
    setup_logging()
    log.info("started, model=%s", settings.model)
    for err in LOAD_ERRORS:
        log.warning("plugin skipped: %s", err)
        print(f"  (plugin skipped: {err})")

    agent = Agent()
    facts, notes = agent.memory.counts()
    print("Jinni online. type 'exit' to leave.")
    if facts or notes:
        print(f"  (memory: {facts} facts, {notes} session notes)")

    with asyncio.Runner() as runner:
        manager = McpManager(settings.mcp_servers) if settings.mcp_enabled else None
        if manager:
            for line in runner.run(manager.start()):
                print(line)
        print(f"  ({len(TOOL_FUNCTIONS)} tools loaded)")
        try:
            while True:
                user_text = input("you > ").strip()
                if user_text.lower() in ("exit", "quit"):
                    break
                if not user_text:
                    continue
                cmd, _, arg = user_text.partition(" ")
                if cmd == "/think":
                    agent.thinking_on = not agent.thinking_on
                    print(f"  (thinking: {'on' if agent.thinking_on else 'off'})")
                    continue
                if cmd == "/parallel":
                    agent.parallel_tools = not agent.parallel_tools
                    print(f"  (parallel tools: {'on' if agent.parallel_tools else 'off'})")
                    continue
                if cmd == "/tools":
                    for name in TOOL_FUNCTIONS:
                        print(f"  {name}{'  (asks first)' if name in NEEDS_APPROVAL else ''}")
                    continue
                if cmd == "/allowed":
                    if not agent.allowed:
                        print("  (nothing is allowed without asking)")
                    for name, scope in sorted(agent.allowed):
                        print(f"  {name}: {'any use' if scope == '*' else scope}")
                    continue
                if cmd == "/revoke":
                    agent.allowed.clear()
                    print("  (all session permissions revoked)")
                    continue
                if cmd == "/memory":
                    show_memories(agent)
                    continue
                if cmd == "/forget":
                    forget_command(agent, arg.strip())
                    continue
                if cmd == "/open":
                    page = find_chart(arg.strip())
                    if page is None:
                        print("  (no chart found. ask Jinni to one first)")
                    elif webbrowser.open(page.as_uri()):
                        print(f"  (opened {page.name})")
                    else:
                        print(f"  (could not open a browser. the file is at {page})")
                    continue
                if cmd == "/recall":
                    found, mode = hybrid_search(agent.memory, arg.strip())
                    print(f"  ({len(found)} result(s), {mode} search)")
                    for m in found:
                        print(f"  #{m.id} [{m.kind}] {m.text}")
                    continue
                if cmd == "/reindex":
                    try:
                        print(f"  ({catch_up(agent.memory)} memories embedded)")
                    except EmbedError as e:
                        print(f"  (embeddings server not reachable: {e})")
                    continue
                if cmd == "/mcp":
                    if manager is None:
                        print("  (MCP is turned off in config.py)")
                    elif arg.startswith("restart"):
                        for line in runner.run(manager.restart(arg[len("restart"):].startswith())):
                            print(line)
                    else:
                        for line in manager.status_lines():
                            print(line)
                    continue
                print("jinni > ", end="")
                try:
                    runner.run(agent.chat(user_text))
                except KeyboardInterrupt:
                    print("\n  (interrupted, that turn was dropped)")
        except (KeyboardInterrupt, EOFError):
            print()

        print("  (looking back over this session...)")
        try:
            proposals = runner.run(agent.propose_memories())
            if proposals:
                saved = review(agent.memory, proposals)
                print(f"  ({saved} saved)")
            else:
                print("  (nothing new to remember)")
        except (Exception, KeyboardInterrupt) as e:
            log.exception("memory review failed")
            print(f"  (skipped the memory review: {type(e).__name__})")
        if manager:
            try:
                runner.run(manager.stop())
            except (Exception, KeyboardInterrupt) as e:
                log.exception("MCP shutdown failed")
                print(f"  (MCP shutdown problem: {type(e).__name__})")


if __name__ == "__main__":
    main()