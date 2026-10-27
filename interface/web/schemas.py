"""Validated request models for the local web API."""

from typing import Literal

from pydantic import BaseModel, Field


class TextAttachmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=100_000)
    mime_type: str = Field(default="text/plain", max_length=120)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    attachments: list[TextAttachmentRequest] = Field(default_factory=list, max_length=12)


class ProjectRequest(BaseModel):
    path: str


class ProjectApplyRequest(BaseModel):
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class SessionCreateRequest(BaseModel):
    project_id: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SessionEditRequest(BaseModel):
    message_index: int = Field(ge=0)


class WorkingWindowRequest(BaseModel):
    activities: list[dict[str, object]] = Field(max_length=2000)
    action_details: list[str] = Field(alias="actionDetails", max_length=2000)
    visible: bool = False
    expanded: bool = False
    actions_expanded: bool = Field(default=True, alias="actionsExpanded")
    elapsed_seconds: int = Field(default=0, ge=0, alias="elapsedSeconds")


class InteractionRequest(BaseModel):
    answer: str = Field(min_length=1)


class ReasoningModeRequest(BaseModel):
    mode: Literal["auto", "thinking", "fast"]


class PermissionModeRequest(BaseModel):
    mode: Literal["ask", "auto", "auto-edit", "full-access"]
    confirmation: str = ""


class AutoEditUndoRequest(BaseModel):
    checkpoint_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class McpServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    url: str = Field(min_length=8, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)


class McpToolsRequest(BaseModel):
    tools: list[str] = Field(max_length=200)


class PermissionDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "always"]
