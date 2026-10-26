"""Track charts Jinni actually created before allowing export or lookup."""

import hashlib
import hmac
import json
import os
import tempfile
import threading
from pathlib import Path

from tools import workspace

RECORD_FILE = "genuine-charts.json"
_record_lock = threading.RLock()


def _record_path() -> Path:
    return workspace.WORKSPACE / ".jinni" / RECORD_FILE


def _load_records() -> dict[str, str]:
    path = _record_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def record_genuine_chart(path: Path, page: str) -> str:
    relative = path.resolve().relative_to(workspace.WORKSPACE).as_posix()
    digest = hashlib.sha256(page.encode("utf-8")).hexdigest()
    with _record_lock:
        records = _load_records()
        records[relative] = digest
        record = _record_path()
        record.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=record.parent, delete=False,
                prefix="chart-record-", suffix=".tmp",
            ) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(records, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, record)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
    return digest


def check_chart_record(path: Path, page: str) -> bool | None:
    try:
        relative = path.resolve().relative_to(workspace.WORKSPACE).as_posix()
    except (OSError, ValueError):
        return False
    with _record_lock:
        expected = _load_records().get(relative)
    if expected is None:
        return None
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return hmac.compare_digest(expected, hashlib.sha256(page.encode("utf-8")).hexdigest())
