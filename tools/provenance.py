"""Attach integrity-checked source records to generated CSV files."""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def sidecar_path(csv_path: Path) -> Path:
    return csv_path.with_suffix(".provenance.json")


def write_csv_provenance(csv_path: Path, data: bytes, source_url: str, table_index: int) -> dict:
    record = {
        "kind": "source",
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table_index": table_index,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    _write_record(csv_path, record)
    return record


def write_typed_csv_provenance(csv_path: Path, data: bytes) -> dict:
    record = {
        "kind": "typed",
        "source_url": "jinni://typed",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    _write_record(csv_path, record)
    return record


def write_search_csv_provenance(csv_path: Path, data: bytes, query: str, sources: list[dict[str, str]]) -> dict:
    record = {
        "kind": "snippet",
        "source_url": "search://snippets",
        "query": query[:200],
        "sources": sources[:5],
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    _write_record(csv_path, record)
    return record


def _write_record(csv_path: Path, record: dict) -> None:
    target = sidecar_path(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_csv_provenance(csv_path: Path) -> dict | None:
    target = sidecar_path(csv_path)
    try:
        record = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return None
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if record.get("sha256") != digest:
            return None
        if not all(isinstance(record.get(key), str) and record[key]
                   for key in ("source_url", "fetched_at")):
            return None
        if record.get("kind", "source") not in ("source", "typed", "snippet"):
            return None
        if record.get("kind") == "snippet":
            sources = record.get("sources")
            if (not isinstance(record.get("query"), str) or len(record["query"]) > 200
                    or not isinstance(sources, list) or len(sources) > 5
                    or any(not isinstance(item, dict)
                           or not isinstance(item.get("title"), str)
                           or not isinstance(item.get("url"), str)
                           for item in sources)):
                return None
        record.setdefault("kind", "source")
        return record
    except (OSError, ValueError, TypeError):
        return None
