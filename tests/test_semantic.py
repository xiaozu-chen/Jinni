import re
import sys
import threading
from dataclasses import replace

import httpx
import numpy as np
import pytest

import semantic
from config import settings
from semantic import EmbedError, catch_up, fuse, hybrid_search, semantic_search
from tools.memory_tools import recall

CONCEPTS = {"dog": 0, "canine": 0, "puppy": 0, "cat": 1, "feline": 1, "python": 2, "code": 2}


@pytest.fixture(autouse=True)
def reset_embed_breaker():
    semantic.reset_circuit()
    yield
    semantic.reset_circuit()


def fake_vectors(texts):
    out = np.zeros((len(texts), 3), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in re.findall(r"\w+", text.lower()):
            if word in CONCEPTS:
                out[row, CONCEPTS[word]] += 1
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return out / norms


@pytest.fixture
def fake_server(monkeypatch):
    calls = []

    def fake(texts):
        calls.append(list(texts))
        return fake_vectors(texts)

    monkeypatch.setattr(semantic, "embed_texts", fake)
    monkeypatch.setattr(semantic, "settings", replace(settings, embed_enabled=True, min_similarity=0.5))
    return calls


def serve(monkeypatch, payload):
    def post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(semantic.httpx, "post", post)


def test_embed_texts_orders_and_normalizes(monkeypatch):
    serve(monkeypatch, {"data": [
        {"index": 1, "embedding": [0.0, 2.0]},
        {"index": 0, "embedding": [3.0, 4.0]},
    ]})
    result = semantic.embed_texts(["first", "second"])
    assert np.allclose(result[0], [0.6, 0.8])
    assert np.allclose(result[1], [0.0, 1.0])


def test_embed_texts_wraps_connection_errors(monkeypatch):
    def refuse(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(semantic.httpx, "post", refuse)
    with pytest.raises(EmbedError):
        semantic.embed_texts(["hello"])


def test_embed_texts_rejects_wrong_count(monkeypatch):
    serve(monkeypatch, {"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    with pytest.raises(EmbedError):
        semantic.embed_texts(["one", "two"])


def test_embed_texts_rejects_zero_vectors(monkeypatch):
    serve(monkeypatch, {"data": [{"index": 0, "embedding": [0.0, 0.0]}]})
    with pytest.raises(EmbedError):
        semantic.embed_texts(["one"])


def test_missing_numpy_is_an_embed_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", None)
    with pytest.raises(EmbedError):
        semantic.embed_texts(["hello"])


def test_catch_up_embeds_each_memory_once(memory_store, fake_server):
    memory_store.add("fact", "The user owns a puppy.")
    memory_store.add("event", "Read mm.txt.")

    assert catch_up(memory_store) == 2
    assert catch_up(memory_store) == 0
    assert len(fake_server) == 1
    assert fake_server[0][0].startswith("search_document: ")


def test_prefixes_can_be_selected_per_model(monkeypatch):
    monkeypatch.setattr(semantic, "settings", replace(
        settings,
        embed_model="custom-model",
        embed_query_prefix="fallback query: ",
        embed_doc_prefix="fallback doc: ",
        embed_prefixes=(("custom-model", "query: ", "document: "),),
    ))

    assert semantic.embedding_prefixes() == ("query: ", "document: ")
    assert semantic.embedding_prefixes("other-model") == ("fallback query: ", "fallback doc: ")


def test_embedding_circuit_breaker_skips_retries_for_one_minute(monkeypatch):
    now = [100.0]
    calls = []

    def refuse(url, **kwargs):
        calls.append(url)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(semantic.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(semantic.httpx, "post", refuse)
    with pytest.raises(EmbedError, match="ConnectError"):
        semantic.embed_texts(["first"])
    assert semantic.circuit_open()
    with pytest.raises(EmbedError, match="paused"):
        semantic.embed_texts(["second"])
    assert len(calls) == 1

    now[0] += semantic.EMBED_CIRCUIT_SECONDS + 1
    assert not semantic.circuit_open()
    serve(monkeypatch, {"data": [{"index": 0, "embedding": [1.0, 0.0]}]})
    assert semantic.embed_texts(["third"]).shape == (1, 2)


def test_startup_warmup_runs_in_background(monkeypatch, memory_store):
    finished = threading.Event()
    monkeypatch.setattr(semantic, "settings", replace(settings, embed_enabled=True))
    monkeypatch.setattr(semantic, "_warmup_started", False)
    monkeypatch.setattr(semantic, "catch_up", lambda store: finished.set() or 1)

    assert semantic.start_warmup(memory_store)
    assert not semantic.start_warmup(memory_store)
    assert finished.wait(1)


def test_catch_up_redoes_work_when_the_model_changes(memory_store, fake_server, monkeypatch):
    memory_store.add("fact", "The user owns a puppy.")
    catch_up(memory_store)
    monkeypatch.setattr(semantic, "settings", replace(semantic.settings, embed_model="another-model"))
    assert catch_up(memory_store) == 1


def test_prefix_changes_invalidate_stored_embeddings(memory_store, fake_server, monkeypatch):
    memory_store.add("fact", "The user owns a puppy.")
    catch_up(memory_store)
    monkeypatch.setattr(semantic, "settings", replace(
        semantic.settings,
        embed_prefixes=(("nomic-embed-text-v1.5", "query: ", "document: "),),
    ))

    assert catch_up(memory_store) == 1
    assert fake_server[-1][0].startswith("document: ")


def test_semantic_search_finds_meaning_without_shared_words(memory_store, fake_server):
    puppy = memory_store.add("fact", "The user owns a puppy.")
    memory_store.add("fact", "The user has a feline.")
    catch_up(memory_store)

    found = semantic_search(memory_store, "canine", 5)

    assert [i for i, _ in found] == [puppy.id]


def test_semantic_search_ignores_unrelated_text(memory_store, fake_server):
    memory_store.add("fact", "The user owns a puppy.")
    catch_up(memory_store)
    assert semantic_search(memory_store, "weather tomorrow", 5) == []


def test_fuse_rewards_agreement():
    assert fuse([[1, 2, 3], [3, 9]], 3) == [3, 1, 2]


def test_hybrid_combines_keyword_and_meaning(memory_store, fake_server):
    by_meaning = memory_store.add("fact", "The user owns a puppy.")
    by_keyword = memory_store.add("event", "Read canine.txt about vets.")
    memory_store.add("fact", "The user likes code.")

    found, mode = hybrid_search(memory_store, "canine")

    assert mode == "hybrid"
    assert {m.id for m in found} == {by_meaning.id, by_keyword.id}


def test_hybrid_falls_back_when_the_server_is_down(memory_store, monkeypatch):
    monkeypatch.setattr(semantic, "settings", replace(settings, embed_enabled=True))

    def down(texts):
        raise EmbedError("refused")

    monkeypatch.setattr(semantic, "embed_texts", down)
    memory_store.add("fact", "The user likes cats.")

    found, mode = hybrid_search(memory_store, "cats")

    assert mode == "keyword"
    assert [m.text for m in found] == ["The user likes cats."]


def test_hybrid_off_never_calls_the_server(memory_store, monkeypatch):
    def explode(texts):
        raise AssertionError("the server should not be called")

    monkeypatch.setattr(semantic, "embed_texts", explode)
    memory_store.add("fact", "The user likes cats.")

    found, mode = hybrid_search(memory_store, "cats")

    assert mode == "keyword"
    assert len(found) == 1


def test_vectors_follow_their_memory(memory_store, fake_server):
    first = memory_store.add("fact", "The user owns a puppy.")
    memory_store.add("fact", "The user has a feline.")
    catch_up(memory_store)
    cache_key = semantic.embedding_cache_key()
    assert len(memory_store.load_vectors(cache_key)) == 2

    memory_store.delete(first.id)
    assert len(memory_store.load_vectors(cache_key)) == 1

    memory_store.clear()
    assert memory_store.load_vectors(cache_key) == []


def test_vector_for_a_deleted_memory_is_dropped(memory_store):
    memory_store.save_vector(999, "m", 2, np.zeros(2, dtype=np.float32).tobytes())
    assert memory_store.load_vectors("m") == []


def test_blank_query_returns_nothing(memory_store, fake_server):
    memory_store.add("fact", "The user owns a puppy.")
    assert hybrid_search(memory_store, "   ") == ([], "keyword")
    assert fake_server == []


def test_recall_tool_uses_meaning(memory_store, fake_server):
    memory_store.add("fact", "The user owns a puppy.")
    assert "puppy" in recall("canine")
