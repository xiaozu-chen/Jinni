"""MCP server lifecycle and configuration for the local web runtime."""

import json
import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException

from server.mcp_client import McpManager
from server.mcp_config import resolve_mcp_servers
from settings.config import settings

log = logging.getLogger("jinni.web")


class McpRuntime:
    """Own configured MCP servers and serialize live configuration changes."""

    def __init__(self, lock: threading.RLock, ensure_idle: Callable[[str], None]) -> None:
        self.lock = lock
        self.ensure_idle = ensure_idle
        self.configs, self.warning = resolve_mcp_servers(settings.mcp_servers_file, settings.mcp_servers)
        self.manager = McpManager(self.configs) if settings.mcp_enabled else None
        self.reconfiguring = False

    def status(self) -> dict[str, object]:
        if not settings.mcp_enabled or self.manager is None:
            return {"enabled": False, "warning": self.warning, "servers": []}
        manager = self.manager
        return {
            "enabled": True,
            "warning": self.warning,
            "servers": [
                {
                    "name": name,
                    "url": server.cfg.url,
                    "state": server.state,
                    "error": server.error,
                    "tools": manager.exposed.get(name, []),
                    "allowed_tools": list(server.cfg.tools),
                    "available_tools": [tool.name for tool in server.tools],
                    "hidden_tools": manager.hidden.get(name, []),
                    "restart_pending": name in manager._restart_tasks,
                }
                for name, server in manager.servers.items()
            ],
        }

    @asynccontextmanager
    async def _operation(self, action: str):
        with self.lock:
            self.ensure_idle(action)
            if not settings.mcp_enabled or self.manager is None:
                raise HTTPException(status_code=409, detail="MCP servers are disabled.")
            self.reconfiguring = True
        try:
            yield
        finally:
            with self.lock:
                self.reconfiguring = False

    async def restart(self, name: str = "") -> dict[str, object]:
        async with self._operation("restart MCP servers"):
            manager = self.manager
            assert manager is not None
            if name and name not in manager.servers:
                raise HTTPException(status_code=404, detail="MCP server was not found.")
            await manager.restart(name)
            return self.status()

    async def add_server(self, name: str, url: str, headers: dict[str, str]) -> dict[str, object]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="Enter a valid HTTP or HTTPS MCP server URL.")
        async with self._operation("change MCP servers"):
            if any(config.name == name for config in self.configs):
                raise HTTPException(status_code=409, detail="An MCP server with that name already exists.")
            if len(headers) > 30 or any(
                not key.strip() or len(key) > 200 or len(value) > 4000
                for key, value in headers.items()
            ):
                raise HTTPException(status_code=422, detail="Custom headers are invalid or too large.")
            from settings.config import McpServerConfig

            config = McpServerConfig(name=name, url=url, headers=tuple(headers.items()))
            await self._replace_configs((*self.configs, config))
            return self.status()

    async def set_tools(self, name: str, tools: list[str]) -> dict[str, object]:
        async with self._operation("change MCP tools"):
            config = next((item for item in self.configs if item.name == name), None)
            if config is None:
                raise HTTPException(status_code=404, detail="MCP server was not found.")
            server = self.manager.servers.get(name) if self.manager else None
            offered = {tool.name for tool in (server.tools if server else [])}
            if len(set(tools)) != len(tools) or any(tool not in offered for tool in tools):
                raise HTTPException(status_code=422, detail="Select only tools currently offered by this server.")
            updated = tuple(
                replace(item, tools=tuple(tools), remember=tuple(tool for tool in item.remember if tool in tools))
                if item.name == name else item
                for item in self.configs
            )
            await self._replace_configs(updated)
            return self.status()

    async def remove_server(self, name: str) -> dict[str, object]:
        async with self._operation("remove MCP servers"):
            if not any(config.name == name for config in self.configs):
                raise HTTPException(status_code=404, detail="MCP server was not found.")
            await self._replace_configs(tuple(config for config in self.configs if config.name != name))
            return self.status()

    async def _replace_configs(self, configs) -> None:
        path = settings.mcp_servers_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"servers": [
            {
                "name": config.name,
                **({"url": config.url} if config.url else {
                    "command": config.command,
                    "args": list(config.args),
                    "env": dict(config.env),
                }),
                "headers": dict(config.headers),
                "tools": list(config.tools),
                "remember": list(config.remember),
                "resources": list(config.resources),
                "prompts": list(config.prompts),
                "call_timeout": config.call_timeout,
                "mode": config.mode,
            }
            for config in configs
        ]}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=f"{path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    log.debug("could not remove temporary MCP config file %s", temporary)

        if self.manager is not None:
            await self.manager.stop()
            self.configs = tuple(configs)
            self.manager = McpManager(self.configs)
            await self.manager.start()
