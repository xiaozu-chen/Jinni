"""In-memory session records owned by the web runtime."""

from dataclasses import dataclass, field


@dataclass
class ChatSession:
    id: str
    title: str
    project_id: str | None
    messages: list[dict[str, object]] = field(default_factory=list)
    summary: str = ""
    context_used: int = 0
    user_display: dict[int, dict[str, object]] = field(default_factory=dict)
    working_window: dict[str, object] = field(default_factory=dict)
    partial_assistant: str | None = None
