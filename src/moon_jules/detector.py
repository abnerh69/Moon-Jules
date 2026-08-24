"""Detección de estancamiento. Núcleo calibrado del proyecto.

Los umbrales y las tres invariantes del reloj de silencio salen del
Spike 01 (docs/spikes/), medidos sobre 3.749 huecos reales y 9 rescates
manuales. No son heurísticas de pizarra. Ver ADR-002 antes de tocarlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .models import Activity, AutonomyMode, Session, SessionState

# Eventos del agente que detienen el reloj de silencio.
# `sessionCompleted` NO es terminal en el flujo de actividades: hay
# sesiones que terminan y reviven horas despues con trabajo sobre el PR.
# Contar ese ocio como silencio dispara alertas sobre trabajo entregado.
CLOCK_FREEZING = frozenset({"sessionCompleted", "sessionFailed"})

TERMINAL_STATES = frozenset({SessionState.COMPLETED, SessionState.FAILED})


class Verdict(StrEnum):
    HEALTHY = "healthy"
    STALLED = "stalled"
    BLOCKED_FEEDBACK = "blocked_feedback"
    BLOCKED_PLAN = "blocked_plan"
    QUEUED_SLOW = "queued_slow"
    PAUSED_STALE = "paused_stale"
    FAILED = "failed"
    DONE = "done"
    NUDGE_UNANSWERED = "nudge_unanswered"
    NUDGE_BUDGET_SPENT = "nudge_budget_spent"


class Action(StrEnum):
    NONE = "none"
    NUDGE = "nudge"
    APPROVE_PLAN = "approve_plan"
    ASSIGN_NEXT = "assign_next"
    ALERT = "alert"


#: Acciones que escriben en el workspace de Jules, por modo de autonomia.
ALLOWED: dict[AutonomyMode, frozenset[Action]] = {
    AutonomyMode.READ_ONLY: frozenset({Action.NONE, Action.ALERT}),
    AutonomyMode.UNBLOCK_ONLY: frozenset(
        {Action.NONE, Action.ALERT, Action.NUDGE, Action.APPROVE_PLAN}
    ),
    AutonomyMode.FULL_AUTO: frozenset(Action),
}


@dataclass(frozen=True)
class Policy:
    """Umbrales. Defaults del Spike 01 y del plan Jules in Pro."""

    stall_after_s: int = 900  # N = 15 min. ADR-002.
    plan_warn_s: int = 900
    queue_warn_s: int = 1800
    nudge_verify_s: int = 600  # peor caso medido 8 min + margen
    max_nudges_per_session: int = 3
    nudge_prompt: str = "Completa la tarea"


@dataclass(frozen=True)
class NudgeRecord:
    """Ultimo nudge enviado a una sesion, leido del store."""

    sent_at: datetime
    count: int = 1


@dataclass(frozen=True)
class Freshness:
    """Resultado del calculo de frescura sobre las actividades del agente."""

    last_agent_at: datetime | None = None
    last_agent_kind: str | None = None

    @property
    def clock_frozen(self) -> bool:
        return self.last_agent_kind in CLOCK_FREEZING

    def silence_s(self, now: datetime) -> float | None:
        """Segundos de silencio, o None si el reloj esta congelado."""
        if self.last_agent_at is None or self.clock_frozen:
            return None
        return (now - self.last_agent_at).total_seconds()


@dataclass(frozen=True)
class Finding:
    session: Session
    verdict: Verdict
    action: Action
    silence_s: float | None
    reason: str
    downgraded_from: Action | None = None

    @property
    def needs_attention(self) -> bool:
        return self.verdict is not Verdict.HEALTHY and self.verdict is not Verdict.DONE


def freshness(activities: list[Activity]) -> Freshness:
    """Ultimo evento *del agente* y su tipo.

    Invariante 1 (ADR-002): solo cuentan actividades con
    originator == "agent". Si contaran las del usuario, cada nudge que
    enviamos reiniciaria nuestro propio reloj y una sesion muerta
    pareceria viva.

    Invariante 3: se usa `createTime` de la actividad, no `updateTime`
    de la sesion, que se mueve por causas ajenas al progreso del agente.
    """
    agent = [a for a in activities if a.originator == "agent" and a.create_time]
    if not agent:
        return Freshness()
    last = max(agent, key=lambda a: a.create_time)  # type: ignore[arg-type,return-value]
    return Freshness(last_agent_at=last.create_time, last_agent_kind=last.kind)


def _gate(action: Action, mode: AutonomyMode) -> tuple[Action, Action | None]:
    """Degrada la accion al modo de autonomia del source. ADR-005."""
    if action in ALLOWED[mode]:
        return action, None
    fallback = Action.ALERT if Action.ALERT in ALLOWED[mode] else Action.NONE
    return fallback, action


def assess(
    session: Session,
    fresh: Freshness,
    now: datetime,
    *,
    policy: Policy | None = None,
    mode: AutonomyMode = AutonomyMode.READ_ONLY,
    nudge: NudgeRecord | None = None,
    has_pending_queue: bool = False,
    owned: bool = False,
) -> Finding:
    """Dictamina el estado de una sesion y la accion que corresponde.

    `owned`: la sesion la creo Moon-Jules (habilita aprobar su plan).
    `has_pending_queue`: el source tiene issues sin asignar.
    """
    p = policy or Policy()
    sil = fresh.silence_s(now)

    def out(v: Verdict, a: Action, reason: str) -> Finding:
        gated, dropped = _gate(a, mode)
        return Finding(session, v, gated, sil, reason, downgraded_from=dropped)

    st = session.state

    if st is SessionState.FAILED:
        why = session.failure_reason or "sin razon declarada"
        # ADR-002: sendMessage sobre sesion terminal no esta verificado.
        # Hasta entonces FAILED solo alerta, nunca se le escribe.
        return out(Verdict.FAILED, Action.ALERT, f"sesion fallida: {why}")

    if st is SessionState.COMPLETED:
        if has_pending_queue:
            return out(Verdict.DONE, Action.ASSIGN_NEXT, "completada con cola pendiente")
        return out(Verdict.DONE, Action.NONE, "completada")

    if st is SessionState.AWAITING_PLAN_APPROVAL:
        if owned:
            return out(Verdict.BLOCKED_PLAN, Action.APPROVE_PLAN, "plan pendiente de aprobar")
        return out(
            Verdict.BLOCKED_PLAN, Action.ALERT, "plan pendiente en sesion ajena a Moon-Jules"
        )

    if st is SessionState.AWAITING_USER_FEEDBACK:
        return out(Verdict.BLOCKED_FEEDBACK, Action.NUDGE, "el agente espera respuesta")

    if st is SessionState.QUEUED:
        waited = (now - session.create_time).total_seconds() if session.create_time else 0.0
        if waited > p.queue_warn_s:
            return out(
                Verdict.QUEUED_SLOW,
                Action.ALERT,
                f"en cola {waited/60:.0f} min: posible tope de concurrencia",
            )
        return out(Verdict.HEALTHY, Action.NONE, "en cola")

    # PLANNING, IN_PROGRESS, PAUSED: aqui manda la frescura.

    # Un nudge sin respuesta es la senal de que el prompt magico dejo de
    # funcionar (riesgo 5 del Inception). Se comprueba antes que nada.
    if nudge is not None:
        since_nudge = (now - nudge.sent_at).total_seconds()
        answered = fresh.last_agent_at is not None and fresh.last_agent_at > nudge.sent_at
        if not answered and since_nudge > p.nudge_verify_s:
            return out(
                Verdict.NUDGE_UNANSWERED,
                Action.ALERT,
                f"nudge sin respuesta tras {since_nudge/60:.0f} min",
            )
        if not answered:
            return out(Verdict.HEALTHY, Action.NONE, "esperando respuesta al nudge")

    if fresh.clock_frozen:
        # Invariante 2 (ADR-002): sessionCompleted no es terminal en el
        # flujo de actividades. El tiempo tras el es ocio, no silencio.
        return out(Verdict.HEALTHY, Action.NONE, "en reposo tras cerrar trabajo")

    if sil is None:
        return out(Verdict.HEALTHY, Action.NONE, "sin actividad del agente todavia")

    if st is SessionState.PAUSED:
        if sil > p.stall_after_s:
            # El API no expone resume. Solo se puede avisar.
            return out(
                Verdict.PAUSED_STALE, Action.ALERT, f"pausada y muda {sil/60:.0f} min"
            )
        return out(Verdict.HEALTHY, Action.NONE, "pausada recientemente")

    threshold = p.plan_warn_s if st is SessionState.PLANNING else p.stall_after_s
    if sil <= threshold:
        return out(Verdict.HEALTHY, Action.NONE, f"activa, ultimo latido {sil:.0f}s")

    if st is SessionState.PLANNING and sil <= threshold * 2:
        return out(Verdict.HEALTHY, Action.NONE, f"planificando, {sil/60:.0f} min")

    spent = nudge.count if nudge else 0
    if spent >= p.max_nudges_per_session:
        return out(
            Verdict.NUDGE_BUDGET_SPENT,
            Action.ALERT,
            f"muda {sil/60:.0f} min tras {spent} intentos",
        )
    return out(Verdict.STALLED, Action.NUDGE, f"muda {sil/60:.0f} min")


@dataclass
class Report:
    """Resultado de un ciclo completo."""

    at: datetime
    findings: list[Finding] = field(default_factory=list)

    @property
    def attention(self) -> list[Finding]:
        return [f for f in self.findings if f.needs_attention]

    def by_verdict(self) -> dict[Verdict, int]:
        counts: dict[Verdict, int] = {}
        for f in self.findings:
            counts[f.verdict] = counts.get(f.verdict, 0) + 1
        return counts
