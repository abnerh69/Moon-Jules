"""Persistencia local en SQLite. ADR-003.

El NO 10 del Inception ("no guardar datos sensibles del codigo") esta
implementado como esquema, no como intencion: las columnas para guardar
gitPatch, bashOutput o media sencillamente no existen.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .detector import NudgeRecord
from .models import Session

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    name             TEXT PRIMARY KEY,
    source           TEXT,
    state            TEXT NOT NULL,
    title            TEXT,
    url              TEXT,
    created_at       TEXT,
    last_agent_at    TEXT,
    last_agent_kind  TEXT,
    activity_cursor  TEXT,
    seen_at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nudges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session     TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    verified_at TEXT,
    outcome     TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_nudges_session ON nudges(session, sent_at DESC);
CREATE TABLE IF NOT EXISTS assignments (
    issue_url   TEXT PRIMARY KEY,
    session     TEXT NOT NULL,
    source      TEXT NOT NULL,
    assigned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------- sesiones y cursor ----------

    def cursor_for(self, name: str) -> str | None:
        row = self.db.execute(
            "SELECT activity_cursor FROM sessions WHERE name = ?", (name,)
        ).fetchone()
        return row["activity_cursor"] if row else None

    def upsert_session(
        self,
        s: Session,
        *,
        last_agent_at: datetime | None,
        last_agent_kind: str | None,
        cursor: str | None,
        now: datetime,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO sessions
                (name, source, state, title, url, created_at,
                 last_agent_at, last_agent_kind, activity_cursor, seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                source=excluded.source,
                state=excluded.state,
                title=excluded.title,
                url=excluded.url,
                last_agent_at=COALESCE(excluded.last_agent_at, sessions.last_agent_at),
                last_agent_kind=COALESCE(excluded.last_agent_kind, sessions.last_agent_kind),
                activity_cursor=COALESCE(excluded.activity_cursor, sessions.activity_cursor),
                seen_at=excluded.seen_at
            """,
            (
                s.name, s.source, s.state.value, s.title, s.url, _iso(s.create_time),
                _iso(last_agent_at), last_agent_kind, cursor, _iso(now),
            ),
        )

    def known_freshness(self, name: str) -> tuple[datetime | None, str | None]:
        row = self.db.execute(
            "SELECT last_agent_at, last_agent_kind FROM sessions WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            return None, None
        return _dt(row["last_agent_at"]), row["last_agent_kind"]

    # ---------- nudges ----------

    def last_nudge(self, name: str) -> NudgeRecord | None:
        row = self.db.execute(
            "SELECT sent_at, COUNT(*) OVER () AS n FROM nudges "
            "WHERE session = ? ORDER BY sent_at DESC LIMIT 1",
            (name,),
        ).fetchone()
        if not row:
            return None
        sent = _dt(row["sent_at"])
        return NudgeRecord(sent_at=sent, count=int(row["n"])) if sent else None

    def record_nudge(self, name: str, prompt: str, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO nudges(session, sent_at, prompt) VALUES (?,?,?)",
            (name, _iso(now), prompt),
        )

    def resolve_nudge(self, name: str, outcome: str, now: datetime) -> None:
        self.db.execute(
            "UPDATE nudges SET outcome = ?, verified_at = ? "
            "WHERE id = (SELECT id FROM nudges WHERE session = ? "
            "            ORDER BY sent_at DESC LIMIT 1)",
            (outcome, _iso(now), name),
        )

    # ---------- asignaciones e idempotencia ----------

    def already_assigned(self, issue_url: str) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM assignments WHERE issue_url = ?", (issue_url,)
            ).fetchone()
            is not None
        )

    def record_assignment(self, issue_url: str, session: str, source: str, now: datetime) -> bool:
        """Devuelve False si el issue ya estaba asignado. Idempotente."""
        try:
            self.db.execute(
                "INSERT INTO assignments(issue_url, session, source, assigned_at) "
                "VALUES (?,?,?,?)",
                (issue_url, session, source, _iso(now)),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def sessions_created_since(self, since: datetime) -> int:
        """Consumo del presupuesto diario. Ventana movil de 24 h. ADR-005."""
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM assignments WHERE assigned_at >= ?",
            (_iso(since),),
        ).fetchone()
        return int(row["n"]) if row else 0

    def daily_budget_left(self, usable: int, now: datetime) -> int:
        return max(0, usable - self.sessions_created_since(now - timedelta(hours=24)))
