from dataclasses import dataclass
from typing import Any

Message = dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str
