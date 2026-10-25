import json
import math
import re
from pathlib import Path

from config import McpServerConfig

MAX_CONFIG_BYTES = 100_000
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_FIELDS = {"name", "command", "args", "env", "tools", "remember", "call_timeout", "mode"}


def _string_list(value, field: str, server_index: int) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"server {server_index}: '{field}' must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"server {server_index}: '{field}' entries must be unique")
    return tuple(value)


def load_mcp_servers(path: Path | str) -> tuple[McpServerConfig, ...]:
    config_path = Path(path)
    if config_path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError(f"MCP config is larger than {MAX_CONFIG_BYTES:,} bytes")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read MCP JSON ({type(error).__name__})") from None
    if not isinstance(data, dict) or set(data) != {"servers"} or not isinstance(data["servers"], list):
        raise ValueError("MCP JSON must be an object with a 'servers' list")

    servers = []
    names = set()
    for index, item in enumerate(data["servers"], 1):
        if not isinstance(item, dict) or set(item) - ALLOWED_FIELDS:
            raise ValueError(f"server {index}: expected an object with supported MCP fields")
        name, command = item.get("name"), item.get("command")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name) or name in names:
            raise ValueError(f"server {index}: name must be unique and use letters, numbers, '_' or '-'")
        if not isinstance(command, str) or not command.strip() or len(command) > 512:
            raise ValueError(f"server {index}: command must contain 1 to 512 characters")
        args = _string_list(item.get("args", []), "args", index)
        tools = _string_list(item.get("tools", []), "tools", index)
        remember = _string_list(item.get("remember", []), "remember", index)
        if not set(remember) <= set(tools):
            raise ValueError(f"server {index}: remembered tools must also be allowlisted")
        env = item.get("env", {})
        if not isinstance(env, dict) or any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in env.items()
        ):
            raise ValueError(f"server {index}: env must map strings to strings")
        timeout = item.get("call_timeout", 30.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0.1 <= timeout <= 300:
            raise ValueError(f"server {index}: call_timeout must be between 0.1 and 300 seconds")
        mode = item.get("mode", "auto")
        if mode not in ("auto", "legacy"):
            raise ValueError(f"server {index}: mode must be 'auto' or 'legacy'")
        servers.append(McpServerConfig(
            name=name,
            command=command,
            args=args,
            env=tuple(env.items()),
            tools=tools,
            remember=remember,
            call_timeout=float(timeout),
            mode=mode,
        ))
        names.add(name)
    return tuple(servers)


def resolve_mcp_servers(path: Path | str, fallback: tuple[McpServerConfig, ...]):
    try:
        return load_mcp_servers(path), ""
    except FileNotFoundError:
        return fallback, ""
    except OSError as error:
        return fallback, f"MCP JSON ignored: could not read it ({type(error).__name__}); using built-in server settings."
    except ValueError as error:
        return fallback, f"MCP JSON ignored: {error}; using built-in server settings."
