import json

from starlette.testclient import TestClient

from agent import Agent
from agent_events import AgentEvent
from desktop_api import DesktopBackend, create_app
import task_store
from task_store import TaskStore
from tools import workspace as workspace_tools

TOKEN = "test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def make_test_app():
    return create_app(token=TOKEN, backend=DesktopBackend(start_mcp=False))


def test_api_starts_with_no_project_and_hides_project_tools():
    with TestClient(make_test_app()) as client:
        state = client.get("/api/v1/state", headers=HEADERS).json()
        tools = client.get("/api/v1/tools", headers=HEADERS).json()["tools"]

        assert state["project"] == {"active": False, "path": None, "checkpointing": False}
        assert "list_files" not in {tool["name"] for tool in tools}
        assert client.get("/api/v1/project/files", headers=HEADERS).status_code == 409


def test_project_selection_uses_the_selected_folder_directly(tmp_path):
    folder = tmp_path / "my-project"
    folder.mkdir()
    (folder / "sales.csv").write_text("month,revenue\nJan,120\n", encoding="utf-8")

    with TestClient(make_test_app()) as client:
        selected = client.post(
            "/api/v1/project/select", headers=HEADERS, json={"path": str(folder)},
        )
        assert selected.status_code == 200
        assert selected.json()["path"] == str(folder.resolve())
        assert workspace_tools.WORKSPACE == folder.resolve()
        assert workspace_tools.PROJECT_ACTIVE is True

        file_list = client.get("/api/v1/project/files", headers=HEADERS).json()
        contents = client.get(
            "/api/v1/project/file", headers=HEADERS, params={"path": "sales.csv"},
        ).json()
        tools = client.get("/api/v1/tools", headers=HEADERS).json()["tools"]

        assert "sales.csv" in file_list["tree"]
        assert "Jan,120" in contents["content"]
        assert "list_files" in {tool["name"] for tool in tools}

        closed = client.post("/api/v1/project/close", headers=HEADERS)
        assert closed.json()["active"] is False
        assert workspace_tools.WORKSPACE == workspace_tools.DEFAULT_WORKSPACE
        assert workspace_tools.PROJECT_ACTIVE is False


def test_api_requires_bearer_token_except_health():
    with TestClient(make_test_app()) as client:
        assert client.get("/api/v1/health").json() == {"ok": True, "service": "jinni"}
        assert client.get("/api/v1/state").status_code == 401


def test_mcp_routes_report_disabled_without_starting_servers():
    with TestClient(make_test_app()) as client:
        status = client.get("/api/v1/mcp", headers=HEADERS)
        restart = client.post("/api/v1/mcp/restart", headers=HEADERS, json={})

        assert status.json() == {"status": ["MCP is disabled"]}
        assert restart.status_code == 409


def test_task_endpoints_list_and_update_tasks(monkeypatch, tmp_path):
    store = TaskStore(tmp_path / "tasks.sqlite3")
    monkeypatch.setattr(task_store, "get_store", lambda: store)

    with TestClient(make_test_app()) as client:
        created = client.post(
            "/api/v1/tasks", headers=HEADERS,
            json={"action": "add", "text": "Review release notes"},
        )
        task_id = created.json()["task"]["id"]
        listed = client.get("/api/v1/tasks", headers=HEADERS).json()["items"]
        completed = client.post(
            "/api/v1/tasks", headers=HEADERS,
            json={"action": "done", "task_id": task_id},
        )

        assert created.status_code == 201
        assert listed[0]["text"] == "Review release notes"
        assert completed.json()["updated"] is True


def test_chat_streams_agent_events(monkeypatch):
    async def fake_chat(self, message):
        self.emit(AgentEvent("text_delta", message.upper()))
        self.messages.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": message.upper()},
        ])

    monkeypatch.setattr(Agent, "chat", fake_chat)
    with TestClient(make_test_app()) as client:
        response = client.post("/api/v1/chat", headers=HEADERS, json={"message": "hello"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert '"type": "text_delta", "text": "HELLO"' in response.text
        assert '"type": "turn_complete"' in response.text


def test_ui_can_answer_ask_user_interaction():
    with TestClient(make_test_app()) as client:
        with client.stream(
            "POST", "/api/v1/tools/ask_user", headers=HEADERS,
            json={"arguments": {"question": "Pick a color", "choices": "red, blue"}},
        ) as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if payload["type"] == "interaction_required":
                    answer = client.post(
                        f"/api/v1/interactions/{payload['id']}",
                        headers=HEADERS,
                        json={"answer": "blue"},
                    )
                    assert answer.status_code == 200
                if payload["type"] == "tool_result":
                    assert payload["result"] == "blue"
                if payload["type"] == "turn_complete":
                    break
            else:
                raise AssertionError("SSE stream ended before the tool completed")
