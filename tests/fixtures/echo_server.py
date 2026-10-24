import asyncio
import os

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("echo-test")


@mcp.tool()
def echo(text: str) -> str:
    """Repeat the text back."""
    return text


@mcp.tool()
def secret() -> str:
    """A tool that must never reach the model."""
    return "classified"


@mcp.tool()
async def slow() -> str:
    """Takes a while."""
    await asyncio.sleep(3)
    return "finally"


@mcp.tool()
def crash() -> str:
    """Kills the whole server process."""
    os._exit(1)


if __name__ == "__main__":
    mcp.run(transport="stdio")
