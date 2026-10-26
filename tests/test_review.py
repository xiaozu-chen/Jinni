from datetime import date, timedelta

from memory.memory import Proposal
from runtime.review import review, review_stale_facts
import runtime.review as review_module

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


def test_possible_fact_conflict_is_shown_before_saving_both(memory_store, monkeypatch, capsys):
    memory_store.add("fact", "Likes tea.")

    assert run_review(memory_store, monkeypatch, ["y"], [
        Proposal("fact", "Likes coffee.")
    ]) == 1

    assert "may overlap with saved fact" in capsys.readouterr().out
    assert [item.text for item in memory_store.facts()] == ["Likes tea.", "Likes coffee."]


def test_embedding_duplicate_warning_is_shown(memory_store, monkeypatch, capsys):
    saved = memory_store.add("fact", "Canine companions are fun.")
    monkeypatch.setattr(review_module, "similar_facts_by_embedding", lambda store, text: [saved])

    assert run_review(memory_store, monkeypatch, ["n"], [Proposal("fact", "Enjoys a puppy.")]) == 0

    output = capsys.readouterr().out
    assert "may overlap with saved fact" in output
    assert "Canine companions are fun." in output


def test_quit_stops(memory_store, monkeypatch):
    assert run_review(memory_store, monkeypatch, ["q"], [FACT, NOTE]) == 0
    assert memory_store.counts() == (0, 0)


def test_rejected_item_does_not_crash(memory_store, monkeypatch):
    memory_store.add("fact", FACT.text)
    assert run_review(memory_store, monkeypatch, ["y"], [FACT]) == 0


def test_exit_review_offers_old_facts_forgetting(memory_store, monkeypatch):
    saved = memory_store.add("fact", "Old preference.")
    with memory_store.conn:
        memory_store.conn.execute(
            "UPDATE memories SET created = ? WHERE id = ?",
            ((date.today() - timedelta(days=400)).isoformat(), saved.id),
        )
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "d")

    assert review_stale_facts(memory_store) == 1
    assert memory_store.get(saved.id) is None
    assert "Old preference." in prompts[0]


def test_exit_review_keeps_stale_facts_when_user_says_keep(memory_store, monkeypatch):
    saved = memory_store.add("fact", "Old preference.")
    with memory_store.conn:
        memory_store.conn.execute(
            "UPDATE memories SET created = ? WHERE id = ?",
            ((date.today() - timedelta(days=400)).isoformat(), saved.id),
        )
    monkeypatch.setattr("builtins.input", lambda _: "k")

    assert review_stale_facts(memory_store) == 0
    assert memory_store.get(saved.id) is not None
    assert review_stale_facts(memory_store, days=1) == 0
