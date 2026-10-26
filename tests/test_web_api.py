import threading

from fastapi.testclient import TestClient

import interface.web.api as web_api


class FakeAgent:
    def __init__(self, **kwargs):
        self.system_prompt = "system"
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.summary = ""
        self.project_guidance = ""
        self.thinking_on = False
        self.thinking_override = None
        self.context_used = 0
        self.allowed = set()
        self.project_active = False
        self.event_sink = kwargs["event_sink"]

    def set_project_active(self, active):
        self.project_active = active

    def apply_memory(self):
        pass

    async def chat(self, message):
        self.messages.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Hello from Jinni."},
        ])
        self.event_sink(web_api.AgentEvent("text_delta", "Hello from Jinni."))


def test_api_chat_and_session(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        assert client.get("/api/health").json() == {"ok": True}
        response = client.post("/api/chat", json={"message": "Hi"})
        assert response.status_code == 202
        assert response.json() == {"started": True}

        for _ in range(100):
            state = client.get("/api/state").json()
            if not state["busy"]:
                break
            threading.Event().wait(0.01)
        assert not state["busy"]
        assert client.get("/api/session").json()["messages"] == [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello from Jinni."},
        ]
        events = client.get("/api/events").json()["events"]
        assert [event["type"] for event in events] == [
            "user_message", "text_delta", "turn_complete",
        ]
        assert client.delete("/api/session").json() == {"cleared": True}
        assert client.get("/api/session").json()["messages"] == []


def test_session_lifecycle_and_edit(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        initial = client.get("/api/workspace").json()["active_session_id"]
        assert client.post("/api/chat", json={"message": "Keep this message"}).status_code == 202
        for _ in range(100):
            if not client.get("/api/state").json()["busy"]:
                break
            threading.Event().wait(0.01)

        second = client.post("/api/sessions", json={}).json()
        assert second["id"] != initial
        assert client.get("/api/session").json()["messages"] == []
        assert client.post(f"/api/sessions/{initial}/activate").status_code == 200
        assert client.get("/api/session").json()["messages"][0]["content"] == "Keep this message"

        edited = client.post(
            f"/api/sessions/{initial}/edit",
            json={"message_index": 0},
        )
        assert edited.json() == {"message": "Keep this message", "attachments": []}
        assert client.get("/api/session").json()["messages"] == []

        assert client.delete(f"/api/sessions/{initial}").status_code == 200
        workspace = client.get("/api/workspace").json()
        assert workspace["active_session_id"] != initial
        assert all(session["id"] != initial for session in workspace["sessions"])


def test_projects_and_session_export_preserve_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api, "load_project_guidance", lambda _path: "")
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path / "workspace")
    project = tmp_path / "project"
    project.mkdir()

    with TestClient(web_api.app) as client:
        assert client.post("/api/project/select", json={"path": str(project)}).status_code == 200
        workspace = client.get("/api/workspace").json()
        project_info = workspace["projects"][0]
        project_session = workspace["active_session_id"]
        assert workspace["sessions"][-1]["project_id"] == project_info["id"]

        attachment = {
            "name": "notes.txt",
            "content": "attached content",
            "mime_type": "text/plain",
        }
        assert client.post(
            "/api/chat",
            json={"message": "Review this", "attachments": [attachment]},
        ).status_code == 202
        for _ in range(100):
            if not client.get("/api/state").json()["busy"]:
                break
            threading.Event().wait(0.01)

        messages = client.get("/api/session").json()["messages"]
        assert messages[0] == {
            "role": "user",
            "content": "Review this",
            "attachments": [attachment],
        }
        exported = client.get(f"/api/sessions/{project_session}/export").json()
        assert exported["messages"][0] == messages[0]
        assert client.post(f"/api/projects/{project_info['id']}/activate").status_code == 200
        assert client.delete(f"/api/projects/{project_info['id']}").status_code == 200
        assert project.is_dir()
        assert client.get("/api/state").json()["project"] is None

        oversized = [
            {"name": f"{index}.txt", "content": "x" * 100_000, "mime_type": "text/plain"}
            for index in range(4)
        ]
        response = client.post(
            "/api/chat",
            json={"message": "Too much", "attachments": oversized},
        )
        assert response.status_code == 413


def test_failed_project_activation_keeps_current_session(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())

    def load_guidance(path):
        if not path.is_dir():
            raise OSError("Project folder is unavailable.")
        return ""

    monkeypatch.setattr(web_api, "load_project_guidance", load_guidance)
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path / "workspace")
    project = tmp_path / "project"
    project.mkdir()

    with TestClient(web_api.app) as client:
        client.post("/api/project/select", json={"path": str(project)})
        project_session = client.get("/api/state").json()["active_session_id"]
        default_session = client.post("/api/sessions", json={}).json()["id"]
        project.rmdir()

        response = client.post(f"/api/sessions/{project_session}/activate")
        assert response.status_code == 400
        state = client.get("/api/state").json()
        assert state["active_session_id"] == default_session
        assert state["project"] is None


def test_project_and_busy_validation(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path / "workspace")
    project = tmp_path / "project"
    project.mkdir()

    with TestClient(web_api.app) as client:
        response = client.post("/api/project/select", json={"path": str(project)})
        assert response.status_code == 200
        assert response.json()["project"] == str(project.resolve())
        assert client.get("/api/state").json()["project"] == str(project.resolve())
        assert client.post("/api/project/close").json() == {"project": None}

        runtime = client.app.state.runtime
        runtime.busy = True
        assert client.post("/api/project/close").status_code == 409
        runtime.busy = False
        assert client.post("/api/chat", json={"message": "  "}).status_code == 422
        assert client.post("/api/chat", json={"message": "x" * 12_001}).status_code == 422


