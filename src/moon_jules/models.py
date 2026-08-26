"""Modelos de dominio.

Espejo de los esquemas del discovery doc de Jules (revision 20260821),
verificados contra el API en vivo el 2026-08-24. Solo metadatos: ningun
gitPatch, ningun bashOutput, ninguna media. NO 10 del Inception.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

#: Campos de evento de Activity. Exactamente uno viene poblado.
ACTIVITY_KINDS = (
    "planGenerated",
    "planApproved",
    "userMessaged",
    "agentMessaged",
    "progressUpdated",
    "sessionCompleted",
    "sessionFailed",
)


class SessionState(StrEnum):
    """Enum verificado del API. Nueve valores, ni uno mas."""

    UNSPECIFIED = "STATE_UNSPECIFIED"
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    AWAITING_PLAN_APPROVAL = "AWAITING_PLAN_APPROVAL"
    AWAITING_USER_FEEDBACK = "AWAITING_USER_FEEDBACK"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"

    @classmethod
    def parse(cls, raw: str | None) -> SessionState:
        try:
            return cls(raw or "STATE_UNSPECIFIED")
        except ValueError:
            # El API esta en alpha: un estado nuevo no debe tumbar el loop.
            return cls.UNSPECIFIED


class AutonomyMode(StrEnum):
    """Dos modos, no tres.

    El tercero (`full_auto`) existia para asignar la siguiente tarea de
    la cola. Esa decision no es de Moon-Jules: la resuelve una GitHub
    Action al fusionar el PR. Sin ese acto, `full_auto` no hacia nada
    que `unblock_only` no hiciera ya, y un modo que miente en el config
    es peor que no tenerlo. Ver la enmienda de ADR-005.
    """

    READ_ONLY = "read_only"
    UNBLOCK_ONLY = "unblock_only"

    @classmethod
    def parse(cls, raw: str) -> AutonomyMode:
        if raw == "full_auto":
            # Se acepta para no romper configuraciones existentes.
            return cls.UNBLOCK_ONLY
        return cls(raw)


def parse_ts(raw: str | None) -> datetime | None:
    """ISO-8601 de Google a datetime con tz. Trunca nanosegundos.

    El API devuelve precision variable: 6 digitos en activities, hasta 9
    en sessions. fromisoformat solo acepta 3 o 6.
    """
    if not raw:
        return None
    s = raw.replace("Z", "+00:00")
    if "." in s:
        head, _, tail = s.partition(".")
        frac, sign, off = (
            tail.partition("+") if "+" in tail else tail.partition("-")
        )
        s = f"{head}.{frac[:6]}{sign}{off}"
    try:
        return datetime.fromisoformat(s).astimezone(UTC)
    except ValueError:
        return None


@dataclass(frozen=True)
class Activity:
    name: str
    kind: str
    originator: str | None
    create_time: datetime | None
    description: str | None = None
    text: str | None = None

    @classmethod
    def from_api(cls, raw: dict) -> Activity:
        kind = next((k for k in ACTIVITY_KINDS if k in raw), "unknown")
        text = None
        if kind == "agentMessaged":
            text = (raw.get("agentMessaged") or {}).get("agentMessage")
        elif kind == "userMessaged":
            text = (raw.get("userMessaged") or {}).get("userMessage")
        elif kind == "sessionFailed":
            text = (raw.get("sessionFailed") or {}).get("reason")
        elif kind == "progressUpdated":
            text = (raw.get("progressUpdated") or {}).get("title")
        return cls(
            name=raw.get("name", ""),
            kind=kind,
            originator=raw.get("originator"),
            create_time=parse_ts(raw.get("createTime")),
            description=raw.get("description"),
            text=text,
        )


@dataclass(frozen=True)
class Session:
    name: str
    state: SessionState
    title: str | None = None
    url: str | None = None
    source: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    archived: bool = False
    pr_url: str | None = None
    failure_reason: str | None = None
    #: Ultimo `agentMessaged`. Ahi esta lo que Jules dijo de verdad; el
    #: `reason` del API es siempre "unable to complete the task".
    last_message: str | None = None
    #: Instante y tipo del ultimo evento del agente, para publicarlos.
    last_agent_at: datetime | None = None
    last_agent_kind: str | None = None

    @property
    def id(self) -> str:
        return self.name.removeprefix("sessions/")

    @property
    def repo(self) -> str:
        """Nombre corto del repo, para mostrar."""
        if not self.source:
            return "(sin repo)"
        return self.source.removeprefix("sources/").removeprefix("github/")

    @classmethod
    def from_api(cls, raw: dict) -> Session:
        ctx = raw.get("sourceContext") or {}
        pr = None
        for o in raw.get("outputs") or []:
            if "pullRequest" in o:
                pr = (o["pullRequest"] or {}).get("url")
                break
        return cls(
            name=raw.get("name", ""),
            state=SessionState.parse(raw.get("state")),
            title=raw.get("title"),
            url=raw.get("url"),
            source=ctx.get("source"),
            create_time=parse_ts(raw.get("createTime")),
            update_time=parse_ts(raw.get("updateTime")),
            archived=bool(raw.get("archived")),
            pr_url=pr,
        )

    def with_details(
        self,
        reason: str | None = None,
        message: str | None = None,
        agent_at: datetime | None = None,
        agent_kind: str | None = None,
    ) -> Session:
        return Session(
            name=self.name,
            state=self.state,
            title=self.title,
            url=self.url,
            source=self.source,
            create_time=self.create_time,
            update_time=self.update_time,
            archived=self.archived,
            pr_url=self.pr_url,
            failure_reason=reason if reason is not None else self.failure_reason,
            last_message=message if message is not None else self.last_message,
            last_agent_at=agent_at or self.last_agent_at,
            last_agent_kind=agent_kind or self.last_agent_kind,
        )

    def with_failure(self, reason: str | None) -> Session:
        """Compatibilidad con el nombre anterior."""
        return self.with_details(reason=reason)
