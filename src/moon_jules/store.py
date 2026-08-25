"""Persistencia local en SQLite. ADR-003.

El NO 10 del Inception ("no guardar datos sensibles del codigo") esta
implementado como esquema, no como intencion: las columnas para guardar
gitPatch, bashOutput o media sencillamente no existen.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .detector import NudgeRecord
from .models import Session, SessionState

SCHEMA_VERSION = 7

#: Clave de la pausa que afecta a todos los sources.
GLOBAL_SCOPE = "*"

#: Migraciones hacia adelante para bases que ya existen. Las versiones
#: 1-4 solo anadian tablas, que `CREATE TABLE IF NOT EXISTS` ya resuelve;
#: la 5 es la primera que altera una tabla y necesita ejecutarse.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    5: ("ALTER TABLE sessions ADD COLUMN failure_reason TEXT",),
    # Moon-Jules no crea sesiones: la siguiente tarea la asigna una
    # GitHub Action al fusionar el PR. La tabla que garantizaba
    # idempotencia al asignar ya no tiene destinatario.
    6: ("DROP TABLE IF EXISTS assignments",),
}

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
    failure_reason   TEXT,
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
CREATE TABLE IF NOT EXISTS pauses (
    scope     TEXT PRIMARY KEY,
    paused_at TEXT NOT NULL,
    until     TEXT,
    reason    TEXT
);
CREATE TABLE IF NOT EXISTS commands (
    id           TEXT PRIMARY KEY,
    verb         TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    status       TEXT NOT NULL,
    message      TEXT,
    completed_at TEXT
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
        self._migrate()

    def _migrate(self) -> None:
        """Lleva una base preexistente hasta SCHEMA_VERSION.

        En una base nueva el SCHEMA ya trae todo, asi que solo se anota
        la version: aplicar las migraciones ahi fallaria con "duplicate
        column".
        """
        row = self.db.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        desde = int(row["value"]) if row else SCHEMA_VERSION
        for version in sorted(MIGRATIONS):
            if version > desde:
                for sql in MIGRATIONS[version]:
                    self.db.execute(sql)
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
                 last_agent_at, last_agent_kind, activity_cursor,
                 failure_reason, seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                source=excluded.source,
                state=excluded.state,
                title=excluded.title,
                url=excluded.url,
                last_agent_at=COALESCE(excluded.last_agent_at, sessions.last_agent_at),
                last_agent_kind=COALESCE(excluded.last_agent_kind, sessions.last_agent_kind),
                activity_cursor=COALESCE(excluded.activity_cursor, sessions.activity_cursor),
                failure_reason=COALESCE(excluded.failure_reason, sessions.failure_reason),
                seen_at=excluded.seen_at
            """,
            (
                s.name, s.source, s.state.value, s.title, s.url, _iso(s.create_time),
                _iso(last_agent_at), last_agent_kind, cursor, s.failure_reason, _iso(now),
            ),
        )

    def newest_created(self) -> datetime | None:
        """`createTime` mas reciente conocido: la marca del incremental.

        Devuelve un datetime, no una cadena: el API y el store escriben
        la zona horaria distinto y comparar texto da resultados falsos.
        """
        row = self.db.execute(
            "SELECT MAX(created_at) AS m FROM sessions WHERE created_at IS NOT NULL"
        ).fetchone()
        return _dt(row["m"]) if row and row["m"] else None

    def tracked_non_terminal(self) -> list[str]:
        """Sesiones que no habian terminado la ultima vez que se miraron.

        Son las unicas cuyo estado puede haber cambiado sin que aparezcan
        en la primera pagina, asi que son las unicas que hay que releer
        una por una.
        """
        return [
            r["name"]
            for r in self.db.execute(
                "SELECT name FROM sessions WHERE state NOT IN ('COMPLETED','FAILED')"
            )
        ]

    def decisions(self) -> dict:
        """Lo que decidio el arquitecto, no lo que se observo.

        Triajes, pausas y nudges no se reconstruyen desde ninguna parte:
        si se pierden, vuelven a aparecer las alertas ya silenciadas. La
        tabla `sessions` en cambio es cache pura —se rehace con un poll
        completo— y por eso no entra aqui: sincronizarla seria subir
        cientos de KB por ciclo para no ganar nada.
        """
        return {
            "acks": [
                {"session": r["session"], "verdict": r["verdict"],
                 "acked_at": r["acked_at"], "note": r["note"]}
                for r in self.db.execute(
                    "SELECT session, verdict, acked_at, note FROM acks"
                )
            ],
            "pauses": [
                {"scope": r["scope"], "paused_at": r["paused_at"],
                 "until": r["until"], "reason": r["reason"]}
                for r in self.db.execute("SELECT * FROM pauses")
            ],
            "nudges": [
                {"session": r["session"], "sent_at": r["sent_at"],
                 "verified_at": r["verified_at"], "outcome": r["outcome"]}
                for r in self.db.execute(
                    "SELECT session, sent_at, verified_at, outcome FROM nudges "
                    "ORDER BY sent_at DESC LIMIT 200"
                )
            ],
        }

    def nudge_summary(self) -> dict[str, dict]:
        """Ultimo nudge por sesion, con su desenlace, para el snapshot."""
        out: dict[str, dict] = {}
        for r in self.db.execute(
            "SELECT session, sent_at, outcome, COUNT(*) OVER (PARTITION BY session) AS n "
            "FROM nudges ORDER BY session, sent_at DESC"
        ):
            out.setdefault(
                r["session"],
                {"sent_at": r["sent_at"], "outcome": r["outcome"], "count": int(r["n"])},
            )
        return out

    def cached_sessions(self) -> list[Session]:
        """Reconstruye las sesiones conocidas sin tocar la red."""
        return [
            Session(
                name=r["name"],
                state=SessionState.parse(r["state"]),
                title=r["title"],
                url=r["url"],
                source=r["source"],
                create_time=_dt(r["created_at"]),
                update_time=_dt(r["seen_at"]),
                failure_reason=r["failure_reason"],
            )
            for r in self.db.execute(
                "SELECT name, source, state, title, url, created_at, seen_at, "
                "failure_reason FROM sessions"
            )
        ]

    def failure_reasons(self) -> dict[str, str]:
        """Razones de fallo ya conocidas.

        FAILED es terminal: la razon no cambia nunca. Sin esta cache el
        ciclo re-descargaba *todas* las actividades de cada sesion
        fallida cada cinco minutos, para siempre.
        """
        return {
            r["name"]: r["failure_reason"]
            for r in self.db.execute(
                "SELECT name, failure_reason FROM sessions WHERE failure_reason IS NOT NULL"
            )
        }

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

    def last_nudges(self) -> dict[str, NudgeRecord]:
        """Todos los ultimos nudges de una vez.

        Antes era una consulta por sesion: con 538 sesiones, 538
        consultas por ciclo para leer una tabla con un punado de filas.
        """
        out: dict[str, NudgeRecord] = {}
        for r in self.db.execute(
            "SELECT session, MAX(sent_at) AS sent_at, COUNT(*) AS n "
            "FROM nudges GROUP BY session"
        ):
            sent = _dt(r["sent_at"])
            if sent:
                out[r["session"]] = NudgeRecord(sent_at=sent, count=int(r["n"]))
        return out

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

    # ---------- comandos: idempotencia por identificador ----------

    def command_result(self, cmd_id: str) -> dict | None:
        """Resultado de un comando ya ejecutado, si lo hubo.

        RTDB no es una cola: si la instancia actua y muere antes de
        publicar el acuse, al reiniciar volveria a actuar. Guardar el
        resultado por `id` permite reejecutar la *publicacion* sin
        reejecutar la *accion*.
        """
        row = self.db.execute(
            "SELECT id, status, message, completed_at FROM commands WHERE id = ?",
            (cmd_id,),
        ).fetchone()
        return dict(row) if row else None

    def record_command(
        self, cmd_id: str, verb: str, status: str, message: str,
        completed_at: str, now: datetime,
    ) -> None:
        self.db.execute(
            "INSERT INTO commands(id, verb, received_at, status, message, completed_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (cmd_id, verb, _iso(now), status, message, completed_at),
        )

    def command_log(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT id, verb, received_at, status, message FROM commands "
                "ORDER BY received_at DESC LIMIT ?",
                (limit,),
            )
        )

    # ---------- pausa de autonomia ----------

    def pause(
        self,
        scope: str,
        now: datetime,
        until: datetime | None = None,
        reason: str | None = None,
    ) -> None:
        """`scope` es GLOBAL_SCOPE o el `name` de un source."""
        self.db.execute(
            "INSERT INTO pauses(scope, paused_at, until, reason) VALUES (?,?,?,?) "
            "ON CONFLICT(scope) DO UPDATE SET paused_at = excluded.paused_at, "
            "until = excluded.until, reason = excluded.reason",
            (scope, _iso(now), _iso(until), reason),
        )

    def resume(self, scope: str) -> int:
        return self.db.execute("DELETE FROM pauses WHERE scope = ?", (scope,)).rowcount

    def active_pauses(self, now: datetime) -> dict[str, sqlite3.Row]:
        """Pausas vigentes. Las vencidas se retiran al pasar por aqui.

        Una pausa con `until` se auto-levanta: el modo de fallo que mas
        preocupa no es olvidarse de pausar, es olvidarse de reanudar y
        creer que la autonomia esta encendida cuando no lo esta.
        """
        vigentes: dict[str, sqlite3.Row] = {}
        vencidas: list[str] = []
        for row in self.db.execute("SELECT * FROM pauses"):
            hasta = _dt(row["until"])
            if hasta is not None and hasta <= now:
                vencidas.append(row["scope"])
            else:
                vigentes[row["scope"]] = row
        for scope in vencidas:
            self.db.execute("DELETE FROM pauses WHERE scope = ?", (scope,))
        return vigentes

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
