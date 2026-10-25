"""Compare a few related and unrelated pairs against the local embedding service."""

import time

from config import settings
from semantic import EmbedError, embed_texts

PAIRS = [
    ("canine companion", "The user owns a puppy.", "related"),
    ("what did we read", "Read mm.txt about radioisotopes and green chemistry.", "related"),
    ("favourite programming language", "The user is learning Python.", "related"),
    ("canine companion", "Read mm.txt about radioisotopes and green chemistry.", "unrelated"),
    ("favourite programming language", "The user's name is Carl.", "unrelated"),
    ("weather tomorrow", "The user prefers short answers.", "unrelated"),
]


def threshold_summary(related: list[float], unrelated: list[float]) -> str:
    if not related or not unrelated:
        return "Not enough labeled scores to suggest a threshold."
    lowest_related = min(related)
    highest_unrelated = max(unrelated)
    if highest_unrelated >= lowest_related:
        return (
            f"Score ranges overlap (related min {lowest_related:.3f}, "
            f"unrelated max {highest_unrelated:.3f}); keep {settings.min_similarity:.3f} "
            "or collect more examples."
        )
    suggested = (highest_unrelated + lowest_related) / 2
    return (
        f"Suggested floor: {suggested:.3f} (unrelated max {highest_unrelated:.3f}, "
        f"related min {lowest_related:.3f}; current {settings.min_similarity:.3f})."
    )


def main() -> None:
    related_scores = []
    unrelated_scores = []
    try:
        for query, document, label in PAIRS:
            query_vector = embed_texts([settings.embed_query_prefix + query])[0]
            document_vector = embed_texts([settings.embed_doc_prefix + document])[0]
            score = float(query_vector @ document_vector)
            (related_scores if label == "related" else unrelated_scores).append(score)
            print(f"{score:6.3f}  {label:9}  {query!r}  vs  {document!r}")

        texts = [settings.embed_doc_prefix + f"memory number {i}, some text about files" for i in range(32)]
        start = time.perf_counter()
        embed_texts(texts)
        print(f"\n32 texts embedded in {time.perf_counter() - start:.1f}s")
        print(threshold_summary(related_scores, unrelated_scores))
    except EmbedError as error:
        print(f"Embedding benchmark could not reach {settings.embed_url}: {error}")
        print("Start the configured embedding service, then run bench_embed.py again.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
