import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


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
    allowed_file: Path = Path("workspace/.jinni/allowed.json")
    max_facts: int = 20
    max_fact_chars: int = 200
    memory_prompt_chars: int = 2400
    max_event_chars: int = 600
    recall_results: int = 5
    near_duplicate_similarity: float = 0.82

    # semantic recall (optional: needs the embedding server on its own port)
    embed_enabled: bool = True
    embed_url: str = "http://127.0.0.1:8081/v1"
    embed_server_command: str = ""
    embed_server_args: tuple[str, ...] = ()
    embed_server_start_timeout: float = 20.0
    embed_server_stop_timeout: float = 5.0
    embed_model: str = "nomic-embed-text-v1.5"
    embed_query_prefix: str = "search_query: "
    embed_doc_prefix: str = "search_document: "
    embed_prefixes: tuple[tuple[str, str, str], ...] = (
        ("nomic-embed-text-v1.5", "search_query: ", "search_document: "),
    )
    embed_timeout: float = 15.0
    min_similarity: float = 0.512

    # MCP (optional: Jinni works without any of it)
    mcp_enabled: bool = True
    mcp_servers_file: Path = Path("mcp_servers.json")
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


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path or os.environ.get("JINNI_SETTINGS", "settings.toml"))
    if not config_path.exists():
        return Settings()

    with config_path.open("rb") as stream:
        values = tomllib.load(stream)
    if not isinstance(values, dict):
        raise ValueError("settings TOML must contain a table")

    known = {item.name for item in fields(Settings)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")

    defaults = Settings()
    parsed: dict[str, Any] = {}
    for name, value in values.items():
        default = getattr(defaults, name)
        if isinstance(default, Path):
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a path string")
            parsed[name] = Path(value)
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false")
            parsed[name] = value
        elif isinstance(default, int):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"{name} must be an integer")
            parsed[name] = value
        elif isinstance(default, float):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            parsed[name] = float(value)
        elif isinstance(default, str):
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            parsed[name] = value
        elif name == "embed_prefixes":
            if (not isinstance(value, list) or any(
                not isinstance(item, list) or len(item) != 3
                or any(not isinstance(part, str) for part in item)
                for item in value
            )):
                raise ValueError("embed_prefixes must be arrays of three strings")
            parsed[name] = tuple(tuple(item) for item in value)
        elif name == "embed_server_args":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError("embed_server_args must be an array of strings")
            parsed[name] = tuple(value)
        elif name == "mcp_servers":
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError("mcp_servers must be an array of tables")
            parsed[name] = tuple(_parse_mcp_server(item) for item in value)
        else:
            raise ValueError(f"unsupported setting type: {name}")

    if "near_duplicate_similarity" in parsed and not 0.0 <= parsed["near_duplicate_similarity"] <= 1.0:
        raise ValueError("near_duplicate_similarity must be between 0 and 1")
    for timeout in ("embed_server_start_timeout", "embed_server_stop_timeout"):
        if timeout in parsed and parsed[timeout] <= 0:
            raise ValueError(f"{timeout} must be positive")
    return Settings(**parsed)


def _parse_mcp_server(value: dict[str, Any]) -> McpServerConfig:
    known = {item.name for item in fields(McpServerConfig)}
    unknown = set(value) - known
    if unknown:
        raise ValueError(f"unknown MCP server fields: {', '.join(sorted(unknown))}")
    data = dict(value)
    for name in ("args", "tools", "remember"):
        if name in data:
            items = data[name]
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"MCP server {name} must be an array of strings")
            data[name] = tuple(items)
    if "env" in data:
        env = data["env"]
        if not isinstance(env, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in env.items()
        ):
            raise ValueError("MCP server env must be a table of strings")
        data["env"] = tuple(sorted(env.items()))
    for name in ("name", "command", "mode"):
        if name in data and not isinstance(data[name], str):
            raise ValueError(f"MCP server {name} must be a string")
    if "call_timeout" in data and (
        not isinstance(data["call_timeout"], (int, float))
        or isinstance(data["call_timeout"], bool)
    ):
        raise ValueError("MCP server call_timeout must be a number")
    return McpServerConfig(**data)


settings = load_settings()

# terminal colors
GRAY = "\033[90m"
RESET = "\033[0m"
