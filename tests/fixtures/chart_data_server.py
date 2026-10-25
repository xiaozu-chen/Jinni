import json

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("jinni-chart-fixture")


@mcp.tool()
def get_table(dataset: str = "sales") -> str:
    """Return a small chart-ready table from the local fixture catalog."""
    if dataset != "sales":
        raise ValueError("the fixture provides only the sales dataset")
    return json.dumps({
        "columns": ["month", "revenue", "returns"],
        "rows": [
            ["Jan", 120, 8],
            ["Feb", 135, 11],
            ["Mar", 150, 9],
        ],
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")
