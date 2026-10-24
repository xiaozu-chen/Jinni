from __future__ import annotations

import logging
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


class EmbedError(Exception):
    """The embedding server was unreachable, or answered with something unusable."""


def _np():
    try:
        import numpy
    except ImportError as e:
        raise EmbedError("numpy is not installed (pip install numpy)") from e
    return numpy


def embed_texts(texts: list[str]) -> np.ndarray:
    """One L2-normalized float32 vector per text, so cosine similarity is just a dot product."""
    np = _np()
    try:
        response = httpx.post(
            f"{settings.embed_url}/embeddings",
            json={"model": settings.embed_model, "input": texts},
            timeout=settings.embed_timeout,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda d: d.get("index", 0))
        matrix = np.array([d["embedding"] for d in data], dtype=np.float32)
    except (httpx.HTTPError, KeyError, ValueError, TypeError, AttributeError) as e:
        raise EmbedError(f"{type(e).__name__}: {e}") from e

    if matrix.ndim != 2 or matrix.shape[0] != len(texts) or not np.isfinite(matrix).all():
        raise EmbedError("the server returned vectors in an unexpected shape")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norms == 0).any():
        raise EmbedError("the server returned an empty (all-zero) vector")
    return matrix / norms


def catch_up(store: MemoryStore) -> int:
    """Embed every memory that has no vector yet. Returns how many were embedded."""
    done = 0
    for _ in range(MAX_BATCHES):
        batch = store.pending(settings.embed_model, BATCH)
        if not batch:
            break
        vectors = embed_texts([settings.embed_doc_prefix + m.text for m in batch])
        for memory, vector in zip(batch, vectors):
            store.save_vector(memory.id, settings.embed_model, vector.shape[0], vector.tobytes())
        done += len(batch)
    return done


def semantic_search(store: MemoryStore, query: str, limit: int) -> list[tuple[int, float]]:
    """(memory id, cosine similarity) for the best matches above the similarity floor."""
    rows = store.load_vectors(settings.embed_model)
    if not rows:
        return []
    np = _np()
    q = embed_texts([settings.embed_query_prefix + query])[0]
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


def fuse(rankings: list[list[int]], limit: int) -> list[int]:
    """Reciprocal rank fusion: items that rank well in several lists float to the top."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, memory_id in enumerate(ranking, start=1):
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda i: (-scores[i], i))[:limit]


def hybrid_search(store: MemoryStore, query: str, limit: int | None = None) -> tuple[list[Memory], str]:
    """Returns (results, mode). Mode is 'hybrid', or 'keyword' when semantic search is off or down."""
    limit = limit or settings.recall_results
    if not query.strip():
        return [], "keyword"

    by_keyword = store.search(query, limit * 2)
    by_meaning: list[tuple[int, float]] = []
    mode = "keyword"
    if settings.embed_enabled:
        try:
            catch_up(store)
            by_meaning = semantic_search(store, query, limit * 2)
            mode = "hybrid"
        except EmbedError as e:
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
        ids = fuse([[m.id for m in by_keyword], [i for i, _ in by_meaning]], limit)
        results = [known[i] for i in ids if i in known]

    log.info("recall %r: %d result(s), mode=%s", query[:60], len(results), mode)
    return results, mode