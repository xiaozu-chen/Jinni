"""Textual front end for Jinni: chat, project selection, settings, and local commands.

Runtime services are assembled once, then input routes to a slash command or an agent turn.
Everything runs on Textual's event loop, so agent turns, MCP calls and confirmations are
awaited directly instead of going through asyncio.Runner and input()."""

import argparse
import asyncio
import atexit
import json
import logging
import re
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import httpx
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Footer, Header, Input, Static

from settings.config import settings
from runtime.agent_events import AgentEvent
from server.mcp_config import resolve_mcp_servers
from runtime.logger import setup_logging
from runtime.agent import Agent
from tools import LOAD_ERRORS, NEEDS_APPROVAL
from tools.interaction import due_tasks, task_list
from tools.workspace import find_chart
from memory.semantic import EmbedError, catch_up, hybrid_search, start_warmup
from server.mcp_client import McpManager
from presentation.export_png import ExportError, export_chart, parse_export_options
from presentation.export_formats import export_pdf, export_svg
from presentation.export_all import export_all
from server.mcp_data import export_mcp_table
from presentation.svgcharts import is_genuine_page
from presentation.chart_records import check_chart_record, record_genuine_chart
from permission.audit import recent_calls
from memory.transcripts import load_transcript, save_transcript
from memory.session_replay import SessionRecorder, render_replay, replay_path, replay_session
from server.embedding_server import EmbeddingServer
from permission.approval_store import load_approvals, save_approvals
from permission.policy import FULL_ACCESS_WARNING
import runtime.project as project_tools
import tools.workspace as workspace_tools

log = logging.getLogger("jinni.cli")

SLASH_COMMANDS = [
    "/help", "/config", "/undo", "/mode ask", "/mode auto", "/mode auto-edit",
    "/full-access", "/safe", "/project", "/subtask", "/think", "/parallel", "/tools",
    "/allowed", "/revoke", "/memory", "/forget", "/tasks", "/stats", "/replay",
    "/save", "/load", "/prune", "/audit", "/open", "/png", "/svg", "/pdf",
    "/export-all", "/mcp", "/mcp-table", "/recall", "/reindex",
]


# ---------------------------------------------------------------------------
# Pure helpers (no terminal I/O)
# ---------------------------------------------------------------------------

def memory_lines(agent: Agent, query: str = "") -> list[str]:
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
        return ["  (no matching memories)"]
    lines = [f"  {len(items)} matching memory item(s):"]
    for item in items[:100]:
        session = item.session_id or "older memory"
        lines.append(f"  #{item.id} [{item.kind}] {item.created} · session {session}: {item.text}")
    if len(items) > 100:
        lines.append(f"  ... {len(items) - 100} more")
    return lines


def help_text() -> str:
    return """Commands:
  /help              show this list
  /config            show effective settings (sensitive values are hidden)
  /undo              remove the latest chat turn from conversation history
  /mode ask|auto|auto-edit choose approval behavior for this session
  /full-access       request bounded Full Access (if enabled)
  /safe              return to Ask mode immediately
  /project [NAME|PATH] list or switch projects; /project create NAME makes one
  /subtask TASK      summarize prior work and start with a fresh context
  /think [on|off|auto] toggle reasoning, or return to automatic classification
  /parallel          toggle parallel tool calls
  /tools             list available tools
  /allowed           inspect saved domain approvals
  /revoke [DOMAIN]   revoke saved approvals for a domain, or all domains
  /memory [FILTER]   browse memories by fact/event or search text
  /forget            remove saved memories
  /tasks             show the saved task list
  /stats             show session token, timing, and tool totals
  /replay start NAME record model requests locally; prompts and context are included
  /replay stop       stop recording
  /replay run NAME [MODEL] compare tool choices without running tools
  /save [NAME]       save a bounded conversation transcript
  /load NAME         load a transcript as context
  /prune DAYS        review and remove old session notes
  /audit [COUNT]     show recent approved tool calls
  /open [NAME]       open a chart
  /png, /svg, /pdf   export a chart
  /export-all [TYPE] export charts (png, svg, pdf, or all)
  /mcp               inspect servers, resources, prompts, or restart one
  /mcp-table         export an allowlisted MCP table
  /recall QUERY      search saved memories
  /reindex           refresh semantic memory embeddings
  exit               leave Jinni (or press Ctrl+Q)

Keys: Ctrl+C interrupt the current turn · Ctrl+L clear the screen
      Up/Down input history · Right arrow accepts a command suggestion"""


