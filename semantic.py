"""Embed and search memories, falling back to keyword ranking when the local service is down."""

from __future__ import annotations

import logging
import hashlib
import threading
import time
from typing import TYPE_CHECKING

import httpx

from config import settings
from memory import Memory, MemoryStore

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger("jinni.semantic")

BATCH = 32
MAX_BATCHES = 20
RRF_K = 60
EMBED_CIRCUIT_SECONDS = 60
_circuit_lock = threading.Lock()
_circuit_until = 0.0
_warmup_lock = threading.Lock()
_warmup_started = False
_catch_up_lock = threading.Lock()


class EmbedError(Exception):
    """The embedding server was unreachable, or answered with something unusable."""


def _np():
    try:
        import numpy
    except ImportError as e:
        raise EmbedError("numpy is not installed (pip install numpy)") from e
    return numpy


def embedding_prefixes(model: str | None = None) -> tuple[str, str]:
    model = model or settings.embed_model
    for name, query_prefix, document_prefix in settings.embed_prefixes:
        if name == model:
            return query_prefix, document_prefix
    return settings.embed_query_prefix, settings.embed_doc_prefix


def embedding_cache_key() -> str:
    query_prefix, document_prefix = embedding_prefixes()
    prefix_hash = hashlib.sha256(f"{query_prefix}\0{document_prefix}".encode("utf-8")).hexdigest()[:12]
    return f"{settings.embed_model}:{prefix_hash}"


def circuit_open() -> bool:
    with _circuit_lock:
        return time.monotonic() < _circuit_until


def reset_circuit() -> None:
    global _circuit_until
    with _circuit_lock:
        _circuit_until = 0.0


def _trip_circuit() -> None:
    global _circuit_until
    with _circuit_lock:
        _circuit_until = time.monotonic() + EMBED_CIRCUIT_SECONDS


def embed_texts(texts: list[str]) -> np.ndarray:
    """One L2-normalized float32 vector per text, so cosine similarity is just a dot product."""
    if circuit_open():
        raise EmbedError("embedding service paused after a recent failure; retry after one minute")
    try:
        np = _np()
        response = httpx.post(
            f"{settings.embed_url}/embeddings",
            json={"model": settings.embed_model, "input": texts},
            timeout=settings.embed_timeout,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda d: d.get("index", 0))
        matrix = np.array([d["embedding"] for d in data], dtype=np.float32)
    except EmbedError as error:
        _trip_circuit()
        raise error
    except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError) as e:
        error = EmbedError(f"{type(e).__name__}: {e}")
        _trip_circuit()
        raise error from e

    if matrix.ndim != 2 or matrix.shape[0] != len(texts) or not np.isfinite(matrix).all():
        _trip_circuit()
        raise EmbedError("the server returned vectors in an unexpected shape")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms == 0).any():
        _trip_circuit()
        raise EmbedError("the server returned an empty (all-zero) vector")
    return matrix / norms


def catch_up(store: MemoryStore) -> int:
    """Embed every memory that has no vector yet. Returns how many were embedded."""
    with _catch_up_lock:
        return _catch_up(store)


def _catch_up(store: MemoryStore) -> int:
    done = 0
    cache_key = embedding_cache_key()
    for _ in range(MAX_BATCHES):
        batch = store.pending(cache_key, BATCH)
        if not batch:
            break
        _query_prefix, document_prefix = embedding_prefixes()
        vectors = embed_texts([document_prefix + m.text for m in batch])
        for memory, vector in zip(batch, vectors):
            store.save_vector(memory.id, cache_key, vector.shape[0], vector.tobytes())
        done += len(batch)
    return done


