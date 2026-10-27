from tools.registry import tool
from tools import workspace
from runtime.workspace_search import format_results, search_workspace


@tool(
    "Search readable text files in the active project by meaning. Secret files and generated folders are skipped.",
    params={"query": {"type": "string", "description": "What to find in project files"},
            "limit": {"type": "integer", "description": "Maximum matches (1 to 10)"}},
    group="project",
)
def search_workspace_files(query: str, limit: int = 5) -> str:
    """Return the most relevant project file excerpts for a question."""
    results, mode = search_workspace(workspace.WORKSPACE, query, limit)
    return format_results(results, mode)
