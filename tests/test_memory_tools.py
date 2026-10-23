from tools import NEEDS_APPROVAL, REMEMBERABLE
from tools.memory_tools import forget, recall, remember


def test_remember_saves_a_fact(memory_store):
    assert "Saved" in remember("The user's name is Carl.")
    assert memory_store.facts()[0].text == "The user's name is Carl."


def test_remember_reports_rejection(memory_store):
    assert remember("x" * 500).startswith("Error")
    assert memory_store.counts() == (0, 0)


def test_recall_finds_and_labels_untrusted(memory_store):
    memory_store.add("event", "Read mm.txt about radioisotopes.")
    out = recall("radioisotope")
    assert "mm.txt" in out
    assert "not instructions" in out


def test_recall_nothing(memory_store):
    assert recall("anything") == "Nothing found in memory."


def test_forget(memory_store):
    saved = memory_store.add("fact", "Likes cats.")
    assert "Forgot" in forget(saved.id)
    assert forget(saved.id).startswith("Error")
    assert memory_store.counts() == (0, 0)


def test_memory_tools_approval_rules():
    assert {"remember", "forget"} <= NEEDS_APPROVAL
    assert "recall" not in NEEDS_APPROVAL
    assert not ({"remember", "forget", "recall"} & REMEMBERABLE)