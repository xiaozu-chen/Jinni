from memory import Proposal
from review import review

FACT = Proposal("fact", "The user's name is Carl.")
NOTE = Proposal("event", "Read mm.txt.")


def run_review(store, monkeypatch, answers, proposals):
    replies = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(replies))
    return review(store, proposals)


def test_yes_saves(memory_store, monkeypatch):
    assert run_review(memory_store, monkeypatch, ["y", "y"], [FACT, NOTE]) == 2
    assert memory_store.counts() == (1, 1)


def test_no_and_junk_skip(memory_store, monkeypatch):
    assert run_review(memory_store, monkeypatch, ["n", "banana"], [FACT, NOTE]) == 0
    assert memory_store.counts() == (0, 0)


def test_edit_then_save(memory_store, monkeypatch):
    saved = run_review(memory_store, monkeypatch, ["e", "The user's name is Carlo.", "y"], [FACT])
    assert saved == 1
    assert memory_store.facts()[0].text == "The user's name is Carlo."


def test_quit_stops(memory_store, monkeypatch):
    assert run_review(memory_store, monkeypatch, ["q"], [FACT, NOTE]) == 0
    assert memory_store.counts() == (0, 0)


def test_rejected_item_does_not_crash(memory_store, monkeypatch):
    memory_store.add("fact", FACT.text)
    assert run_review(memory_store, monkeypatch, ["y"], [FACT]) == 0