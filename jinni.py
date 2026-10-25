import asyncio
import json
import sys
import logging
from datetime import date, timedelta

import webbrowser
from config import settings
from logger import setup_logging
from agent import Agent
from review import review, review_stale_facts
from tools import LOAD_ERRORS, NEEDS_APPROVAL, TOOL_FUNCTIONS
from tools.interaction import reset_tasks, task_list
from tools.workspace import find_chart
from semantic import EmbedError, catch_up, hybrid_search, start_warmup
from mcp_client import McpManager
from export_png import ExportError, export_chart, parse_export_options
from export_formats import export_pdf, export_svg
from export_all import export_all
from mcp_data import export_mcp_table
from svgcharts import is_genuine_page
from chart_records import check_chart_record, record_genuine_chart
from audit import recent_calls

log = logging.getLogger("jinni.cli")


def show_memories(agent: Agent, query: str = "") -> None:
    parts = query.strip().split(maxsplit=1)
    kind = ""
    if parts and parts[0].lower() in {"fact", "facts", "event", "events"}:
        kind = "fact" if parts[0].lower().startswith("fact") else "event"
        query = parts[1] if len(parts) > 1 else ""
    elif parts and parts[0].lower() == "search":
        query = parts[1] if len(parts) > 1 else ""

    items = agent.memory.list_all()
    if kind:
        items = [item for item in items if item.kind == kind]
    if query:
        matching_ids = {item.id for item in agent.memory.search(query, limit=200)}
        items = [item for item in items if item.id in matching_ids]
    if not items:
        print("  (no matching memories)")
        return
    print(f"  {len(items)} matching memory item(s):")
    for item in items[:100]:
        session = item.session_id or "older memory"
        print(f"  #{item.id} [{item.kind}] {item.created} · session {session}: {item.text}")
    if len(items) > 100:
        print(f"  ... {len(items) - 100} more")


def forget_command(agent: Agent, arg: str) -> None:
    if arg == "all":
        count = len(agent.memory.list_all())
        if count and input(f"  delete ALL {count} memories? (y/n) > ").strip().lower() == "y":
            print(f"  ({agent.memory.clear()} memories deleted)")
    elif arg.isdigit():
        print("  (forgotten)" if agent.memory.delete(int(arg)) else "  (no memory with that number)")
    else:
        print("  usage: /forget 12  or  /forget all")


def help_text() -> str:
    return """Commands:
  /help              show this list
  /config            show effective settings (sensitive values are hidden)
  /undo              remove the latest chat turn from conversation history
  /think             toggle model reasoning display
  /parallel          toggle parallel tool calls
  /tools             list available tools
  /allowed, /revoke  inspect or clear session approvals
  /memory [FILTER]   browse memories by fact/event or search text
  /forget            remove saved memories
  /tasks             show the session task list
  /stats             show session token, timing, and tool totals
  /prune DAYS        review and remove old session notes
  /audit [COUNT]     show recent approved tool calls
  /open [NAME]       open a chart
  /png, /svg, /pdf   export a chart
  /export-all [TYPE] export charts (png, svg, pdf, or all)
  /mcp, /mcp-table   inspect MCP servers or export a table
  /recall QUERY      search saved memories
  /reindex           refresh semantic memory embeddings
  exit               leave Jinni"""


def config_text(config=settings) -> str:
    servers = ", ".join(
        f"{server.name} ({', '.join(server.tools) or 'no tools'})"
        for server in config.mcp_servers
    ) or "none"
    return "\n".join((
        f"model: {config.model}",
        f"max steps: {config.max_steps}",
        f"context limit: {config.context_limit} tokens",
        f"thinking by default: {'on' if config.thinking_default else 'off'}",
        f"parallel tools: {'on' if config.parallel_tools else 'off'}",
        f"search: {config.search_backend} ({config.search_region})",
        f"memory limits: {config.max_facts} facts, {config.max_fact_chars} chars each, {config.memory_prompt_chars} prompt chars, {config.recall_results} recall results",
        f"embeddings: {'on' if config.embed_enabled else 'off'}",
        f"MCP: {'on' if config.mcp_enabled else 'off'}; servers: {servers}",
        f"PNG default: {config.png_theme}, {config.png_width}x{config.png_height} at {config.png_scale:g}x",
    ))


def undo_last_turn(agent: Agent) -> str:
    turn_start = next(
        (index for index in range(len(agent.messages) - 1, 0, -1)
         if agent.messages[index].get("role") == "user"),
        None,
    )
    if turn_start is None:
        return "(no chat turn to undo)"
    del agent.messages[turn_start:]
    agent.apply_memory()
    return "(latest chat turn removed from conversation history)"


def stats_text(agent: Agent) -> str:
    stats = agent.stats
    total_tokens = stats["prompt_tokens"] + stats["completion_tokens"]
    average = stats["seconds"] / stats["laps"] if stats["laps"] else 0.0
    lines = [
        f"model laps: {stats['laps']}",
        f"tokens: {total_tokens} total ({stats['prompt_tokens']} prompt, {stats['completion_tokens']} generated)",
        f"model time: {stats['seconds']:.1f}s total, {average:.1f}s per lap average",
        "tool calls:",
    ]
    if agent.tool_counts:
        lines.extend(f"  {name}: {count}" for name, count in sorted(agent.tool_counts.items()))
    else:
        lines.append("  (none)")
    return "\n".join(lines)

