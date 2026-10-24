import pytest

from dataclasses import dataclass, replace

import memory
import semantic
from memory import MemoryStore
from tools import workspace as ws
from config import settings


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    store = MemoryStore(":memory:")
    monkeypatch.setattr(memory, "get_store", lambda: store)
    return store


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "WORKSPACE", tmp_path.resolve())
    monkeypatch.setattr(ws, "MODEL_WRITTEN", set())
    return tmp_path.resolve()


@pytest.fixture(autouse=True)
def no_embedding_server(monkeypatch):
    monkeypatch.setattr(semantic, "settings", replace(settings, embed_enabled=False))