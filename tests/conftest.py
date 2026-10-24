import pytest

import memory
from memory import MemoryStore
from tools import workspace as ws


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