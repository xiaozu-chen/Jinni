from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    tools: tuple[str, ...] = ()         # allowlist: tools not listed here never reach the model
    remember: tuple[str, ...] = ()      # allowlisted tools the user may "always allow" per session
    call_timeout: float = 30.0
    mode: str = "auto"                  # "legacy" pins the old protocol if a server misbehaves



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
    memory_prompt_chars: int = 2400
    max_event_chars: int = 600
    recall_results: int = 5

    # semantic recall (optional: needs the embedding server on its own port)
    embed_enabled: bool = True
    embed_url: str = "http://127.0.0.1:8081/v1"
    embed_model: str = "nomic-embed-text-v1.5"
    embed_query_prefix: str = "search_query: "
    embed_doc_prefix: str = "search_document: "
    embed_timeout: float = 15.0
    min_similarity: float = 0.5

    # MCP (optional: Jinni works without any of it)
    mcp_enabled: bool = True
    mcp_servers: tuple[McpServerConfig, ...] = (
        McpServerConfig(name="ddgs", command="ddgs", args=("mcp",), tools=("search_text",)),
    )
    mcp_start_timeout: float = 20.0
    mcp_stop_timeout: float = 5.0
    mcp_result_chars: int = 3000

    # PNG export (uses an installed Edge or Chrome, headless)
    browser_path: str = ""
    png_theme: str = "light"
    png_width: int = 1280
    png_height: int = 720
    png_scale: float = 2.0
    png_timeout: float = 30.0
    png_headless_flag: str = "--headless=new"


settings = Settings()

# terminal colors
GRAY = "\033[90m"
RESET = "\033[0m"
