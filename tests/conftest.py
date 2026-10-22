import pytest

from tools import workspace as ws


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "WORKSPACE", tmp_path.resolve())
    return tmp_path.resolve()