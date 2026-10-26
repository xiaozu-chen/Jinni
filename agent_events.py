from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    text: str = ""


EventSink = Callable[[AgentEvent], None]
