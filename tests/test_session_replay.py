import asyncio
import json

import pytest

import memory.session_replay as session_replay
from memory.session_replay import SessionRecorder, load_replay, render_replay, replay_path, replay_session


def test_recorder_round_trips_model_requests(tmp_path):
    path = tmp_path / "replay.jsonl"
    recorder = SessionRecorder(path)
    recorder.record(
        [{"role": "user", "content": "find a file"}],
        [{"type": "function", "function": {"name": "find_files"}}],
        ["find_files"],
    )
    recorder.close()

    rows = load_replay(path)

    assert len(rows) == 1
    assert rows[0]["expected_tools"] == ["find_files"]


def test_replay_compares_choices_without_executing_tools(tmp_path, monkeypatch):
    path = tmp_path / "replay.jsonl"
    recorder = SessionRecorder(path)
    recorder.record(
        [{"role": "user", "content": "find a file"}],
        [{"type": "function", "function": {"name": "find_files"}}],
        ["find_files"],
    )
    recorder.close()
    requests = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"tool_calls": [
                {"function": {"name": "find_files"}},
            ]}}]}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, _path, json):
            requests.append(json)
            return Response()

    monkeypatch.setattr(session_replay.httpx, "AsyncClient", Client)
    results = asyncio.run(replay_session(path, model="test-model", system_prompt="new prompt"))

    assert results[0].correct
    assert requests[0]["model"] == "test-model"
    assert requests[0]["messages"][0]["content"] == "new prompt"
    assert render_replay(results) == "Replay tool choice: 1/1 matched\n  match: expected find_files; selected find_files"


def test_replay_rejects_malformed_cases(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid session case"):
        load_replay(path)


def test_replay_path_rejects_unsafe_names_and_symlinked_folder(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert replay_path(workspace, "daily-run").parent == workspace / ".jinni" / "replays"
    with pytest.raises(ValueError, match="replay name"):
        replay_path(workspace, "../outside")

    outside = tmp_path / "outside"
    outside.mkdir()
    control = workspace / ".jinni"
    control.mkdir()
    try:
        (control / "replays").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ValueError, match="inside the workspace"):
        replay_path(workspace, "daily-run")
