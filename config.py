from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # server
    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = "qwen3.5"

    # agent
    system_prompt: str = "You are Jinni, a helpful local AI agent. Keep answers concise."
    max_steps: int = 8
    thinking_default: bool = False

    # context management
    context_limit: int = 16384 # must match the -c of llama-server
    compact_at: float = 0.7 
    keep_recent: int = 3
    summarize_at: float = 0.8
    keep_turns: int = 2

    # files
    memory_file: Path = Path("memory.txt")

    # reliability
    request_timeout: float = 120.0
    retry_attempts: int = 3
    retry_delay: float = 1.0
    parallel_tools: bool = True

    # logging
    log_file: Path = Path("jinni.log")

    # search
    search_backend: str = "auto"
    search_region: str = "us-en"

    # memory
    memory_db: Path = Path("memory.db")
    max_facts: int = 20
    max_fact_chars: int = 200
    max_event_chars: int = 600
    recall_results: int = 5


settings = Settings()

# terminal colors
GRAY = "\033[90m"
RESET = "\033[0m"