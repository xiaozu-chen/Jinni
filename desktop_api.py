"""Local HTTP/SSE bridge for the Tauri desktop interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import secrets
import threading
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from agent import Agent
from agent_events import AgentEvent
from config import settings
from models import ToolCall
from mcp_client import McpManager
from mcp_config import resolve_mcp_servers
from project import load_project_guidance
from tools import tool_schemas
from tools import workspace as workspace_tools
from tools.files import project_tree, read_file
import export_all
import task_store

MAX_BODY_BYTES = 128_000
INTERACTION_TIMEOUT = 180
log = logging.getLogger("jinni.desktop_api")
TAURI_ORIGINS = [
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
]


class PendingInteraction:
    def __init__(self, kind: str, prompt: str, choices: str) -> None:
        self.kind = kind
        self.prompt = prompt
        self.choices = choices
        self.ready = threading.Event()
        self.answer = ""


class DesktopBackend:
    """Own the single desktop conversation and bridge its events to SSE clients."""

    def __init__(self, agent_factory: Callable[..., Agent] = Agent, *, start_mcp: bool = True) -> None:
        self.agent_factory = agent_factory
        self.start_mcp = start_mcp
        self.mcp_manager: McpManager | None = None
        self.agent: Agent | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.event_queue: asyncio.Queue[dict[str, Any]] | None = None
        self.turn_task: asyncio.Task[None] | None = None
        self.pending: dict[str, PendingInteraction] = {}

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        workspace_tools.WORKSPACE = workspace_tools.DEFAULT_WORKSPACE
        workspace_tools.PROJECT_ACTIVE = False
        export_all.WORKSPACE = workspace_tools.DEFAULT_WORKSPACE
        if self.start_mcp and settings.mcp_enabled:
            servers, warning = resolve_mcp_servers(settings.mcp_servers_file, settings.mcp_servers)
            if warning:
                log.warning("%s", warning)
            self.mcp_manager = McpManager(servers)
            await self.mcp_manager.start()
        self.agent = self.agent_factory(
            project_active=False,
            event_sink=self.emit,
            interaction_provider=self.request_interaction,
        )

    async def stop(self) -> None:
        if self.mcp_manager:
            await self.mcp_manager.stop()
        if self.turn_task and not self.turn_task.done():
            self._release_interactions("n")
            self.turn_task.cancel()
            try:
                await self.turn_task
            except asyncio.CancelledError:
                pass
        if self.agent:
            await self.agent.client.close()
            if self.agent.thinking_classifier:
                await self.agent.thinking_classifier.close()

    def emit(self, event: AgentEvent) -> None:
        self._publish({"type": event.kind, "text": event.text})

    def _publish(self, payload: dict[str, Any]) -> None:
        queue, loop = self.event_queue, self.loop
        if queue is None or loop is None or not loop.is_running():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            queue.put_nowait(payload)
        else:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    def request_interaction(self, kind: str, prompt: str, choices: str = "") -> str:
        item_id = uuid.uuid4().hex
        pending = PendingInteraction(kind, prompt, choices)
        self.pending[item_id] = pending
        self._publish({
            "type": "interaction_required",
            "id": item_id,
            "kind": kind,
            "prompt": prompt,
            "choices": choices,
        })
        try:
            if not pending.ready.wait(INTERACTION_TIMEOUT):
                return "n" if kind == "approval" else ""
            return pending.answer
        finally:
            self.pending.pop(item_id, None)

    def answer_interaction(self, item_id: str, answer: str) -> bool:
        pending = self.pending.get(item_id)
        if pending is None or pending.ready.is_set():
            return False
        pending.answer = answer
        pending.ready.set()
        return True

    def _release_interactions(self, answer: str) -> None:
        for pending in tuple(self.pending.values()):
            pending.answer = answer
            pending.ready.set()

    def begin_stream(self, operation: Callable[[], Awaitable[None]], request: Request) -> StreamingResponse:
        if self.turn_task and not self.turn_task.done():
            raise ApiError(409, "a chat or tool operation is already running")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.event_queue = queue

        async def run() -> None:
            try:
                await operation()
            except asyncio.CancelledError:
                self._publish({"type": "turn_cancelled"})
            except Exception as error:
                self._publish({"type": "error", "message": str(error)})
            finally:
                self._publish({"type": "turn_complete"})
                self.event_queue = None

        self.turn_task = asyncio.create_task(run())

        async def stream():
            try:
                while True:
                    if await request.is_disconnected():
                        self._release_interactions("n")
                        if self.turn_task and not self.turn_task.done():
                            self.turn_task.cancel()
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    if payload["type"] == "turn_complete":
                        break
            finally:
                if self.turn_task and not self.turn_task.done():
                    self._release_interactions("n")
                    self.turn_task.cancel()

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message


def _backend(request: Request) -> DesktopBackend:
    return request.app.state.backend


def _active_agent(backend: DesktopBackend) -> Agent:
    if backend.agent is None:
        raise ApiError(503, "the Jinni backend has not started")
    return backend.agent


def _project_state(path: Path | None, active: bool) -> dict[str, Any]:
    checkpointing = bool(
        active and path
        and (path / ".jinni" / "managed-project").is_file()
        and (path / ".git").is_dir()
    )
    return {
        "active": active,
        "path": str(path) if active and path else None,
        "checkpointing": checkpointing,
    }


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "request body is too large")
    try:
        value = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApiError(400, "request body must be valid JSON") from None
    if not isinstance(value, dict):
        raise ApiError(400, "request body must be a JSON object")
    return value


async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse({"error": error.message}, status_code=error.status)


async def handle_bad_request(_request: Request, error: Exception) -> JSONResponse:
    return JSONResponse({"error": str(error)}, status_code=400)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "jinni"})


async def state(request: Request) -> JSONResponse:
    backend = _backend(request)
    agent = _active_agent(backend)
    project_active = agent.project_active is True
    path = workspace_tools.WORKSPACE if project_active else None
    return JSONResponse({
        "project": _project_state(path, project_active),
        "busy": bool(backend.turn_task and not backend.turn_task.done()),
        "thinking": {
            "enabled": agent.thinking_on,
            "mode": "auto" if agent.thinking_override is None else ("on" if agent.thinking_override else "off"),
            "classifier_configured": bool(settings.thinking_classifier_model),
        },
        "model": settings.model,
    })


async def select_project(request: Request) -> JSONResponse:
    backend = _backend(request)
    agent = _active_agent(backend)
    if backend.turn_task and not backend.turn_task.done():
        raise ApiError(409, "wait for the current turn before switching projects")
    data = await _body(request)
    raw_path = data.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ApiError(400, "path must be a non-empty directory path")
    selected = Path(raw_path).expanduser()
    if selected.is_symlink():
        raise ApiError(400, "the selected project folder cannot be a symbolic link")
    try:
        root = selected.resolve(strict=True)
    except OSError:
        raise ApiError(400, "the selected project folder does not exist") from None
    if not root.is_dir():
        raise ApiError(400, "the selected project path is not a directory")
    guidance = load_project_guidance(root)
    workspace_tools.WORKSPACE = root
    workspace_tools.PROJECT_ACTIVE = True
    export_all.WORKSPACE = root
    agent.project_guidance = guidance
    agent.project_active = True
    agent.summary = ""
    agent.messages = [{"role": "system", "content": agent.system_prompt}]
    agent.write_checkpoint = None
    agent.apply_memory()
    return JSONResponse({"active": True, "name": root.name, "path": str(root),
                         "checkpointing": _project_state(root, True)["checkpointing"]})


async def close_project(request: Request) -> JSONResponse:
    backend = _backend(request)
    agent = _active_agent(backend)
    if backend.turn_task and not backend.turn_task.done():
        raise ApiError(409, "wait for the current turn before closing the project")
    workspace_tools.WORKSPACE = workspace_tools.DEFAULT_WORKSPACE
    workspace_tools.PROJECT_ACTIVE = False
    export_all.WORKSPACE = workspace_tools.DEFAULT_WORKSPACE
    agent.project_guidance = ""
    agent.project_active = False
    agent.summary = ""
    agent.messages = [{"role": "system", "content": agent.system_prompt}]
    agent.write_checkpoint = None
    agent.apply_memory()
    return JSONResponse({"active": False, "path": None, "checkpointing": False})


def _require_project(agent: Agent) -> None:
    if agent.project_active is not True:
        raise ApiError(409, "select a project folder first")


async def project_files(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    _require_project(agent)
    path = request.query_params.get("path", ".")
    depth = int(request.query_params.get("depth", "3"))
    entries = int(request.query_params.get("limit", "300"))
    if not 1 <= depth <= 8 or not 1 <= entries <= 500:
        raise ApiError(400, "depth must be 1-8 and limit must be 1-500")
    return JSONResponse({"path": path, "tree": project_tree(path, depth, entries)})


async def project_file(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    _require_project(agent)
    path = request.query_params.get("path", "")
    if not path:
        raise ApiError(400, "path is required")
    contents = read_file(path)
    if contents.startswith("Error:"):
        raise ApiError(404, contents)
    return JSONResponse({"path": path, "content": contents})


async def tools_list(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    schemas = tool_schemas(agent.project_active, agent.tool_menu)
    return JSONResponse({"tools": [schema["function"] for schema in schemas]})


async def chat(request: Request) -> StreamingResponse | JSONResponse:
    backend = _backend(request)
    agent = _active_agent(backend)
    data = await _body(request)
    message = data.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 20_000:
        raise ApiError(400, "message must contain 1 to 20,000 characters")
    return backend.begin_stream(lambda: agent.chat(message.strip()), request)


async def invoke_tool(request: Request) -> StreamingResponse | JSONResponse:
    backend = _backend(request)
    agent = _active_agent(backend)
    name = request.path_params["name"]
    if name not in agent.visible_tool_names():
        raise ApiError(404, "tool is not available in the current project state")
    data = await _body(request)
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ApiError(400, "arguments must be a JSON object")

    async def run() -> None:
        call = ToolCall(id=uuid.uuid4().hex, name=name, arguments=json.dumps(arguments))
        result = await agent.run_tools([call])
        backend._publish({"type": "tool_result", "name": name, "result": result[0]})

    return backend.begin_stream(run, request)


async def cancel_chat(request: Request) -> JSONResponse:
    backend = _backend(request)
    if not backend.turn_task or backend.turn_task.done():
        raise ApiError(409, "there is no active turn")
    backend._release_interactions("n")
    backend.turn_task.cancel()
    return JSONResponse({"cancelled": True}, status_code=202)


async def answer_interaction(request: Request) -> JSONResponse:
    backend = _backend(request)
    data = await _body(request)
    answer = data.get("answer")
    if not isinstance(answer, str) or len(answer) > 2_000:
        raise ApiError(400, "answer must be a string up to 2,000 characters")
    if not backend.answer_interaction(request.path_params["item_id"], answer):
        raise ApiError(404, "interaction is no longer waiting for an answer")
    return JSONResponse({"accepted": True})


async def session(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    messages = []
    for item in agent.messages[1:]:
        value: dict[str, Any] = {"role": item.get("role", ""), "content": item.get("content") or ""}
        tool_calls = item.get("tool_calls") or []
        if tool_calls:
            value["tools"] = [call.get("function", {}).get("name", "") for call in tool_calls]
        messages.append(value)
    return JSONResponse({"messages": messages, "summary": agent.summary})


async def clear_session(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    backend = _backend(request)
    if backend.turn_task and not backend.turn_task.done():
        raise ApiError(409, "wait for the current turn before clearing the session")
    agent.summary = ""
    agent.messages = [{"role": "system", "content": agent.system_prompt}]
    agent.write_checkpoint = None
    agent.apply_memory()
    return JSONResponse({"cleared": True})


async def undo_turn(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    backend = _backend(request)
    if backend.turn_task and not backend.turn_task.done():
        raise ApiError(409, "wait for the current turn before undoing it")
    user_index = next(
        (index for index in range(len(agent.messages) - 1, 0, -1)
         if agent.messages[index].get("role") == "user"), None,
    )
    if user_index is None:
        return JSONResponse({"undone": False, "message": "no chat turn to undo"})
    restored = False
    if agent.write_checkpoint:
        import project as project_tools

        restored = project_tools.undo_last_checkpoint(workspace_tools.WORKSPACE)
        agent.write_checkpoint = None
    del agent.messages[user_index:]
    agent.apply_memory()
    return JSONResponse({"undone": True, "checkpoint_restored": restored})


async def thinking(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    if request.method == "PUT":
        data = await _body(request)
        mode = data.get("mode")
        if mode not in {"on", "off", "auto"}:
            raise ApiError(400, "mode must be on, off, or auto")
        agent.thinking_override = None if mode == "auto" else mode == "on"
        agent.thinking_on = settings.thinking_default if mode == "auto" else mode == "on"
    mode = "auto" if agent.thinking_override is None else ("on" if agent.thinking_override else "off")
    return JSONResponse({"mode": mode, "enabled": agent.thinking_on})


async def stats(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    return JSONResponse({
        **agent.stats,
        "total_tokens": agent.stats["prompt_tokens"] + agent.stats["completion_tokens"],
        "tool_calls": dict(agent.tool_counts),
    })


async def mcp_status(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    return JSONResponse({"status": manager.status_lines() if manager else ["MCP is disabled"]})


async def mcp_restart(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    if manager is None:
        raise ApiError(409, "MCP is disabled")
    data = await _body(request)
    server = data.get("server", "")
    if not isinstance(server, str):
        raise ApiError(400, "server must be a string")
    return JSONResponse({"status": await manager.restart(server)})


async def mcp_resources(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    if manager is None:
        raise ApiError(409, "MCP is disabled")
    return JSONResponse({"resources": manager.resource_lines(request.path_params["server"])})


async def mcp_read_resource(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    if manager is None:
        raise ApiError(409, "MCP is disabled")
    data = await _body(request)
    uri = data.get("uri")
    if not isinstance(uri, str) or not uri:
        raise ApiError(400, "uri must be a non-empty string")
    result = await manager.read_resource(request.path_params["server"], uri)
    return JSONResponse({"content": result})


async def mcp_prompts(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    if manager is None:
        raise ApiError(409, "MCP is disabled")
    return JSONResponse({"prompts": manager.prompt_lines(request.path_params["server"])})


async def mcp_prompt(request: Request) -> JSONResponse:
    manager = _backend(request).mcp_manager
    if manager is None:
        raise ApiError(409, "MCP is disabled")
    data = await _body(request)
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in arguments.items()
    ):
        raise ApiError(400, "arguments must be a JSON object of strings")
    result = await manager.get_prompt(request.path_params["server"], request.path_params["name"], arguments)
    return JSONResponse({"content": result})


async def memories(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    limit = min(500, max(1, int(request.query_params.get("limit", "100"))))
    items = agent.memory.list_all()[-limit:]
    return JSONResponse({"items": [item.__dict__ for item in items]})


async def search_memories(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    data = await _body(request)
    query = data.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ApiError(400, "query must be a non-empty string")
    limit = data.get("limit", 5)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise ApiError(400, "limit must be an integer from 1 to 20")
    import semantic

    found, mode = await asyncio.to_thread(semantic.hybrid_search, agent.memory, query.strip(), limit)
    return JSONResponse({"mode": mode, "items": [item.__dict__ for item in found]})


async def forget_memory(request: Request) -> JSONResponse:
    agent = _active_agent(_backend(request))
    if not agent.memory.delete(request.path_params["memory_id"]):
        raise ApiError(404, "memory id not found")
    return JSONResponse({"deleted": True})


async def tasks(request: Request) -> JSONResponse:
    store = task_store.get_store()
    due_only = request.query_params.get("due", "false").lower() == "true"
    items = store.due() if due_only else store.list()
    return JSONResponse({"items": [item.__dict__ for item in items]})


async def mutate_tasks(request: Request) -> JSONResponse:
    data = await _body(request)
    action = data.get("action")
    store = task_store.get_store()
    if action == "add":
        text, due_date = data.get("text"), data.get("due_date", "")
        if not isinstance(text, str) or not isinstance(due_date, str):
            raise ApiError(400, "text and due_date must be strings")
        item = store.add(text, due_date)
        return JSONResponse({"task": item.__dict__}, status_code=201)
    if action in {"done", "remove"}:
        task_id = data.get("task_id")
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            raise ApiError(400, "task_id must be a positive integer")
        changed = store.mark_done(task_id) if action == "done" else store.remove(task_id)
        if not changed:
            raise ApiError(404, "open task not found")
        return JSONResponse({"updated": True, "action": action, "task_id": task_id})
    if action == "clear":
        if data.get("confirmed") is not True:
            raise ApiError(409, "confirm clearing the task list")
        return JSONResponse({"deleted": store.clear()})
    raise ApiError(400, "action must be add, done, remove, or clear")


class BearerTokenMiddleware:
    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] != "/api/v1/health" and scope["method"] != "OPTIONS":
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"").decode("latin1")
            if not secrets.compare_digest(supplied, f"Bearer {self.token}"):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(token: str | None = None, backend: DesktopBackend | None = None) -> Starlette:
    api_token = token or os.environ.get("JINNI_API_TOKEN") or secrets.token_urlsafe(32)
    runtime = backend or DesktopBackend()

    @asynccontextmanager
    async def lifespan(_app):
        await runtime.start()
        yield
        await runtime.stop()

    routes = [
        Route("/api/v1/health", health, methods=["GET"]),
        Route("/api/v1/state", state, methods=["GET"]),
        Route("/api/v1/project/select", select_project, methods=["POST"]),
        Route("/api/v1/project/close", close_project, methods=["POST"]),
        Route("/api/v1/project/files", project_files, methods=["GET"]),
        Route("/api/v1/project/file", project_file, methods=["GET"]),
        Route("/api/v1/tools", tools_list, methods=["GET"]),
        Route("/api/v1/tools/{name:str}", invoke_tool, methods=["POST"]),
        Route("/api/v1/chat", chat, methods=["POST"]),
        Route("/api/v1/chat/cancel", cancel_chat, methods=["POST"]),
        Route("/api/v1/interactions/{item_id:str}", answer_interaction, methods=["POST"]),
        Route("/api/v1/session", session, methods=["GET"]),
        Route("/api/v1/session", clear_session, methods=["DELETE"]),
        Route("/api/v1/session/undo", undo_turn, methods=["POST"]),
        Route("/api/v1/thinking", thinking, methods=["GET", "PUT"]),
        Route("/api/v1/stats", stats, methods=["GET"]),
        Route("/api/v1/mcp", mcp_status, methods=["GET"]),
        Route("/api/v1/mcp/restart", mcp_restart, methods=["POST"]),
        Route("/api/v1/mcp/{server:str}/resources", mcp_resources, methods=["GET"]),
        Route("/api/v1/mcp/{server:str}/resources/read", mcp_read_resource, methods=["POST"]),
        Route("/api/v1/mcp/{server:str}/prompts", mcp_prompts, methods=["GET"]),
        Route("/api/v1/mcp/{server:str}/prompts/{name:str}", mcp_prompt, methods=["POST"]),
        Route("/api/v1/memories", memories, methods=["GET"]),
        Route("/api/v1/memories/search", search_memories, methods=["POST"]),
        Route("/api/v1/memories/{memory_id:int}", forget_memory, methods=["DELETE"]),
        Route("/api/v1/tasks", tasks, methods=["GET"]),
        Route("/api/v1/tasks", mutate_tasks, methods=["POST"]),
    ]
    app = Starlette(
        routes=routes,
        lifespan=lifespan,
        exception_handlers={ApiError: handle_api_error, ValueError: handle_bad_request, OSError: handle_bad_request},
        middleware=[
            Middleware(CORSMiddleware, allow_origins=TAURI_ORIGINS,
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["Authorization", "Content-Type"]),
            Middleware(BearerTokenMiddleware, token=api_token),
        ],
    )
    app.state.backend = runtime
    app.state.api_token = api_token
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Jinni local desktop API")
    parser.add_argument("--port", type=int, default=int(os.environ.get("JINNI_API_PORT", "8765")))
    args = parser.parse_args()
    token = os.environ.get("JINNI_API_TOKEN") or secrets.token_urlsafe(32)
    print(json.dumps({
        "event": "ready",
        "url": f"http://127.0.0.1:{args.port}",
        "token": token,
    }), flush=True)
    uvicorn.run(create_app(token), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
