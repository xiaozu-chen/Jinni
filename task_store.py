from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tools import workspace

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    due_date TEXT,
    created TEXT NOT NULL,
    completed TEXT
);
"""


@dataclass(frozen=True)
class Task:
    id: int
    text: str
    due_date: str | None
    created: str
    completed: str | None


class TaskStore:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def add(self, text: str, due_date: str = "") -> Task:
        clean = " ".join(text.split())
        if not clean or len(clean) > 200:
            raise ValueError("task text must contain 1 to 200 characters")
        due = due_date.strip() or None
        if due:
            try:
                date.fromisoformat(due)
            except ValueError:
                raise ValueError("due_date must use YYYY-MM-DD") from None
        created = date.today().isoformat()
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "INSERT INTO tasks (text, due_date, created, completed) VALUES (?, ?, ?, NULL)",
                (clean, due, created),
            )
            task_id = cursor.lastrowid or 0
        return Task(task_id, clean, due, created, None)

    def list(self) -> list[Task]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, text, due_date, created, completed FROM tasks ORDER BY completed IS NOT NULL, due_date IS NULL, due_date, id"
            ).fetchall()
        return [Task(*row) for row in rows]

    def due(self, today: date | None = None) -> list[Task]:
        today = today or date.today()
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, text, due_date, created, completed FROM tasks "
                "WHERE completed IS NULL AND due_date IS NOT NULL AND due_date <= ? "
                "ORDER BY due_date, id",
                (today.isoformat(),),
            ).fetchall()
        return [Task(*row) for row in rows]

    def mark_done(self, task_id: int) -> bool:
        with self.lock, self.conn:
            cursor = self.conn.execute(
                "UPDATE tasks SET completed = ? WHERE id = ? AND completed IS NULL",
                (date.today().isoformat(), int(task_id)),
            )
        return cursor.rowcount > 0

    def remove(self, task_id: int) -> bool:
        with self.lock, self.conn:
            cursor = self.conn.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),))
        return cursor.rowcount > 0

    def clear(self) -> int:
        with self.lock, self.conn:
            cursor = self.conn.execute("DELETE FROM tasks")
        return cursor.rowcount


_stores: dict[Path, TaskStore] = {}
_stores_lock = threading.Lock()


def get_store() -> TaskStore:
    path = (workspace.WORKSPACE / ".jinni" / "tasks.sqlite3").resolve()
    with _stores_lock:
        if path not in _stores:
            path.parent.mkdir(parents=True, exist_ok=True)
            _stores[path] = TaskStore(path)
        return _stores[path]
