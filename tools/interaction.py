from threading import RLock

from .registry import tool

MAX_TASKS = 50
MAX_TASK_CHARS = 200
_tasks: list[dict[str, object]] = []
_next_id = 1
_task_lock = RLock()


@tool(
    description="Ask the user one short clarifying question and return their answer.",
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
    prompt = f"  Jinni asks: {question.strip()}"
    if choices.strip():
        prompt += f" ({choices.strip()})"
    try:
        answer = input(prompt + "\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return "The user did not provide an answer."
    return answer or "The user left the answer blank."


@tool(
    description="Manage a small session task list: list, add, complete, remove, or clear tasks.",
    params={
        "action": "One of list, add, done, remove, or clear.",
        "task": "Task text for add, or unused for other actions.",
        "task_id": "Task number for done or remove.",
    },
)
def task_list(action: str, task: str = "", task_id: int = 0) -> str:
    global _next_id
    with _task_lock:
        if action == "list":
            if not _tasks:
                return "(task list is empty)"
            return "\n".join(
                f"{'[x]' if item['done'] else '[ ]'} #{item['id']} {item['text']}"
                for item in _tasks
            )
        if action == "add":
            clean = task.strip()
            if not clean or len(clean) > MAX_TASK_CHARS:
                return f"Error: task text must contain 1 to {MAX_TASK_CHARS} characters."
            if len(_tasks) >= MAX_TASKS:
                return f"Error: the session task list is limited to {MAX_TASKS} items."
            item = {"id": _next_id, "text": clean, "done": False}
            _tasks.append(item)
            _next_id += 1
            return f"Added task #{item['id']}: {clean}"
        if action in ("done", "remove"):
            item = next((entry for entry in _tasks if entry["id"] == task_id), None)
            if item is None:
                return f"Error: there is no task #{task_id}."
            if action == "done":
                item["done"] = True
                return f"Completed task #{task_id}: {item['text']}"
            _tasks.remove(item)
            return f"Removed task #{task_id}."
        if action == "clear":
            count = len(_tasks)
            _tasks.clear()
            return f"Cleared {count} session task(s)."
        return "Error: action must be list, add, done, remove, or clear."


def reset_tasks() -> None:
    global _next_id
    with _task_lock:
        _tasks.clear()
        _next_id = 1