def config_text(config=settings, mcp_servers=None) -> str:
    mcp_servers = config.mcp_servers if mcp_servers is None else mcp_servers
    thinking = (
        f"automatic ({config.thinking_classifier_model})"
        if config.thinking_classifier_model
        else f"{'on' if config.thinking_default else 'off'} default"
    )
    servers = ", ".join(
        f"{server.name} ({', '.join(server.tools) or 'no tools'})"
        for server in mcp_servers
    ) or "none"
    return "\n".join((
        f"model: {config.model}",
        f"max steps: {config.max_steps}",
        f"context limit: {config.context_limit} tokens",
        f"thinking: {thinking}",
        f"parallel tools: {'on' if config.parallel_tools else 'off'}",
        f"Full Access: {'enabled by user command' if config.allow_full_access else 'disabled (allow_full_access = false)'}",
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
    restored = False
    if getattr(agent, "write_checkpoint", None):
        try:
            checkpoint = str(agent.write_checkpoint)
            if re.fullmatch(r"[0-9a-f]{32}", checkpoint):
                restored = bool(project_tools.restore_auto_edit_checkpoint(
                    workspace_tools.WORKSPACE, checkpoint
                ).get("restored"))
            else:
                restored = project_tools.undo_last_checkpoint(workspace_tools.WORKSPACE)
        except (OSError, ValueError) as error:
            return f"(could not undo the chat turn: {error})"
        agent.write_checkpoint = None
    del agent.messages[turn_start:]
    agent.apply_memory()
    suffix = " and its last workspace write was restored" if restored else ""
    return f"(latest chat turn removed from conversation history{suffix})"


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


def mcp_restart_target(argument: str) -> str | None:
    command, separator, target = argument.partition(" ")
    if command != "restart":
        return None
    return target.strip() if separator else ""


def activate_project(path, agent: Agent) -> str:
    """Switch workspace-scoped tools and guidance to the selected project folder."""
    if agent.approval_mode != "ask":
        agent.safe_mode("the active project changed")
    path = Path(path).expanduser().resolve()
    guidance = project_tools.load_project_guidance(path)
    workspace_tools.WORKSPACE = path
    workspace_tools.PROJECT_ACTIVE = True
    export_all.WORKSPACE = path
    agent.project_guidance = guidance
    agent.apply_memory()
    agent.set_project_active(True)
    return f"(active project: {path.name})"


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ChatView(VerticalScroll):
    """Scrolling transcript. Each message is its own Static so streams can update in place."""

    def add(self, renderable, classes: str = "") -> Static:
        widget = Static(renderable, classes=classes, markup=False)
        self.mount(widget)
        self.call_after_refresh(self.scroll_end, animate=False)
        return widget


class HistoryInput(Input):
    """Input with Up/Down history, replacing the old readline support."""

    BINDINGS = [
        Binding("up", "history(-1)", "Previous input", show=False),
        Binding("down", "history(1)", "Next input", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.history: list[str] = []
        self._position = 0
        self._draft = ""

    def remember(self, text: str) -> None:
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self._position = len(self.history)

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        if self._position == len(self.history):
            self._draft = self.value
        self._position = max(0, min(len(self.history), self._position + step))
        self.value = self.history[self._position] if self._position < len(self.history) else self._draft
        self.cursor_position = len(self.value)


class ConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #dialog {
        width: 72; max-width: 90%; height: auto; max-height: 90%;
        padding: 1 2; border: thick $primary; background: $surface; overflow-y: auto;
    }
    ConfirmScreen #buttons { height: auto; margin-top: 1; align-horizontal: right; }
    ConfirmScreen Button { margin-left: 2; }
    """
    AUTO_FOCUS = "#no"
    BINDINGS = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self.question))
            with Horizontal(id="buttons"):
                yield Button("Yes (y)", id="yes", variant="primary")
                yield Button("No (n)", id="no")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)

    @on(Button.Pressed, "#yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def _no(self) -> None:
        self.dismiss(False)


class PromptScreen(ModalScreen["str | None"]):
    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen #dialog {
        width: 90; max-width: 95%; height: auto; max-height: 90%;
        padding: 1 2; border: thick $error; background: $surface; overflow-y: auto;
    }
    PromptScreen Input { margin-top: 1; }
    """
    AUTO_FOCUS = "Input"
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, placeholder: str = "") -> None:
        super().__init__()
        self.question = question
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(Text(self.question))
            yield Input(placeholder=self.placeholder)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class JinniApp(App):
    TITLE = "Jinni"
    CSS = """
    #chat { height: 1fr; padding: 0 1; border: round $primary-darken-2; scrollbar-gutter: stable; }
    #chat.full-access { border: round $error; }
    #chat > Static { width: 100%; height: auto; }
    #chat > .user { color: $accent; text-style: bold; margin-top: 1; }
    #chat > .status, #chat > .sys { color: $text-muted; }
    #chat > .thinking {
        color: $text-muted; text-style: italic;
        border-left: tall $primary-darken-2; padding-left: 1;
    }
    #prompt.full-access { border: tall $error; }
    """
    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("pageup", "scroll_chat(-1)", "Scroll up", show=False),
        Binding("pagedown", "scroll_chat(1)", "Scroll down", show=False),
    ]

    def __init__(self, *, projects_dir: Path, project_guidance, project_active: bool,
                 mcp_servers, notes: list[str]) -> None:
        super().__init__()
        self.projects_dir = projects_dir
        self.mcp_servers = mcp_servers
        self.notes = notes
        self.manager: McpManager | None = None
        self.ready = False
        self._turn = None
        self._stream: tuple[str, Static, list[str]] | None = None
        self.agent = Agent(project_guidance=project_guidance, allowed_file=settings.allowed_file,
                           project_active=project_active, event_sink=self.render_event)
        self.agent.allowed.update(load_approvals(settings.allowed_file))
        self.embedding_server = EmbeddingServer(settings)
        self._chat = ChatView(id="chat")
        self._prompt = HistoryInput(
            id="prompt", placeholder="Message Jinni, or type / for commands",
            suggester=SuggestFromList(SLASH_COMMANDS, case_sensitive=False),
        )

    # -- layout and lifecycle ------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield self._chat
        yield self._prompt
        yield Footer()

    async def on_mount(self) -> None:
        self._prompt.focus()
        self.refresh_chrome()
        self.set_interval(5, self.refresh_chrome)  # picks up Full Access expiry
        for note in self.notes:
            self.say(f"  ({note})")
        if self.embedding_server.configured:
            self.say(f"  ({await asyncio.to_thread(self.embedding_server.start)})")
            atexit.register(self.embedding_server.stop)
        due = due_tasks()
        if due != "(task list is empty)":
            self.say("  Tasks due today or overdue:\n" + due)
        if start_warmup(self.agent.memory):
            self.say("  (warming semantic memory in the background)")
        facts, session_notes = self.agent.memory.counts()
        self.say("Jinni online. Type /help for commands, Ctrl+Q to quit.")
        if facts or session_notes:
            self.say(f"  (memory: {facts} facts, {session_notes} session notes)")
        if settings.mcp_enabled:
            self.manager = McpManager(self.mcp_servers)
            for line in await self.manager.start():
                self.say(line)
        self.say(f"  ({len(self.agent.visible_tool_names())} tools loaded)")
        self.ready = True

    async def action_quit(self) -> None:
        if self._turn is not None and self._turn.is_running:
            self._turn.cancel()
        agent = self.agent
        if agent.replay_recorder:
            agent.replay_recorder.close()
            agent.replay_recorder = None
        if self.manager:
            try:
                await self.manager.stop()
            except (Exception, KeyboardInterrupt) as error:
                log.exception("MCP shutdown failed")
                print(f"(MCP shutdown problem: {type(error).__name__})")
        self.embedding_server.stop()
        self.exit()

    def refresh_chrome(self) -> None:
        agent = self.agent
        agent.refresh_approval_mode()
        full = agent.approval_mode == "full-access"
        project = workspace_tools.WORKSPACE.name if workspace_tools.PROJECT_ACTIVE else "no project"
        self.sub_title = f"{project} · {agent.approval_mode}"
        self._prompt.set_class(full, "full-access")
        self._chat.set_class(full, "full-access")
        self._prompt.border_title = "FULL ACCESS" if full else ""

    # -- output --------------------------------------------------------------

    def say(self, text: str, classes: str = "sys") -> None:
        self._end_stream()
        self._chat.add(Text(text), classes=classes)

    def render_event(self, event: AgentEvent) -> None:
        kind = event.kind
        if kind == "status":
            self.say(event.text, classes="status")
        elif kind == "thinking_start":
            self._end_stream()
            self._begin_stream("thinking")
        elif kind == "thinking_delta":
            self._feed("thinking", event.text)
        elif kind == "thinking_end":
            self._end_stream()
        elif kind in {"text_delta", "responder_delta"}:
            self._feed("answer", event.text)
        elif kind == "text_end":
            self._end_stream()

    def _begin_stream(self, kind: str) -> None:
        widget = self._chat.add(Text(""), classes=kind)
        self._stream = (kind, widget, [])

    def _feed(self, kind: str, text: str) -> None:
        if self._stream and self._stream[0] != kind:
            self._end_stream()
        if self._stream is None:
            self._begin_stream(kind)
        _, widget, parts = self._stream
        parts.append(text)
        widget.update(Text("".join(parts)))
        self._chat.call_after_refresh(self._chat.scroll_end, animate=False)

    def _end_stream(self) -> None:
        if self._stream is None:
            return
        kind, widget, parts = self._stream
        self._stream = None
        text = "".join(parts)
        if not text.strip():
            widget.remove()
        elif kind == "answer":
            widget.update(RichMarkdown(text))

    # -- confirmations (replace input()) --------------------------------------

    async def ask_yes_no(self, question: str) -> bool:
        return bool(await self.push_screen_wait(ConfirmScreen(question)))

    async def ask_text(self, question: str, placeholder: str = "") -> str | None:
        return await self.push_screen_wait(PromptScreen(question, placeholder))

    # -- key actions -----------------------------------------------------------

    def action_interrupt(self) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        agent = self.agent
        if self._turn is not None and self._turn.is_running:
            self._turn.cancel()
            if agent.approval_mode == "full-access":
                agent.safe_mode("Ctrl+C was pressed")
                self.say("  [safety] Full Access ended; approvals are required again.")
            self.say("  (interrupted, that turn was dropped)")
        elif agent.approval_mode == "full-access":
            agent.safe_mode("Ctrl+C was pressed")
            self.say("  [safety] Full Access ended; approvals are required again.")
        else:
            self.notify("Nothing to interrupt. Press Ctrl+Q to quit.")
        self.refresh_chrome()

    def action_clear_chat(self) -> None:
        self._end_stream()
        self._chat.remove_children()

    def action_scroll_chat(self, direction: int) -> None:
        if direction < 0:
            self._chat.scroll_page_up()
        else:
            self._chat.scroll_page_down()

    # -- input ---------------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    def _submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        if not self.ready:
            self.notify("Jinni is still starting up.", severity="warning")
            return
        if self._turn is not None and self._turn.is_running:
            self.notify("Jinni is still working. Ctrl+C interrupts.", severity="warning")
            return
        self._prompt.value = ""
        self._prompt.remember(text)
        if text.lower() in ("exit", "quit"):
            self.run_worker(self.action_quit(), name="quit")
            return
        self._chat.add(Text(f"› {text}"), classes="user")
        self._turn = self.run_worker(self._handle(text), name="turn", exclusive=True)

    async def _handle(self, text: str) -> None:
        try:
            await self._dispatch(text)
        finally:
            self._end_stream()
            self.refresh_chrome()

    async def _dispatch(self, user_text: str) -> None:
        cmd, _, arg = user_text.partition(" ")
        handler = None
        if cmd.startswith("/") and len(cmd) > 1:
            handler = getattr(self, "cmd_" + cmd[1:].replace("-", "_"), None)
        if handler is not None:
            await handler(arg)
            return
        await self._chat_turn(user_text)

    async def _chat_turn(self, user_text: str) -> None:
        mark = len(self.agent.messages)
        try:
            await self.agent.chat(user_text)
        except asyncio.CancelledError:
            del self.agent.messages[mark:]
            raise
        except Exception as error:
            log.exception("agent turn failed")
            self.say(f"  (turn failed: {type(error).__name__}: {error})")

    # -- slash commands --------------------------------------------------------

    async def cmd_help(self, arg: str) -> None:
        self.say(help_text())

    async def cmd_config(self, arg: str) -> None:
        self.say(config_text(mcp_servers=self.mcp_servers))

    async def cmd_undo(self, arg: str) -> None:
        self.say(undo_last_turn(self.agent))

    async def cmd_safe(self, arg: str) -> None:
        self.agent.safe_mode()
        self.say("  (approval mode: Ask)")

    async def cmd_mode(self, arg: str) -> None:
        agent = self.agent
        requested = arg.strip().lower()
        if requested == "ask":
            agent.safe_mode()
            self.say("  (approval mode: Ask)")
        elif requested == "auto":
            agent.approval_mode = "auto"
            self.say("  (Auto mode: web search and public page reads are approved automatically)")
        elif requested == "auto-edit":
            try:
                agent.enable_auto_edit()
            except ValueError as error:
                self.say(f"  ({error})")
            else:
                self.say("  (Auto-edit enabled for this project session; writes use checkpoints)")
        elif requested == "full-access":
            self.say("  (use /full-access to review its warning and type the confirmation)")
        else:
            self.say("  (usage: /mode ask|auto|auto-edit)")

    async def cmd_full_access(self, arg: str) -> None:
        agent = self.agent
        if not settings.allow_full_access:
            self.say("  (Full Access is disabled by allow_full_access = false.)")
            return
        if not agent.project_active:
            self.say("  (Full Access requires an active managed project.)")
            return
        confirmation = await self.ask_text(
            f"{FULL_ACCESS_WARNING}\n\nType FULL ACCESS to confirm (Esc cancels):", "FULL ACCESS"
        )
        if confirmation != "FULL ACCESS":
            self.say("  (Full Access cancelled)")
            return
        try:
            agent.enable_full_access()
        except ValueError as error:
            self.say(f"  ({error})")
        else:
            self.say("  [safety] Full Access active for this session.")

    async def cmd_subtask(self, arg: str) -> None:
        try:
            self.say(f"  ({await self.agent.start_subtask(arg)})")
        except (OSError, ValueError) as error:
            self.say(f"  (could not start subtask: {error})")
        except Exception as error:
            log.exception("starting subtask failed")
            self.say(f"  (could not summarize prior work: {type(error).__name__})")

    async def cmd_project(self, arg: str) -> None:
        if not arg.strip() or arg.strip() == "list":
            projects = project_tools.list_projects(self.projects_dir)
            active = workspace_tools.WORKSPACE.resolve()
            lines = ["  Projects:"]
            if not projects:
                lines.append("    (none yet)")
            for path in projects:
                marker = " *" if path.resolve() == active else ""
                lines.append(f"    {path.name}{marker}")
            self.say("\n".join(lines))
            return
        try:
            project_arg = arg.strip()
            if project_arg.lower() == "create":
                raise ValueError("usage: /project create NAME")
            if project_arg.lower().startswith("create "):
                name = project_arg.split(maxsplit=1)[1]
                path = project_tools.create_project(name, self.projects_dir)
            else:
                candidate = Path(project_arg).expanduser()
                path = (
                    candidate.resolve() if candidate.is_dir()
                    else project_tools.select_project(project_arg, self.projects_dir)
                )
            self.say(f"  {activate_project(path, self.agent)}")
        except (OSError, ValueError) as error:
            self.say(f"  (project switch failed: {error})")

    async def cmd_think(self, arg: str) -> None:
        agent = self.agent
        mode = arg.strip().lower()
        if mode == "auto":
            agent.thinking_override = None
            self.say("  (thinking: automatic)")
        elif mode in ("on", "off"):
            agent.thinking_override = mode == "on"
            agent.thinking_on = agent.thinking_override
            self.say(f"  (thinking: {mode})")
        elif not mode:
            agent.thinking_on = not agent.thinking_on
            agent.thinking_override = agent.thinking_on
            self.say(f"  (thinking: {'on' if agent.thinking_on else 'off'}; manual)")
        else:
            self.say("  (usage: /think [on|off|auto])")

    async def cmd_parallel(self, arg: str) -> None:
        self.agent.parallel_tools = not self.agent.parallel_tools
        self.say(f"  (parallel tools: {'on' if self.agent.parallel_tools else 'off'})")

    async def cmd_tools(self, arg: str) -> None:
        self.say("\n".join(
            f"  {name}{'  (asks first)' if name in NEEDS_APPROVAL else ''}"
            for name in sorted(self.agent.visible_tool_names())
        ))

    async def cmd_allowed(self, arg: str) -> None:
        agent = self.agent
        persisted = load_approvals(settings.allowed_file)
        if not agent.allowed:
            self.say("  (nothing is remembered; asks again on each new domain)")
            return
        self.say("\n".join(
            f"  {name}: {scope} [{'saved' if (name, scope) in persisted else 'session only'}]"
            for name, scope in sorted(agent.allowed)
        ))

    async def cmd_revoke(self, arg: str) -> None:
        agent = self.agent
        domain = arg.strip().lower().removeprefix("www.").rstrip(".")
        if domain:
            agent.allowed = {item for item in agent.allowed if item[1] != domain}
            message = f"(saved approvals for {domain} revoked)"
        else:
            agent.allowed.clear()
            message = "(all saved domain approvals revoked)"
        try:
            save_approvals(settings.allowed_file, agent.allowed)
        except OSError as error:
            self.say(f"  (could not save revocation: {type(error).__name__})")
        else:
            self.say(f"  {message}")

    async def cmd_memory(self, arg: str) -> None:
        self.say("\n".join(memory_lines(self.agent, arg)))

    async def cmd_tasks(self, arg: str) -> None:
        self.say(task_list("list"))

    async def cmd_stats(self, arg: str) -> None:
        self.say(stats_text(self.agent))

    async def cmd_replay(self, arg: str) -> None:
        agent = self.agent
        parts = arg.split()
        name_ok = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
        if len(parts) == 2 and parts[0] == "start":
            name = parts[1]
            if not re.fullmatch(name_ok, name):
                self.say("  (use a replay name with letters, numbers, _ or -)")
                return
            if agent.replay_recorder:
                agent.replay_recorder.close()
            try:
                replay_file = replay_path(workspace_tools.WORKSPACE, name)
                agent.replay_recorder = SessionRecorder(replay_file)
            except (OSError, ValueError) as error:
                agent.replay_recorder = None
                self.say(f"  (could not start replay recording: {type(error).__name__})")
            else:
                self.say(f"  (recording model requests and tool choices in {replay_file})")
        elif parts == ["stop"]:
            if agent.replay_recorder:
                agent.replay_recorder.close()
                agent.replay_recorder = None
                self.say("  (replay recording stopped)")
            else:
                self.say("  (replay recording is not active)")
        elif parts and parts[0] == "run" and len(parts) in {2, 3}:
            name = parts[1]
            if not re.fullmatch(name_ok, name):
                self.say("  (use a replay name with letters, numbers, _ or -)")
                return
            try:
                replay_file = replay_path(workspace_tools.WORKSPACE, name)
                results = await replay_session(replay_file, model=parts[2] if len(parts) == 3 else None)
                self.say(render_replay(results))
            except (OSError, ValueError, httpx.HTTPError, KeyError, IndexError) as error:
                self.say(f"  (replay failed: {type(error).__name__}: {error})")
        else:
            self.say("  (usage: /replay start NAME | /replay stop | /replay run NAME [MODEL])")

    async def cmd_save(self, arg: str) -> None:
        name = arg.strip()
        result = save_transcript(self.agent, name)
        if "Confirm overwrite" in result:
            if await self.ask_yes_no("A transcript with that name exists. Overwrite it?"):
                result = save_transcript(self.agent, name, overwrite=True)
            else:
                result = "(transcript kept)"
        self.say(f"  ({result})")

    async def cmd_load(self, arg: str) -> None:
        if not arg.strip():
            self.say("  (usage: /load NAME)")
        else:
            self.say(f"  ({load_transcript(self.agent, arg.strip())})")

    async def cmd_audit(self, arg: str) -> None:
        raw_count = arg.strip()
        try:
            count = int(raw_count) if raw_count else 20
        except ValueError:
            count = 0
        self.say(recent_calls(count))

    async def cmd_forget(self, arg: str) -> None:
        arg = arg.strip()
        memory = self.agent.memory
        if arg == "all":
            count = len(memory.list_all())
            if count and await self.ask_yes_no(f"Delete ALL {count} memories?"):
                self.say(f"  ({memory.clear()} memories deleted)")
        elif arg.isdigit():
            self.say("  (forgotten)" if memory.delete(int(arg)) else "  (no memory with that number)")
        else:
            self.say("  usage: /forget 12  or  /forget all")

    async def cmd_prune(self, arg: str) -> None:
        memory = self.agent.memory
        try:
            days = int(arg.strip())
        except ValueError:
            days = 0
        if not 1 <= days <= 36500:
            self.say("  (usage: /prune DAYS — choose 1 to 36500 days)")
            return
        cutoff = date.today() - timedelta(days=days)
        count = memory.count_events_before(cutoff)
        if not count:
            self.say(f"  (no session notes older than {cutoff.isoformat()})")
            return
        lines = [f"  {count} session note(s) are older than {cutoff.isoformat()}:"]
        lines.extend(f"    #{item.id} {item.created} {item.text}" for item in memory.events_before(cutoff))
        if count > 10:
            lines.append(f"    ... and {count - 10} more")
        self.say("\n".join(lines))
        if await self.ask_yes_no("Delete these session notes?"):
            self.say(f"  ({memory.prune_events_before(cutoff)} session note(s) pruned)")
        else:
            self.say("  (nothing pruned)")

    async def cmd_open(self, arg: str) -> None:
        page = find_chart(arg.strip())
        if page is None:
            self.say("  (no chart found. ask Jinni to make one first)")
            return
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
            if not await self.ask_yes_no(
                "This page was not made by the current chart tool, so it may contain scripts. Open anyway?"
            ):
                self.say("  (not opened)")
                return
        if await asyncio.to_thread(webbrowser.open, page.as_uri()):
            self.say(f"  (opened {page.name})")
        else:
            self.say(f"  (could not open a browser. the file is at {page})")

    async def cmd_png(self, arg: str) -> None:
        try:
            name, theme, width, height = parse_export_options(arg.strip())
            page = find_chart(name)
            if page is None:
                self.say("  (no chart found. ask Jinni to make one first)")
                return
            self.say(f"  ({await asyncio.to_thread(export_chart, page, theme, width, height)})")
        except (ExportError, ValueError) as error:
            self.say(f"  (PNG export failed: {error})")

    async def _export_single(self, cmd: str, arg: str) -> None:
        page = find_chart(arg.strip())
        if page is None:
            self.say("  (no chart found. ask Jinni to make one first)")
            return
        try:
            exporter = export_svg if cmd == "svg" else export_pdf
            self.say(f"  ({await asyncio.to_thread(exporter, page)})")
        except ExportError as error:
            self.say(f"  ({cmd.upper()} export failed: {error})")

    async def cmd_svg(self, arg: str) -> None:
        await self._export_single("svg", arg)

    async def cmd_pdf(self, arg: str) -> None:
        await self._export_single("pdf", arg)

    async def cmd_export_all(self, arg: str) -> None:
        try:
            self.say(f"  ({await asyncio.to_thread(export_all, arg.strip().lower() or 'all')})")
        except ValueError as error:
            self.say(f"  (export failed: {error})")

    async def cmd_mcp_table(self, arg: str) -> None:
        if self.manager is None:
            self.say("  (MCP is turned off in config.py)")
            return
        server_name, _, remaining = arg.strip().partition(" ")
        tool_name, _, raw_arguments = remaining.partition(" ")
        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
            result = await export_mcp_table(self.manager, server_name, tool_name, arguments)
            self.say(f"  ({result})")
        except (ValueError, RuntimeError) as error:
            self.say(f"  (MCP table export failed: {error})")

    async def cmd_recall(self, arg: str) -> None:
        found, mode = await asyncio.to_thread(hybrid_search, self.agent.memory, arg.strip())
        lines = [f"  ({len(found)} result(s), {mode} search)"]
        lines.extend(f"  #{m.id} [{m.kind}] {m.text}" for m in found)
        self.say("\n".join(lines))

    async def cmd_reindex(self, arg: str) -> None:
        try:
            self.say(f"  ({await asyncio.to_thread(catch_up, self.agent.memory)} memories embedded)")
        except EmbedError as error:
            self.say(f"  (embeddings server not reachable: {error})")

    async def cmd_mcp(self, arg: str) -> None:
        manager = self.manager
        if manager is None:
            self.say("  (MCP is turned off in config.py)")
            return
        restart_target = mcp_restart_target(arg)
        if restart_target is not None:
            self.say("\n".join(await manager.restart(restart_target)))
        elif arg == "resources" or arg.startswith("resources "):
            self.say("\n".join(manager.resource_lines(arg.partition(" ")[2].strip())))
        elif arg == "prompts" or arg.startswith("prompts "):
            self.say("\n".join(manager.prompt_lines(arg.partition(" ")[2].strip())))
        elif arg.startswith("read "):
            _, _, rest = arg.partition(" ")
            server_name, separator, uri = rest.partition(" ")
            if not separator or not uri.strip():
                self.say("  (usage: /mcp read SERVER URI)")
            else:
                self.say(f"  ({await manager.read_resource(server_name, uri.strip())})")
        elif arg.startswith("prompt "):
            _, _, rest = arg.partition(" ")
            server_name, _, rest = rest.partition(" ")
            prompt_name, separator_args, raw_args = rest.partition(" ")
            try:
                arguments = json.loads(raw_args) if separator_args else {}
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be a JSON object")
                self.say(f"  ({await manager.get_prompt(server_name, prompt_name, arguments)})")
            except (json.JSONDecodeError, ValueError) as error:
                self.say(f"  (MCP prompt failed: {error})")
        else:
            self.say("\n".join(manager.status_lines()))


def main(argv: list[str] | None = None) -> None:
    """Resolve the workspace and config, then launch the Textual app."""
    parser = argparse.ArgumentParser(description="Jinni local AI agent")
    parser.add_argument("--project", help="work directly in this project folder")
    args = parser.parse_args(argv)

    active_workspace = workspace_tools.WORKSPACE
    projects_dir = active_workspace / "projects"
    if args.project:
        active_workspace = Path(args.project).expanduser().resolve()
        if not active_workspace.is_dir():
            parser.error("--project must point to an existing folder")
    workspace_tools.WORKSPACE = active_workspace
    export_all.WORKSPACE = active_workspace
    try:
        project_guidance = project_tools.load_project_guidance(active_workspace)
    except ValueError as error:
        parser.error(str(error))

    setup_logging()
    log.info("started, model=%s", settings.model)
    notes: list[str] = []
    mcp_servers, mcp_warning = resolve_mcp_servers(settings.mcp_servers_file, settings.mcp_servers)
    if mcp_warning:
        log.warning("%s", mcp_warning)
        notes.append(mcp_warning)
    for err in LOAD_ERRORS:
        log.warning("plugin skipped: %s", err)
        notes.append(f"plugin skipped: {err}")

    project_active = bool(args.project) or (active_workspace / ".jinni" / "managed-project").is_file()
    workspace_tools.PROJECT_ACTIVE = project_active

    JinniApp(
        projects_dir=projects_dir,
        project_guidance=project_guidance,
        project_active=project_active,
        mcp_servers=mcp_servers,
        notes=notes,
    ).run()


if __name__ == "__main__":
    main()