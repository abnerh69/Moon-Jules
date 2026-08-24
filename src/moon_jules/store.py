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

SCHEMA_VERSION = 3

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
CREATE TABLE IF NOT EXISTS notifications (
    session     TEXT NOT NULL,
    verdict     TEXT NOT NULL,
    notified_at TEXT NOT NULL,
    PRIMARY KEY (session, verdict)
);
CREATE TABLE IF NOT EXISTS acks (
    session  TEXT NOT NULL,
    verdict  TEXT NOT NULL,
    acked_at TEXT NOT NULL,
    note     TEXT,
    PRIMARY KEY (session, verdict)
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
        # Las migraciones hasta hoy solo anaden tablas, y `CREATE TABLE
        # IF NOT EXISTS` ya las aplica. Se registra la version para que
        # una migracion futura que si toque datos sepa de donde parte.
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
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

    # ---------- triaje: silenciar lo ya visto ----------

    def is_acked(self, session: str, verdict: str) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM acks WHERE session = ? AND verdict = ?", (session, verdict)
            ).fetchone()
            is not None
        )

    def acked_pairs(self) -> set[tuple[str, str]]:
        """Todo el triaje de una vez: un SELECT por ciclo, no uno por sesion."""
        return {
            (r["session"], r["verdict"])
            for r in self.db.execute("SELECT session, verdict FROM acks")
        }

    def ack(self, session: str, verdict: str, now: datetime, note: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO acks(session, verdict, acked_at, note) VALUES (?,?,?,?) "
            "ON CONFLICT(session, verdict) DO UPDATE SET "
            "acked_at = excluded.acked_at, note = excluded.note",
            (session, verdict, _iso(now), note),
        )

    def unack(self, session: str, verdict: str | None = None) -> int:
        if verdict:
            cur = self.db.execute(
                "DELETE FROM acks WHERE session = ? AND verdict = ?", (session, verdict)
            )
        else:
            cur = self.db.execute("DELETE FROM acks WHERE session = ?", (session,))
        return cur.rowcount

    def list_acks(self) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT a.session, a.verdict, a.acked_at, a.note, s.title, s.source "
                "FROM acks a LEFT JOIN sessions s ON s.name = a.session "
                "ORDER BY a.acked_at DESC"
            )
        )

    # ---------- historial ----------

    def nudge_log(self, session: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        sql = (
            "SELECT n.session, n.sent_at, n.verified_at, n.outcome, s.title, s.source "
            "FROM nudges n LEFT JOIN sessions s ON s.name = n.session "
        )
        args: tuple = ()
        if session:
            sql += "WHERE n.session = ? "
            args = (session,)
        sql += "ORDER BY n.sent_at DESC LIMIT ?"
        return list(self.db.execute(sql, (*args, limit)))

    def nudge_stats(self) -> dict[str, float | int | None]:
        """Cuantos nudges se enviaron, cuantos revivieron la sesion y en cuanto."""
        row = self.db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(outcome = 'answered') AS answered, "
            "SUM(outcome = 'unanswered') AS unanswered, "
            "SUM(outcome = 'pending') AS pending "
            "FROM nudges"
        ).fetchone()
        tiempos = [
            (_dt(r["verified_at"]) - _dt(r["sent_at"])).total_seconds()
            for r in self.db.execute(
                "SELECT sent_at, verified_at FROM nudges WHERE outcome = 'answered' "
                "AND verified_at IS NOT NULL"
            )
        ]
        tiempos.sort()
        return {
            "total": row["total"] or 0,
            "answered": row["answered"] or 0,
            "unanswered": row["unanswered"] or 0,
            "pending": row["pending"] or 0,
            "median_recovery_s": tiempos[len(tiempos) // 2] if tiempos else None,
        }

    def session_rows(self) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT name, source, state, title, last_agent_at, last_agent_kind, seen_at "
                "FROM sessions ORDER BY last_agent_at DESC"
            )
        )

    # ---------- supresion de notificaciones repetidas ----------

    def should_notify(self, session: str, verdict: str, now: datetime, cooldown_s: int) -> bool:
        """False si ya se notifico esto mismo dentro de la ventana.

        La clave es (sesion, veredicto): si una sesion pasa de STALLED a
        NUDGE_UNANSWERED, eso si es noticia nueva y vuelve a avisar.
        """
        row = self.db.execute(
            "SELECT notified_at FROM notifications WHERE session = ? AND verdict = ?",
            (session, verdict),
        ).fetchone()
        if not row:
            return True
        last = _dt(row["notified_at"])
        return last is None or (now - last).total_seconds() >= cooldown_s

    def record_notification(self, session: str, verdict: str, now: datetime) -> None:
        self.db.execute(
            "INSERT INTO notifications(session, verdict, notified_at) VALUES (?,?,?) "
            "ON CONFLICT(session, verdict) DO UPDATE SET notified_at = excluded.notified_at",
            (session, verdict, _iso(now)),
        )