def test_reasoning_mode_model_thinking_and_actions(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        runtime = client.app.state.runtime
        assert client.get("/api/state").json()["reasoning_mode"] == "auto"

        response = client.post("/api/reasoning-mode", json={"mode": "thinking"})
        assert response.json() == {"mode": "thinking"}
        assert runtime.agent.thinking_override is True
        response = client.post("/api/reasoning-mode", json={"mode": "fast"})
        assert response.json() == {"mode": "fast"}
        assert runtime.agent.thinking_override is False
        response = client.post("/api/reasoning-mode", json={"mode": "auto"})
        assert response.json() == {"mode": "auto"}
        assert runtime.agent.thinking_override is None
        assert client.post("/api/reasoning-mode", json={"mode": "invalid"}).status_code == 422
        runtime.busy = True
        assert client.post("/api/reasoning-mode", json={"mode": "fast"}).status_code == 409
        runtime.busy = False
        cors = client.options(
            "/api/state",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert cors.headers["access-control-allow-origin"] == "http://tauri.localhost"

        model = client.get("/api/model").json()
        assert model["model"] == web_api.settings.model
        assert model["context_used"] == 0
        assert model["context_limit"] == web_api.settings.context_limit
        assert model["context_percent"] == 0
        runtime.agent.context_used = web_api.settings.context_limit // 2
        assert client.get("/api/model").json()["context_percent"] == 50

        runtime._agent_event(web_api.AgentEvent("thinking_start"))
        runtime._agent_event(web_api.AgentEvent("thinking_delta", "Consider the request."))
        assert client.get("/api/thinking").json() == {
            "active": True,
            "content": "Consider the request.",
        }
        runtime._agent_event(web_api.AgentEvent("thinking_end"))
        assert client.get("/api/thinking").json()["active"] is False

        runtime._agent_event(web_api.AgentEvent("action_started", "read_file", {"name": "read_file"}))
        runtime._agent_event(web_api.AgentEvent(
            "action_completed", "read_file", {"name": "read_file", "success": True},
        ))
        actions = client.get("/api/actions").json()["actions"]
        assert [action["type"] for action in actions] == ["action_started", "action_completed"]
        assert actions[-1]["success"] is True
        assert client.get(f"/api/actions?after={actions[0]['id']}").json()["actions"] == [actions[1]]
        next_turn = runtime._publish("user_message", text="next turn")
        runtime.turn_started_event_id = int(next_turn["id"])
        runtime._agent_event(web_api.AgentEvent("status", "next turn only"))
        assert [action["text"] for action in client.get("/api/actions").json()["actions"]] == [
            "next turn only",
        ]


def test_permission_endpoint_answers_pending_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        runtime = client.app.state.runtime
        ready = threading.Event()
        interaction_id = "approval-id"
        runtime.interactions[interaction_id] = {
            "ready": ready,
            "kind": "approval",
            "prompt": "allow write_file?",
            "choices": "y/n/a=always allow this session",
        }

        assert client.get("/api/permission").json()["permission"] == {
            "interaction_id": interaction_id,
            "kind": "approval",
            "prompt": "allow write_file?",
            "choices": "y/n/a=always allow this session",
        }
        response = client.post(
            f"/api/permission/{interaction_id}",
            json={"decision": "always"},
        )
        assert response.json() == {"answered": True}
        assert ready.is_set()
        assert runtime.interactions[interaction_id]["answer"] == "a"
        assert client.post(
            f"/api/permission/{interaction_id}",
            json={"decision": "approve"},
        ).status_code == 409


def test_always_allow_requires_an_advertised_choice(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        runtime = client.app.state.runtime
        ready = threading.Event()
        runtime.interactions["approval-id"] = {
            "ready": ready,
            "kind": "approval",
            "prompt": "allow read_file?",
            "choices": "y/n",
        }

        assert client.post(
            "/api/permission/approval-id",
            json={"decision": "always"},
        ).status_code == 422
        assert not ready.is_set()

        runtime.interactions["approval-id"]["choices"] = "y / n / a = always allow this session"
        assert client.post(
            "/api/permission/approval-id",
            json={"decision": "always"},
        ).status_code == 200
        assert runtime.interactions["approval-id"]["answer"] == "a"


def test_continuation_interaction_accepts_only_continue_or_abort(monkeypatch, tmp_path):
    monkeypatch.setattr(web_api, "Agent", FakeAgent)
    monkeypatch.setattr(web_api, "load_approvals", lambda _path: set())
    monkeypatch.setattr(web_api.workspace_tools, "DEFAULT_WORKSPACE", tmp_path)

    with TestClient(web_api.app) as client:
        runtime = client.app.state.runtime
        ready = threading.Event()
        runtime.interactions["continue-id"] = {
            "ready": ready,
            "kind": "continuation",
            "prompt": "Hit the step limit. Continue?",
            "choices": "Continue / Abort",
        }

        assert client.post(
            "/api/interactions/continue-id",
            json={"answer": "y"},
        ).status_code == 422
        assert not ready.is_set()

        response = client.post(
            "/api/interactions/continue-id",
            json={"answer": "continue"},
        )
        assert response.json() == {"answered": True}
        assert ready.is_set()
        assert runtime.interactions["continue-id"]["answer"] == "continue"
