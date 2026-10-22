from config import settings
from context import compact, to_transcript

LONG = "x" * 500


def tool_msg(text):
    return {"role": "tool", "tool_call_id": "1", "content": text}


def test_compact_trims_old_keeps_recent():
    msgs = [tool_msg(LONG) for _ in range(5)]
    trimmed = compact(msgs)

    assert trimmed == 5 - settings.keep_recent
    assert "trimmed" in msgs[0]["content"]
    assert msgs[-1]["content"] == LONG


def test_compact_leaves_short_results_alone():
    msgs = [tool_msg("short") for _ in range(6)]
    assert compact(msgs) == 0
    assert msgs[0]["content"] == "short"


def test_compact_twice_does_nothing_new():
    msgs = [tool_msg(LONG) for _ in range(6)]
    compact(msgs)
    assert compact(msgs) == 0


def test_compact_never_touches_other_roles():
    msgs = [
        {"role": "user", "content": LONG},
        {"role": "assistant", "content": LONG},
    ] + [tool_msg(LONG) for _ in range(6)]
    compact(msgs)
    assert msgs[0]["content"] == LONG
    assert msgs[1]["content"] == LONG


def test_transcript_covers_all_roles():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function",
             "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}
        ]},
        {"role": "tool", "tool_call_id": "1", "content": "y" * 1000},
        {"role": "assistant", "content": "done"},
    ]
    text = to_transcript(msgs)

    assert "User: hi" in text
    assert "Jinni used read_file" in text
    assert "Jinni: done" in text
    assert "y" * 301 not in text