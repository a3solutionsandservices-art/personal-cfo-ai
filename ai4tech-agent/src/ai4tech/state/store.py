"""Durable state for the pipeline (PRD §8, FR-ORC-1/3, FR-TR-4).

A thin SQLite-backed store recording:
  * processed item GUIDs               -> exactly-once handling (FR-SRC-2, G1)
  * transcription cache (by GUID)      -> no re-transcription on re-run (FR-TR-4)
  * the surfaced-signal ledger         -> novelty across runs (FR-SCO-3)
  * per-run records + brief sent flag  -> idempotent runs (FR-ORC-1)
  * quarantined items                  -> never silently dropped (FR-ORC-4)

The store is the single source of truth for "have we already done this?", which
is what makes a crashed run safe to re-run.
"""

from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Optional

from ..models import Signal, utcnow_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_items (
    guid        TEXT PRIMARY KEY,
    source_id   TEXT,
    title       TEXT,
    processed_at TEXT
);
CREATE TABLE IF NOT EXISTS transcripts (
    guid      TEXT PRIMARY KEY,
    provider  TEXT,
    payload   TEXT,          -- JSON: {text, segments}
    cached_at TEXT
);
CREATE TABLE IF NOT EXISTS signal_ledger (
    id         TEXT PRIMARY KEY,
    item_guid  TEXT,
    theme_id   TEXT,
    text       TEXT,
    final      REAL,
    embedding  TEXT,         -- JSON list[float]
    surfaced_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT,         -- running | delivered | failed
    brief_sent  INTEGER DEFAULT 0,
    log         TEXT
);
CREATE TABLE IF NOT EXISTS quarantine (
    guid       TEXT PRIMARY KEY,
    stage      TEXT,
    error      TEXT,
    quarantined_at TEXT
);
"""


class StateStore:
    def __init__(self, db_path: str | Path = "data/state.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ items
    def is_processed(self, guid: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed_items WHERE guid = ?", (guid,)
        )
        return cur.fetchone() is not None

    def mark_processed(self, guid: str, source_id: str, title: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO processed_items(guid, source_id, title, processed_at)"
            " VALUES (?, ?, ?, ?)",
            (guid, source_id, title, utcnow_iso()),
        )
        self._conn.commit()

    # ------------------------------------------------------------- transcripts
    def get_transcript(self, guid: str) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT provider, payload FROM transcripts WHERE guid = ?", (guid,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        payload["provider"] = row["provider"]
        return payload

    def put_transcript(self, guid: str, provider: str, text: str, segments: list[dict]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO transcripts(guid, provider, payload, cached_at)"
            " VALUES (?, ?, ?, ?)",
            (guid, provider, json.dumps({"text": text, "segments": segments}), utcnow_iso()),
        )
        self._conn.commit()

    # ------------------------------------------------------------ signal ledger
    def add_signal(self, signal: Signal) -> None:
        rec = signal.to_record()
        self._conn.execute(
            "INSERT OR REPLACE INTO signal_ledger"
            "(id, item_guid, theme_id, text, final, embedding, surfaced_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rec["id"],
                rec["item_guid"],
                rec["theme_id"],
                rec["text"],
                rec["final"],
                json.dumps(signal.embedding),
                utcnow_iso(),
            ),
        )
        self._conn.commit()

    def prior_embeddings(self, theme_id: str) -> list[list[float]]:
        """All previously-surfaced embeddings for a theme (novelty source)."""
        cur = self._conn.execute(
            "SELECT embedding FROM signal_ledger WHERE theme_id = ?", (theme_id,)
        )
        out: list[list[float]] = []
        for row in cur.fetchall():
            try:
                vec = json.loads(row["embedding"])
            except (TypeError, json.JSONDecodeError):
                continue
            if vec:
                out.append(vec)
        return out

    def max_similarity(self, theme_id: str, embedding: list[float]) -> float:
        """Highest cosine similarity to any prior signal in the theme (FR-SCO-3)."""
        if not embedding:
            return 0.0
        best = 0.0
        for prior in self.prior_embeddings(theme_id):
            best = max(best, _cosine(embedding, prior))
        return best

    # --------------------------------------------------------------------- runs
    def start_run(self, run_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO runs(run_id, started_at, status) VALUES (?, ?, 'running')",
            (run_id, utcnow_iso()),
        )
        self._conn.commit()

    def run_brief_sent(self, run_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT brief_sent FROM runs WHERE run_id = ?", (run_id,)
        )
        row = cur.fetchone()
        return bool(row and row["brief_sent"])

    def finish_run(self, run_id: str, status: str, brief_sent: bool, log: str = "") -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, brief_sent = ?, log = ?"
            " WHERE run_id = ?",
            (utcnow_iso(), status, int(brief_sent), log, run_id),
        )
        self._conn.commit()

    # -------------------------------------------------------------- quarantine
    def quarantine(self, guid: str, stage: str, error: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO quarantine(guid, stage, error, quarantined_at)"
            " VALUES (?, ?, ?, ?)",
            (guid, stage, error, utcnow_iso()),
        )
        self._conn.commit()

    def quarantined(self) -> list[dict]:
        cur = self._conn.execute(
            "SELECT guid, stage, error FROM quarantine ORDER BY quarantined_at"
        )
        return [dict(r) for r in cur.fetchall()]


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a = list(a)
    b = list(b)
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
