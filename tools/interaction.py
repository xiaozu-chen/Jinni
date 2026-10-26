"""Register user-facing clarification and task-list tools backed by persistent local state."""

from contextvars import ContextVar
from collections.abc import Callable

from .registry import tool
import memory.task_store as task_store
from memory.task_store import TaskStore

USER_INPUT_PROVIDER: ContextVar[Callable[[str, str, str], str] | None] = ContextVar(
    "jinni_user_input_provider", default=None,
)


@tool(
    description="Ask one short clarifying question only when a missing detail prevents a safe or useful action. Do not ask instead of checking available workspace tools for files or information.",
    params={
        "question": "A concise question for the user.",
        "choices": "Optional comma-separated suggested answers.",
    },
)
def ask_user(question: str, choices: str = "") -> str:
    if not question.strip() or len(question) > 500:
        return "Error: the question must contain 1 to 500 characters."
    if len(choices) > 200:
        return "Error: suggested choices are limited to 200 characters."
    try:
        provider = USER_INPUT_PROVIDER.get()
        if provider is not None:
            answer = provider("question", question.strip(), choices.strip()).strip()
        else:
            prompt = f"  Jinni asks: {question.strip()}"
            if choices.strip():
                prompt += f" ({choices.strip()})"
            answer = input(prompt + "\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return "The user did not provide an answer."
    return answer or "The user left the answer blank."


def _format_tasks(tasks) -> str:
    if not tasks:
        return "(task list is empty)"
    return "\n".join(
        f"{'[x]' if item.completed else '[ ]'} #{item.id} {item.text}"
        + (f" (due {item.due_date})" if item.due_date else "")
        for item in tasks
    )


def due_tasks(store: TaskStore | None = None) -> str:
    return _format_tasks((store or task_store.get_store()).due())


@tool(
    description="Manage a persistent task list: list, show due tasks, add, complete, remove, or clear tasks.",
    params={
        "action": "One of list, due, add, done, remove, or clear.",
        "task": "Task text for add, or unused for other actions.",
        "task_id": "Task number for done or remove.",
        "due_date": "Optional due date for add in YYYY-MM-DD format.",
    },
)
def task_list(action: str, task: str = "", task_id: int = 0, due_date: str = "") -> str:
    store = task_store.get_store()
    if action == "list":
        return _format_tasks(store.list())
    if action == "due":
        return due_tasks(store)
    if action == "add":
        try:
            item = store.add(task, due_date)
        except ValueError as error:
            return f"Error: {error}."
        suffix = f" (due {item.due_date})" if item.due_date else ""
        return f"Added task #{item.id}: {item.text}{suffix}"
    if action in ("done", "complete"):
        if store.mark_done(task_id):
            return f"Completed task #{task_id}."
        return f"Error: there is no open task #{task_id}."
    if action == "remove":
        return f"Removed task #{task_id}." if store.remove(task_id) else f"Error: there is no task #{task_id}."
    if action == "clear":
        if input("  Clear the whole task list? (y/n) > ").strip().lower() != "y":
            return "(task list kept)"
        return f"Cleared {store.clear()} task(s)."
    return "Error: action must be list, due, add, done, remove, or clear."
