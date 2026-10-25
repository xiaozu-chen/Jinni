import json
from types import SimpleNamespace

from transcripts import load_transcript, save_transcript


def test_save_and_load_transcript_round_trip(workspace):
    agent = SimpleNamespace(
        summary="Worked on charts.",
        messages=[
            {"role": "system", "content": "Do not export the system prompt."},
            {"role": "user", "content": "Make a chart."},
            {"role": "assistant", "content": "I made it."},
        ],
    )

    assert "Saved transcript" in save_transcript(agent, "charts")
    payload = json.loads((workspace / "transcripts" / "charts.json").read_text(encoding="utf-8"))
    assert "Make a chart." in payload["transcript"]
    assert "Worked on charts." in payload["transcript"]
    assert "system prompt" not in payload["transcript"]

    restored = SimpleNamespace(messages=[{"role": "system", "content": "system"}])
    assert "Loaded transcript" in load_transcript(restored, "charts")
    assert restored.messages[-1]["role"] == "user"
    assert "Saved conversation context" in restored.messages[-1]["content"]


def test_save_requires_confirmation_to_overwrite(workspace):
    agent = SimpleNamespace(summary="", messages=[
        {"role": "system", "content": "system"},
        {"role": "user", "content": "first"},
    ])

    assert "Saved transcript" in save_transcript(agent, "session")
    agent.messages[-1]["content"] = "second"
    assert "Confirm overwrite" in save_transcript(agent, "session")
    assert "Saved transcript" in save_transcript(agent, "session", overwrite=True)
    assert "second" in (workspace / "transcripts" / "session.json").read_text(encoding="utf-8")


def test_transcript_paths_and_oversized_loads_are_rejected(workspace):
    agent = SimpleNamespace(summary="", messages=[{"role": "system"}, {"role": "user", "content": "hi"}])

    assert save_transcript(agent, "../outside").startswith("Error:")
    (workspace / "transcripts").mkdir()
    (workspace / "transcripts" / "huge.json").write_text("x" * 1_000_001, encoding="utf-8")
    assert "too large" in load_transcript(agent, "huge")