def main() -> None:
    for stream in (sys.stdout, sys.stdin):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    setup_logging()
    reset_tasks()
    log.info("started, model=%s", settings.model)
    for err in LOAD_ERRORS:
        log.warning("plugin skipped: %s", err)
        print(f"  (plugin skipped: {err})")

    agent = Agent()
    if start_warmup(agent.memory):
        print("  (warming semantic memory in the background)")
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
                if cmd == "/help":
                    print(help_text())
                    continue
                if cmd == "/config":
                    print(config_text())
                    continue
                if cmd == "/undo":
                    print(undo_last_turn(agent))
                    continue
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
                    show_memories(agent, arg)
                    continue
                if cmd == "/tasks":
                    print(task_list("list"))
                    continue
                if cmd == "/stats":
                    print(stats_text(agent))
                    continue
                if cmd == "/audit":
                    raw_count = arg.strip()
                    try:
                        count = int(raw_count) if raw_count else 20
                    except ValueError:
                        count = 0
                    print(recent_calls(count))
                    continue
                if cmd == "/forget":
                    forget_command(agent, arg.strip())
                    continue
                if cmd == "/prune":
                    raw_days = arg.strip()
                    try:
                        days = int(raw_days)
                    except ValueError:
                        days = 0
                    if not 1 <= days <= 36500:
                        print("  (usage: /prune DAYS — choose 1 to 36500 days)")
                        continue
                    cutoff = date.today() - timedelta(days=days)
                    count = agent.memory.count_events_before(cutoff)
                    if not count:
                        print(f"  (no session notes older than {cutoff.isoformat()})")
                        continue
                    print(f"  {count} session note(s) are older than {cutoff.isoformat()}:")
                    for item in agent.memory.events_before(cutoff):
                        print(f"    #{item.id} {item.created} {item.text}")
                    if count > 10:
                        print(f"    ... and {count - 10} more")
                    if input("  delete these session notes? (y/n) > ").strip().lower() == "y":
                        print(f"  ({agent.memory.prune_events_before(cutoff)} session note(s) pruned)")
                    else:
                        print("  (nothing pruned)")
                    continue
                if cmd == "/open":
                    page = find_chart(arg.strip())
                    if page is None:
                        print("  (no chart found. ask Jinni to make one first)")
                        continue
                    page_text = page.read_text(encoding="utf-8", errors="replace")
                    recorded = check_chart_record(page, page_text)
                    genuine = recorded
                    if recorded is None:
                        genuine = is_genuine_page(page_text)
                        if genuine:
                            try:
                                record_genuine_chart(page, page_text)
                            except OSError:
                                pass
                    if not genuine:
                        warning = "  this page was not made by the current chart tool, so it may contain scripts. open anyway? (y/n) > "
                        if input(warning).strip().lower() != "y":
                            print("  (not opened)")
                            continue
                    if webbrowser.open(page.as_uri()):
                        print(f"  (opened {page.name})")
                    else:
                        print(f"  (could not open a browser. the file is at {page})")
                    continue
                if cmd == "/png":
                    try:
                        name, theme, width, height = parse_export_options(arg.strip())
                        page = find_chart(name)
                        if page is None:
                            print("  (no chart found. ask Jinni to make one first)")
                            continue
                        print(f"  ({export_chart(page, theme, width, height)})")
                    except (ExportError, ValueError) as e:
                        print(f"  (PNG export failed: {e})")
                    continue
                if cmd in ("/svg", "/pdf"):
                    page = find_chart(arg.strip())
                    if page is None:
                        print("  (no chart found. ask Jinni to make one first)")
                        continue
                    try:
                        result = export_svg(page) if cmd == "/svg" else export_pdf(page)
                        print(f"  ({result})")
                    except ExportError as e:
                        print(f"  ({cmd[1:].upper()} export failed: {e})")
                    continue
                if cmd == "/export-all":
                    try:
                        print(f"  ({export_all(arg.strip().lower() or 'all')})")
                    except ValueError as e:
                        print(f"  (export failed: {e})")
                    continue
                if cmd == "/mcp-table":
                    if manager is None:
                        print("  (MCP is turned off in config.py)")
                        continue
                    server_name, _, remaining = arg.strip().partition(" ")
                    tool_name, _, raw_arguments = remaining.partition(" ")
                    try:
                        arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
                        if not isinstance(arguments, dict):
                            raise ValueError("arguments must be a JSON object")
                        result = runner.run(export_mcp_table(manager, server_name, tool_name, arguments))
                        print(f"  ({result})")
                    except (ValueError, RuntimeError) as e:
                        print(f"  (MCP table export failed: {e})")
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
        try:
            deleted = review_stale_facts(agent.memory)
            if deleted:
                print(f"  ({deleted} stale fact(s) forgotten)")
        except (Exception, KeyboardInterrupt) as e:
            log.exception("stale memory review failed")
            print(f"  (skipped stale memory review: {type(e).__name__})")
        if manager:
            try:
                runner.run(manager.stop())
            except (Exception, KeyboardInterrupt) as e:
                log.exception("MCP shutdown failed")
                print(f"  (MCP shutdown problem: {type(e).__name__})")


if __name__ == "__main__":
    main()
