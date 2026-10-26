"""Typed progress events let the agent report work without owning the terminal UI."""

from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    text: str = ""


EventSink = Callable[[AgentEvent], None]
