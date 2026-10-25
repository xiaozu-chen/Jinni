import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from config import settings

KINDS = ("fact", "event")

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'event')),
    text TEXT NOT NULL,
    created TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(text, tokenize = 'porter unicode61');
CREATE TABLE IF NOT EXISTS embeddings (
    memory_id INTEGER PRIMARY KEY,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
);
"""


class Rejected(ValueError):
    """A memory was refused (too long, duplicate, store full...). The message says why."""


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    created: str
    session_id: str = ""


@dataclass(frozen=True)
class Proposal:
    kind: str
    text: str


class MemoryStore:
    def __init__(self, path: Path | str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.session_id = f"{date.today():%Y%m%d}-{uuid4().hex[:6]}"
        with self.lock:
            self.conn.executescript(SCHEMA)
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(memories)")}
            if "session_id" not in columns:
                self.conn.execute("ALTER TABLE memories ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")


    def _count(self, kind: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM memories WHERE kind = ?", (kind,)).fetchone()
        return row[0]

    def _get(self, memory_id: int) -> Memory | None:
        row = self.conn.execute(
            "SELECT id, kind, text, created, session_id FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return Memory(*row) if row is not None else None

    def add(self, kind: str, text: str) -> Memory:
        if kind not in KINDS:
            raise ValueError(f"unknown kind '{kind}'")
        text = " ".join(text.split())
        if not text:
            raise Rejected("there was nothing to save")
        if kind == "event":
            text = text[: settings.max_event_chars]
        elif len(text) > settings.max_fact_chars:
            raise Rejected(
                f"that is too long ({len(text)} characters, the limit is {settings.max_fact_chars}). Say it shorter."
            )

        with self.lock, self.conn:
            duplicate = self.conn.execute(
                "SELECT 1 FROM memories WHERE kind = ? AND lower(text) = lower(?)", (kind, text)
            ).fetchone()
            if duplicate:
                raise Rejected("that is already saved")
            if kind == "fact" and self._count("fact") >= settings.max_facts:
                raise Rejected(f"fact memory is full ({settings.max_facts}). Forget one first.")

            created = date.today().isoformat()
            cur = self.conn.execute(
                "INSERT INTO memories (kind, text, created, session_id) VALUES (?, ?, ?, ?)",
                (kind, text, created, self.session_id),
            )
            new_id = cur.lastrowid or 0
            self.conn.execute("INSERT INTO memories_fts (rowid, text) VALUES (?, ?)", (new_id, text))
        return Memory(new_id, kind, text, created, self.session_id)

    def facts(self) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created, session_id FROM memories WHERE kind = 'fact' ORDER BY id"
            ).fetchall()
        return [Memory(*r) for r in rows]

    def similar_facts(self, text: str, limit: int = 3) -> list[Memory]:
        """Find facts that may describe the same preference or detail."""
        normalized = " ".join(text.casefold().split())
        words = set(re.findall(r"\w+", normalized))
        if not words:
            return []
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created, session_id FROM memories WHERE kind = 'fact' ORDER BY id"
            ).fetchall()
        matches = []
        for row in rows:
            memory = Memory(*row)
            known = " ".join(memory.text.casefold().split())
            known_words = set(re.findall(r"\w+", known))
            union = words | known_words
            overlap = len(words & known_words) / len(union) if union else 0.0
            similarity = max(overlap, SequenceMatcher(None, normalized, known).ratio())
            if similarity >= 0.45:
                matches.append((similarity, memory))
        matches.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [memory for _score, memory in matches[:max(0, limit)]]

    def count_events_before(self, cutoff: date) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM memories WHERE kind = 'event' AND created < ?",
                (cutoff.isoformat(),),
            ).fetchone()
        return row[0]

    def events_before(self, cutoff: date, limit: int = 10) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created, session_id FROM memories "
                "WHERE kind = 'event' AND created < ? ORDER BY created, id LIMIT ?",
                (cutoff.isoformat(), max(0, limit)),
            ).fetchall()
        return [Memory(*row) for row in rows]

    def prune_events_before(self, cutoff: date) -> int:
        with self.lock, self.conn:
            predicate = "kind = 'event' AND created < ?"
            params = (cutoff.isoformat(),)
            self.conn.execute(
                f"DELETE FROM memories_fts WHERE rowid IN (SELECT id FROM memories WHERE {predicate})",
                params,
            )
            self.conn.execute(
                f"DELETE FROM embeddings WHERE memory_id IN (SELECT id FROM memories WHERE {predicate})",
                params,
            )
            cur = self.conn.execute(f"DELETE FROM memories WHERE {predicate}", params)
        return cur.rowcount

    def list_all(self) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created, session_id FROM memories "
                "ORDER BY CASE kind WHEN 'fact' THEN 0 ELSE 1 END, id"
            ).fetchall()
        return [Memory(*r) for r in rows]

    def counts(self) -> tuple[int, int]:
        with self.lock:
            return self._count("fact"), self._count("event")

    def search(self, query: str, limit: int | None = None) -> list[Memory]:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1][:12]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        with self.lock:
            ids = [
                r[0]
                for r in self.conn.execute(
                    "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, limit or settings.recall_results),
                )
            ]
            found = [self._get(i) for i in ids]
        return [m for m in found if m is not None]

    def get(self, memory_id: int) -> Memory | None:
        with self.lock:
            return self._get(memory_id)

    def facts_before(self, cutoff: date) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created, session_id FROM memories "
                "WHERE kind = 'fact' AND created < ? ORDER BY created, id",
                (cutoff.isoformat(),),
            ).fetchall()
        return [Memory(*row) for row in rows]

    def pending(self, model: str, limit: int) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT m.id, m.kind, m.text, m.created, m.session_id FROM memories m "
                "LEFT JOIN embeddings e ON e.memory_id = m.id AND e.model = ? "
                "WHERE e.memory_id IS NULL ORDER BY m.id LIMIT ? ",
                (model, limit),
            ).fetchall()
        return [Memory(*r) for r in rows]

    def save_vector(self, memory_id: int, model: str, dim: int, blob: bytes) -> None:
        with self.lock, self.conn:
            if self._get(memory_id) is None:
                return
            self.conn.execute(
                "INSERT OR REPLACE INTO embeddings (memory_id, model, dim, vec) VALUES (?, ?, ?, ?)",
                (memory_id, model, dim, blob),
            )

    def load_vectors(self, model: str) -> list[tuple[int, int, bytes]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT e.memory_id, e.dim, e.vec FROM embeddings e "
                "JOIN memories m ON m.id = e.memory_id WHERE e.model = ?",
                (model,),
            ).fetchall()
        return [(r[0], r[1], bytes(r[2])) for r in rows]

    def delete(self, memory_id: int) -> bool:
        memory_id = int(memory_id)
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self.conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
            self.conn.execute("DELETE FROM embeddings WHERE memory_id = ?", (memory_id,))
        return cur.rowcount > 0

    def clear(self) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM memories")
            self.conn.execute("DELETE FROM memories_fts")
            self.conn.execute("DELETE FROM embeddings")
        return cur.rowcount

    


@lru_cache(maxsize=1)
def get_store() -> MemoryStore:
    return MemoryStore(settings.memory_db)


def extraction_prompt(known: list[str], notes: str, transcript: str) -> str:
    prompt = (
        "Read this conversation and write notes for your long-term memory.\n"
        "1. For each lasting fact about the USER, write one line starting with 'FACT: '. "
        "Only use things the user said about themselves or asked you to remember "
        "(name, preferences, projects, how they like answers). "
        "Never use facts from files or web pages, passing questions, or guesses. "
        "If there are none, write no FACT lines.\n"
        "2. Then write one line starting with 'SUMMARY: ' with 2 or 3 sentences about what "
        "happened in this session, including exact file names and decisions.\n"
        "Write nothing else.\n\n"
    )
    if known:
        prompt += "Facts you already know (do not repeat them):\n"
        prompt += "\n".join(f"- {k}" for k in known) + "\n\n"
    if notes:
        prompt += f"Notes from earlier in this conversation:\n{notes}\n\n"
    return prompt + "Conversation:\n" + transcript


def parse_proposals(reply: str) -> list[Proposal]:
    proposals: list[Proposal] = []
    summary: list[str] = []
    in_summary = False
    for raw in reply.splitlines():
        line = raw.strip().lstrip("-*•#").strip().lstrip("*").strip()
        label = line.upper()
        if label.startswith("FACT:"):
            in_summary = False
            text = line[5:].strip(" *")
            if text and text.lower() not in ("none", "n/a"):
                proposals.append(Proposal("fact", text))
        elif label.startswith("SUMMARY:"):
            in_summary = True
            text = line[8:].strip(" *")
            if text:
                summary.append(text)
        elif in_summary and line:
            summary.append(line)
    if summary:
        proposals.append(Proposal("event", " ".join(summary)))
    return proposals