def semantic_search(store: MemoryStore, query: str, limit: int) -> list[tuple[int, float]]:
    """(memory id, cosine similarity) for the best matches above the similarity floor."""
    rows = store.load_vectors(embedding_cache_key())
    if not rows:
        return []
    np = _np()
    query_prefix, _document_prefix = embedding_prefixes()
    q = embed_texts([query_prefix + query])[0]
    dim = q.shape[0]
    usable = [
        (i, np.frombuffer(blob, dtype=np.float32))
        for i, d, blob in rows
        if d == dim and len(blob) == dim * 4
    ]
    if not usable:
        return []
    ids = [i for i, _ in usable]
    scores = np.stack([v for _, v in usable]) @ q
    order = np.argsort(-scores)[:limit]
    return [(ids[j], float(scores[j])) for j in order if scores[j] >= settings.min_similarity]


def similar_facts_by_embedding(store: MemoryStore, query: str, limit: int = 3) -> list[Memory]:
    if not settings.embed_enabled or not query.strip() or limit <= 0:
        return []
    catch_up(store)
    matches = semantic_search(store, query, max(20, limit * 4))
    found = []
    for memory_id, score in matches:
        item = store.get(memory_id)
        if item and item.kind == "fact" and score >= settings.near_duplicate_similarity:
            found.append(item)
            if len(found) == limit:
                break
    return found


def fuse(rankings: list[list[int]], limit: int) -> list[int]:
    """Reciprocal rank fusion: items that rank well in several lists float to the top."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, memory_id in enumerate(ranking, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda i: (-scores[i], i))[:limit]


def rerank(ids: list[int], keyword_ids: list[int], semantic_scores: dict[int, float], limit: int) -> list[int]:
    keyword_ranks = {memory_id: rank for rank, memory_id in enumerate(keyword_ids)}
    original_ranks = {memory_id: rank for rank, memory_id in enumerate(ids)}

    def score(memory_id: int) -> float:
        semantic_score = semantic_scores.get(memory_id, 0.0)
        keyword_rank = keyword_ranks.get(memory_id)
        keyword_score = 1.0 / (keyword_rank + 1) if keyword_rank is not None else 0.0
        return semantic_score * 0.7 + keyword_score * 0.3

    return sorted(ids, key=lambda memory_id: (-score(memory_id), original_ranks[memory_id]))[:limit]


def hybrid_search(store: MemoryStore, query: str, limit: int | None = None) -> tuple[list[Memory], str]:
    """Fuse lexical and vector rankings; return keyword mode if the optional embedder is down."""
    limit = limit or settings.recall_results
    if not query.strip():
        return [], "keyword"

    # Search SQLite first so recall still works when the optional local model is sulking.
    by_keyword = store.search(query, limit * 2)
    by_meaning: list[tuple[int, float]] = []
    mode = "keyword"
    if settings.embed_enabled:
        try:
            catch_up(store)
            by_meaning = semantic_search(store, query, limit * 2)
            mode = "hybrid"
        except EmbedError as e:
            if not circuit_open():
                log.warning("semantic search unavailable, using keywords only: %s", e)

    if mode == "keyword":
        results = by_keyword[:limit]
    else:
        known = {m.id: m for m in by_keyword}
        for memory_id, _ in by_meaning:
            if memory_id not in known:
                found = store.get(memory_id)
                if found:
                    known[memory_id] = found
        keyword_ids = [m.id for m in by_keyword]
        semantic_scores = dict(by_meaning)
        # Fuse ranks before reranking: candidates must have evidence from either search path.
        ids = fuse([keyword_ids, list(semantic_scores)], limit * 4)
        ids = rerank(ids, keyword_ids, semantic_scores, limit)
        results = [known[i] for i in ids if i in known]

    log.info("recall %r: %d result(s), mode=%s", query[:60], len(results), mode)
    return results, mode


def _warmup(store: MemoryStore) -> None:
    try:
        count = catch_up(store)
        log.info("semantic startup warm-up embedded %d memories", count)
    except EmbedError as error:
        log.info("semantic startup warm-up skipped: %s", error)


def start_warmup(store: MemoryStore) -> bool:
    global _warmup_started
    if not settings.embed_enabled:
        return False
    with _warmup_lock:
        if _warmup_started:
            return False
        _warmup_started = True
    threading.Thread(target=_warmup, args=(store,), name="jinni-embedding-warmup", daemon=True).start()
    return True
