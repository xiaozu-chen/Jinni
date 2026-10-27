"""Expose the opt-in, read-only subagent entry point."""

from settings.config import settings
from .registry import add_tool

DELEGATE_DESCRIPTION = (
    "Hand ONE narrow, read-only research job to a helper that has a fresh context, for example "
    "find where X is defined or summarize what module Y does. The helper can only read and search "
    "the project. It returns file:line pointers and a short summary. Read the cited lines yourself "
    "before relying on them. Do not use it for edits, or for questions you can answer with a single read."
)


async def delegate(task: str) -> str:
    """Run one isolated lookup; the child cannot write or start another child."""
    from runtime.subagent import ERROR_NESTED, SUBAGENT_DEPTH, run_subagent
    from permission.policy import SESSION_TAINTED

    if SUBAGENT_DEPTH.get() > 0:
        return ERROR_NESTED
    return await run_subagent(task, session_tainted=SESSION_TAINTED.get())


def register_delegate(enabled: bool) -> None:
    if not enabled:
        return
    add_tool(
        "delegate",
        delegate,
        DELEGATE_DESCRIPTION,
        {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "One narrow question or lookup in one or two sentences. Include file or symbol names if you know them.",
                },
            },
            "required": ["task"],
        },
    )


register_delegate(settings.subagents_enabled)
