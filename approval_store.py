import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path

from tools.registry import REMEMBERABLE

MAX_APPROVALS = 500
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)


def load_approvals(path: str | Path) -> set[tuple[str, str]]:
    target = Path(path)
    try:
        if not target.exists():
            return set()
        if target.is_symlink() or target.stat().st_size > 50_000:
            return set()
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return set()
    entries = payload.get("allowed")
    if not isinstance(entries, list) or len(entries) > MAX_APPROVALS:
        return set()
    allowed = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool, scope = entry.get("tool"), entry.get("scope")
        if not isinstance(tool, str) or tool not in REMEMBERABLE:
            continue
        if not isinstance(scope, str) or scope == "*" or not _valid_scope(scope):
            continue
        allowed.add((tool, scope))
    return allowed


def save_approvals(path: str | Path, allowed: set[tuple[str, str]]) -> None:
    pairs = sorted(
        {(tool, scope) for tool, scope in allowed
         if tool in REMEMBERABLE and scope != "*" and _valid_scope(scope)}
    )
    entries = [{"tool": tool, "scope": scope} for tool, scope in pairs]
    if len(entries) > MAX_APPROVALS:
        raise ValueError("too many saved approvals")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": 1, "allowed": entries}, indent=2) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _valid_scope(scope: str) -> bool:
    try:
        ipaddress.ip_address(scope)
        return True
    except ValueError:
        return bool(HOSTNAME.fullmatch(scope))
