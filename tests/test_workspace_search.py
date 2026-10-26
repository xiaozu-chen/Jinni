import numpy as np
import pytest

import workspace_search
from semantic import EmbedError
from workspace_search import collect_chunks, format_results, search_workspace


def test_chunking_tracks_line_ranges_and_bounds_chunk_size(monkeypatch):
    monkeypatch.setattr(workspace_search, "CHUNK_CHARS", 12)
    monkeypatch.setattr(workspace_search, "CHUNK_OVERLAP", 2)

    chunks = workspace_search.chunk_text("notes.md", "one\ntwo\nthree\nfour\n")

    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    assert all(len(chunk.text) <= 12 for chunk in chunks)


def test_collection_skips_secrets_and_generated_folders(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "readme.md").write_text("public project notes", encoding="utf-8")
    (tmp_path / "src" / ".env.production").write_text("API_TOKEN=secret", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "library.py").write_text("generated package", encoding="utf-8")

    chunks = collect_chunks(tmp_path)

    assert [chunk.path for chunk in chunks] == ["src/readme.md"]


def test_semantic_search_ranks_relevant_chunks_and_formats_source(tmp_path, monkeypatch):
    (tmp_path / "one.md").write_text("database schema and query planning", encoding="utf-8")
    (tmp_path / "two.md").write_text("garden flowers and soil", encoding="utf-8")

    def fake_embed_texts(texts):
        if texts[0].startswith("search_query:"):
            return np.array([[1.0, 0.0]], dtype=np.float32)
        return np.array([[1.0, 0.0] if "database" in item else [0.0, 1.0] for item in texts], dtype=np.float32)

    monkeypatch.setattr(workspace_search, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(workspace_search, "embedding_prefixes", lambda: ("search_query: ", "search_document: "))

    results, mode = search_workspace(tmp_path, "database query")

    assert mode == "semantic"
    assert results[0][0].path == "one.md"
    assert "one.md:1-1" in format_results(results, mode)


def test_workspace_search_falls_back_to_keywords(tmp_path, monkeypatch):
    (tmp_path / "notes.txt").write_text("sales grew every month", encoding="utf-8")
    monkeypatch.setattr(workspace_search, "embed_texts", lambda _texts: (_ for _ in ()).throw(EmbedError("offline")))

    results, mode = search_workspace(tmp_path, "sales growth")

    assert mode == "keyword"
    assert len(results) == 1
    assert results[0][0].path == "notes.txt"


def test_workspace_search_validates_bounds(tmp_path):
    with pytest.raises(ValueError, match="limit must be 1 to 10"):
        search_workspace(tmp_path, "query", 11)
