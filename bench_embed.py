import time

from config import settings
from semantic import embed_texts

PAIRS = [
    ("canine companion", "The user owns a puppy.", "related"),
    ("what did we read", "Read mm.txt about radioisotopes and green chemistry.", "related"),
    ("favourite programming language", "The user is learning Python.", "related"),
    ("canine companion", "Read mm.txt about radioisotopes and green chemistry.", "unrelated"),
    ("favourite programming language", "The user's name is Carl.", "unrelated"),
    ("weather tomorrow", "The user prefers short answers.", "unrelated"),
]

for query, doc, label in PAIRS:
    q = embed_texts([settings.embed_query_prefix + query])[0]
    d = embed_texts([settings.embed_doc_prefix + doc])[0]
    print(f"{float(q @ d):5.2f}  {label:9}  {query!r}  vs  {doc!r}")

texts = [settings.embed_doc_prefix + f"memory number {i}, some text about files" for i in range(32)]
start = time.perf_counter()
embed_texts(texts)
print(f"\n32 texts embedded in {time.perf_counter() - start:.1f}s")