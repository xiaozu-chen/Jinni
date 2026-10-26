"""Typed progress events let the agent report work without owning the terminal UI."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    text: str = ""
    details: dict[str, object] = field(default_factory=dict)


EventSink = Callable[[AgentEvent], None]
