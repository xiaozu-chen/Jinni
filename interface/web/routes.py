"""HTTP routes for the local desktop client."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from interface.web.schemas import (
    ChatRequest,
    InteractionRequest,
    McpServerCreateRequest,
    McpToolsRequest,
    PermissionDecisionRequest,
    PermissionModeRequest,
    ProjectApplyRequest,
    ProjectRequest,
    ReasoningModeRequest,
    SessionCreateRequest,
    SessionEditRequest,
    SessionUpdateRequest,
    WorkingWindowRequest,
)

router = APIRouter()



def get_runtime(request: Request) -> Any:
    return request.app.state.runtime


@router.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/api/state")
def get_state(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return runtime.state()


@router.get("/api/workspace")
def get_workspace(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return runtime.workspace()


@router.post("/api/sessions")
def create_session(
    body: SessionCreateRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.create_session(body.project_id)


@router.post("/api/sessions/{session_id}/activate")
def activate_session(
    session_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.activate_session(session_id)


@router.patch("/api/sessions/{session_id}")
def update_session(
    session_id: str,
    body: SessionUpdateRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.rename_session(session_id, body.title)


@router.patch("/api/sessions/{session_id}/working-window")
def update_working_window(
    session_id: str,
    body: WorkingWindowRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, bool]:
    runtime.update_working_window(session_id, body)
    return {"saved": True}


@router.delete("/api/sessions/{session_id}")
def delete_session(
    session_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.delete_session(session_id)


@router.get("/api/sessions/{session_id}/export")
def export_session(
    session_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.export_session(session_id)


@router.post("/api/sessions/{session_id}/edit")
def edit_session(
    session_id: str,
    body: SessionEditRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.edit_session(session_id, body.message_index)


@router.post("/api/projects/{project_id}/activate")
def activate_project(
    project_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.activate_project(project_id)


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.remove_project(project_id)


@router.get("/api/projects/{project_id}/changes")
def get_project_changes(
    project_id: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.project_changes(project_id)


@router.post("/api/projects/{project_id}/apply")
def apply_project_changes(
    project_id: str,
    body: ProjectApplyRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.apply_project_changes(project_id, body.snapshot_id)


@router.get("/api/model")
def get_model_status(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return runtime.model_status()


@router.get("/api/mcp")
def get_mcp_status(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return runtime.mcp_status()


@router.post("/api/mcp/restart")
async def restart_mcp(
    runtime: Annotated[Any, Depends(get_runtime)],
    name: Annotated[str, Query(max_length=64)] = "",
) -> dict[str, object]:
    return await runtime.restart_mcp(name)


@router.post("/api/mcp/servers")
async def add_mcp_server(
    body: McpServerCreateRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return await runtime.add_mcp_server(body.name, body.url, body.headers)


@router.patch("/api/mcp/servers/{name}/tools")
async def set_mcp_tools(
    name: str,
    body: McpToolsRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return await runtime.set_mcp_tools(name, body.tools)


@router.delete("/api/mcp/servers/{name}")
async def remove_mcp_server(
    name: str,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return await runtime.remove_mcp_server(name)


@router.get("/api/thinking")
def get_thinking(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return runtime.thinking()


@router.get("/api/actions")
def get_actions(
    runtime: Annotated[Any, Depends(get_runtime)],
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    return {"actions": runtime.actions_after(after)}


@router.get("/api/permission")
def get_permission(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return {"permission": runtime.pending_permission()}


@router.post("/api/permission/{interaction_id}")
def answer_permission(
    interaction_id: str,
    body: PermissionDecisionRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, bool]:
    runtime.answer_permission(interaction_id, body.decision)
    return {"answered": True}


@router.post("/api/reasoning-mode")
def set_reasoning_mode(
    body: ReasoningModeRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, str]:
    runtime.set_reasoning_mode(body.mode)
    return {"mode": body.mode}


@router.post("/api/permission-mode")
def set_permission_mode(
    body: PermissionModeRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, object]:
    return runtime.set_permission_mode(body.mode, body.confirmation)


@router.post("/api/project/select")
def select_project(
    body: ProjectRequest, runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, str]:
    path = runtime.select_project(body.path)
    return {"project": str(path)}


@router.post("/api/project/import")
def import_project(
    body: ProjectRequest, runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, str]:
    source, working_copy = runtime.import_project(body.path)
    return {"project": str(source), "working_copy": str(working_copy)}


@router.post("/api/project/close")
def close_project(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, None]:
    runtime.close_project()
    return {"project": None}


@router.post("/api/chat", status_code=202)
async def chat(
    body: ChatRequest, runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, bool]:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message cannot be blank.")
    runtime.start_chat(message, body.attachments)
    return {"started": True}


@router.post("/api/chat/stop")
def stop_chat(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, bool]:
    runtime.request_stop_chat()
    return {"requested": True}


@router.get("/api/events")
def get_events(
    runtime: Annotated[Any, Depends(get_runtime)],
    after: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    state = runtime.state()
    return {"events": runtime.events_after(after), "busy": state["busy"], "state": state}


@router.post("/api/interactions/{interaction_id}")
def answer_interaction(
    interaction_id: str,
    body: InteractionRequest,
    runtime: Annotated[Any, Depends(get_runtime)],
) -> dict[str, bool]:
    runtime.answer_interaction(interaction_id, body.answer.strip())
    return {"answered": True}


@router.get("/api/session")
def get_session(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, object]:
    return {"messages": runtime.session(), "working_window": runtime.active_working_window()}


@router.delete("/api/session")
def clear_session(runtime: Annotated[Any, Depends(get_runtime)]) -> dict[str, bool]:
    runtime.clear_session()
    return {"cleared": True}
