import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from config import settings

KINDS = ("fact", "event")

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'event')),
    text TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(text, tokenize = 'porter unicode61');
"""


class Rejected(ValueError):
    """A memory was refused (too long, duplicate, store full...). The message says why."""


@dataclass(frozen=True)
class Memory:
    id: int
    kind: str
    text: str
    created: str


@dataclass(frozen=True)
class Proposal:
    kind: str
    text: str


class MemoryStore:
    def __init__(self, path: Path | str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)


    def _count(self, kind: str) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM memories WHERE kind = ?", (kind,)).fetchone()
        return row[0]

    def _get(self, memory_id: int) -> Memory | None:
        row = self.conn.execute(
            "SELECT id, kind, text, created FROM memories WHERE id = ?", (memory_id,)
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
                "INSERT INTO memories (kind, text, created) VALUES (?, ?, ?)", (kind, text, created)
            )
            new_id = cur.lastrowid or 0
            self.conn.execute("INSERT INTO memories_fts (rowid, text) VALUES (?, ?)", (new_id, text))
        return Memory(new_id, kind, text, created)

    def facts(self) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created FROM memories WHERE kind = 'fact' ORDER BY id"
            ).fetchall()
        return [Memory(*r) for r in rows]

    def list_all(self) -> list[Memory]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, created FROM memories "
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

    def delete(self, memory_id: int) -> bool:
        memory_id = int(memory_id)
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self.conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        return cur.rowcount > 0

    def clear(self) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM memories")
            self.conn.execute("DELETE FROM memories_fts")
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
