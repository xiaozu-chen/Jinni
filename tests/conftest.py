import pytest

from dataclasses import dataclass, replace

import memory
import semantic
import task_store as tasks_db
from tools.web import reset_trusted_urls
from memory import MemoryStore
from tools import workspace as ws
from config import settings
from tools import registry


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "TOOL_FUNCTIONS", {})
    monkeypatch.setattr(registry, "TOOL_SCHEMAS", [])
    monkeypatch.setattr(registry, "TOOL_GROUPS", {})
    monkeypatch.setattr(registry, "SUBAGENT_SAFE", set())
    monkeypatch.setattr(registry, "NEEDS_APPROVAL", set())
    monkeypatch.setattr(registry, "REMEMBERABLE", set())
    monkeypatch.setattr(registry, "SCOPES", {})


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    store = MemoryStore(":memory:")
    monkeypatch.setattr(memory, "get_store", lambda: store)
    return store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "WORKSPACE", tmp_path.resolve())
    monkeypatch.setattr(ws, "PROJECT_ACTIVE", False)
    monkeypatch.setattr(ws, "MODEL_WRITTEN", set())
    return tmp_path.resolve()


@pytest.fixture(autouse=True)
def task_store(monkeypatch):
    store = tasks_db.TaskStore(":memory:")
    monkeypatch.setattr(tasks_db, "get_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def trusted_web_urls():
    reset_trusted_urls()
    yield
    reset_trusted_urls()


@pytest.fixture(autouse=True)
def no_embedding_server(monkeypatch):
    monkeypatch.setattr(semantic, "settings", replace(settings, embed_enabled=False))
