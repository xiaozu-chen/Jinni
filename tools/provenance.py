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
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "table_index": table_index,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
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
    return record


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
        return record
    except (OSError, ValueError, TypeError):
        return None
