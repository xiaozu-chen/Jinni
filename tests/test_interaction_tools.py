from tools.interaction import ask_user, reset_tasks, task_list


def test_ask_user_returns_answer_and_shows_suggested_choices(monkeypatch):
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "dark")

    answer = ask_user("Which theme?", "light, dark")

    assert answer == "dark"
    assert "Which theme? (light, dark)" in prompts[0]


def test_ask_user_handles_end_of_input(monkeypatch):
    def end_of_input(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", end_of_input)

    assert "did not provide" in ask_user("Choose a color")


def test_session_task_list_adds_completes_removes_and_clears():
    reset_tasks()

    added = task_list("add", "Review the migration")

    assert "#1" in added
    assert "Review the migration" in task_list("list")
    assert "Completed" in task_list("done", task_id=1)
    assert "[x] #1" in task_list("list")
    assert "Removed" in task_list("remove", task_id=1)
    assert "empty" in task_list("list")
    assert "Cleared 0" in task_list("clear")


def test_task_list_rejects_invalid_actions_and_task_text():
    reset_tasks()

    assert task_list("launch").startswith("Error:")
    assert task_list("add", " ").startswith("Error:")
    assert task_list("done", task_id=900).startswith("Error:")
