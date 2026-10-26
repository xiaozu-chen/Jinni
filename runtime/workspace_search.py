"""Bounded semantic search over readable text files in one workspace."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from memory.semantic import EmbedError, embed_texts, embedding_prefixes

log = logging.getLogger("jinni.workspace_search")

TEXT_SUFFIXES = {
    ".c", ".cfg", ".cpp", ".css", ".csv", ".go", ".html", ".ini", ".java",
    ".js", ".jsx", ".json", ".md", ".ps1", ".py", ".rs", ".sh", ".sql",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}
SKIP_DIRS = {".git", ".jinni", ".trash", ".venv", "venv", "node_modules", "__pycache__"}
SKIP_NAMES = {".env", ".env.local", "mcp_servers.json", "settings.toml", "secrets.toml"}
SKIP_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
MAX_FILES = 200
MAX_FILE_BYTES = 256_000
MAX_TOTAL_BYTES = 20_000_000
MAX_CHUNKS = 2_000
CHUNK_CHARS = 1_200
CHUNK_OVERLAP = 200


@dataclass(frozen=True)
class Chunk:
    path: str
    start_line: int
    end_line: int
    text: str


def chunk_text(path: str, text: str) -> list[Chunk]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + CHUNK_CHARS // 2:
                end = boundary + 1
        body = text[start:end].strip()
        if body:
            chunks.append(Chunk(
                path=path,
                start_line=text.count("\n", 0, start) + 1,
                end_line=text.count("\n", 0, end) + int(end == 0 or text[end - 1] != "\n"),
                text=body,
            ))
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)
    return chunks


def collect_chunks(root: str | Path) -> list[Chunk]:
    base = Path(root).resolve()
    chunks = []
    total_bytes = 0
    files_seen = 0
    for directory, names, filenames in os.walk(base, followlinks=False):
        folder = Path(directory)
        names[:] = sorted(
            name for name in names
            if name.casefold() not in SKIP_DIRS and not (folder / name).is_symlink()
        )
        for name in sorted(filenames):
            path = folder / name
            lowered = name.casefold()
            if (path.is_symlink() or path.suffix.casefold() not in TEXT_SUFFIXES
                    or path.suffix.casefold() in SKIP_SUFFIXES or lowered in SKIP_NAMES
                    or lowered.startswith((".env", "secret", "credential"))):
                continue
            try:
                size = path.stat().st_size
                if size > MAX_FILE_BYTES or total_bytes + size > MAX_TOTAL_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            total_bytes += size
            files_seen += 1
            relative = path.relative_to(base).as_posix()
            chunks.extend(chunk_text(relative, text))
            if files_seen >= MAX_FILES or len(chunks) >= MAX_CHUNKS:
                return chunks[:MAX_CHUNKS]
    return chunks[:MAX_CHUNKS]


def _keyword_score(query: str, text: str) -> float:
    terms = set(re.findall(r"[\w-]+", query.casefold()))
    words = set(re.findall(r"[\w-]+", text.casefold()))
    return len(terms & words) / len(terms) if terms else 0.0


def search_workspace(root: str | Path, query: str, limit: int = 5) -> tuple[list[tuple[Chunk, float]], str]:
    query = " ".join(query.split())
    if not query:
        return [], "keyword"
    if len(query) > 1_000 or not 1 <= limit <= 10:
        raise ValueError("query must be 1,000 characters or fewer and limit must be 1 to 10")
    chunks = collect_chunks(root)
    if not chunks:
        return [], "keyword"

    try:
        query_prefix, document_prefix = embedding_prefixes()
        query_vector = embed_texts([query_prefix + query])[0]
        vectors = []
        for offset in range(0, len(chunks), 32):
            texts = [document_prefix + chunk.text for chunk in chunks[offset:offset + 32]]
            vectors.extend(embed_texts(texts))
        scores = np.stack(vectors) @ query_vector
        mode = "semantic"
    except EmbedError as error:
        log.info("workspace semantic search unavailable; using keywords: %s", type(error).__name__)
        scores = np.array([_keyword_score(query, chunk.text) for chunk in chunks])
        mode = "keyword"

    ranked = sorted(enumerate(scores), key=lambda pair: (-float(pair[1]), pair[0]))
    return [(chunks[index], float(score)) for index, score in ranked[:limit] if score > 0], mode


def format_results(results: list[tuple[Chunk, float]], mode: str) -> str:
    if not results:
        return f"No workspace matches ({mode} search)."
    lines = [f"Workspace matches ({mode} search):"]
    for chunk, score in results:
        snippet = " ".join(chunk.text.split())[:500]
        lines.append(f"{chunk.path}:{chunk.start_line}-{chunk.end_line} [{score:.2f}] {snippet}")
    return "\n".join(lines)
