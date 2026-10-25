from datetime import date, timedelta

import pytest

from task_store import TaskStore


def test_tasks_survive_reopening_store_and_due_tasks_exclude_completed(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    first = TaskStore(path)
    task = first.add("Send the report", (date.today() - timedelta(days=1)).isoformat())
    second = TaskStore(path)

    assert second.list()[0].text == "Send the report"
    assert [item.id for item in second.due()] == [task.id]
    assert second.mark_done(task.id)
    assert second.due() == []


def test_task_store_validates_text_and_iso_due_dates(tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")

    with pytest.raises(ValueError, match="1 to 200"):
        store.add(" ")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        store.add("A task", "next Friday")
