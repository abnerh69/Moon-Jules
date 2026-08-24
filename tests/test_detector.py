"""Tests del detector.

Los casos que importan no son inventados: son las firmas que el Spike 01
encontro en las 562 sesiones reales del enjambre. Cada test que menciona
el spike protege un hallazgo medido; romperlo es reintroducir un falso
positivo que ya costo encontrar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.detector import (
    Action,
    Finding,
    Freshness,
    NudgeRecord,
    Policy,
    Verdict,
    assess,
    freshness,
)
from moon_jules.models import Activity, AutonomyMode, Session, SessionState, parse_ts

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
P = Policy()


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def act(kind: str, originator: str, when: datetime) -> Activity:
    return Activity(name=f"a/{kind}", kind=kind, originator=originator, create_time=when)


def sess(state: SessionState, **kw: object) -> Session:
    return Session(
        name="sessions/1",
        state=state,
        source="sources/github/acme/repo",
        create_time=kw.pop("create_time", ago(hours=1)),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def check(
    state: SessionState,
    fresh: Freshness,
    *,
    mode: AutonomyMode = AutonomyMode.UNBLOCK_ONLY,
    **kw: object,
) -> Finding:
    return assess(sess(state), fresh, NOW, policy=P, mode=mode, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------
# freshness: las tres invariantes del reloj (ADR-002)
# --------------------------------------------------------------------


def test_solo_cuentan_eventos_del_agente():
    """Invariante 1: un nudge nuestro no puede reiniciar nuestro reloj.

    Sin esto, cada mensaje que Moon-Jules envia haria parecer viva a una
    sesion muerta, y el monitor se enganaria a si mismo para siempre.
    """
    f = freshness(
        [
            act("progressUpdated", "agent", ago(hours=3)),
            act("userMessaged", "user", ago(minutes=1)),
        ]
    )
    assert f.last_agent_at == ago(hours=3)
    assert f.silence_s(NOW) == pytest.approx(3 * 3600)


def test_session_completed_congela_el_reloj():
    """Invariante 2: sessionCompleted no es terminal en el flujo.

    Cinco de los siete falsos positivos del spike eran sesiones que
    cerraron y revivieron horas despues. Ese tiempo es ocio, no silencio.
    """
    f = freshness([act("sessionCompleted", "agent", ago(hours=4))])
    assert f.clock_frozen
    assert f.silence_s(NOW) is None


def test_session_failed_tambien_congela():
    f = freshness([act("sessionFailed", "agent", ago(hours=9))])
    assert f.clock_frozen is True


def test_sin_actividad_del_agente():
    assert freshness([act("userMessaged", "user", ago(minutes=2))]).last_agent_at is None
    assert freshness([]).silence_s(NOW) is None


def test_toma_el_mas_reciente_no_el_ultimo_de_la_lista():
    f = freshness(
        [
            act("progressUpdated", "agent", ago(minutes=1)),
            act("progressUpdated", "agent", ago(minutes=40)),
        ]
    )
    assert f.silence_s(NOW) == pytest.approx(60)


# --------------------------------------------------------------------
# umbral: la rodilla en 15 minutos
# --------------------------------------------------------------------


@pytest.mark.parametrize("secs", [26, 77, 456])  # p50, p90, p99 sanos del spike
def test_cadencia_sana_no_alarma(secs: int):
    f = Freshness(ago(seconds=secs), "progressUpdated")
    assert check(SessionState.IN_PROGRESS, f).verdict is Verdict.HEALTHY


def test_justo_bajo_el_umbral_esta_sana():
    f = Freshness(ago(seconds=P.stall_after_s - 1), "progressUpdated")
    assert check(SessionState.IN_PROGRESS, f).verdict is Verdict.HEALTHY


def test_pasado_el_umbral_se_estanca():
    f = Freshness(ago(seconds=P.stall_after_s + 1), "progressUpdated")
    r = check(SessionState.IN_PROGRESS, f)
    assert r.verdict is Verdict.STALLED
    assert r.action is Action.NUDGE


def test_mediana_de_estancamiento_real_se_detecta():
    """52 minutos: la mediana medida antes de que el arquitecto rescatara."""
    f = Freshness(ago(minutes=52), "progressUpdated")
    assert check(SessionState.IN_PROGRESS, f).verdict is Verdict.STALLED


def test_reposo_largo_tras_completar_no_alarma():
    """El caso de 235 min que rompia el calculo ingenuo por maximo."""
    f = Freshness(ago(minutes=235), "sessionCompleted")
    r = check(SessionState.IN_PROGRESS, f)
    assert r.verdict is Verdict.HEALTHY
    assert r.action is Action.NONE


def test_planning_tolera_el_doble():
    f = Freshness(ago(minutes=20), "planGenerated")
    assert check(SessionState.PLANNING, f).verdict is Verdict.HEALTHY
    f2 = Freshness(ago(minutes=40), "planGenerated")
    assert check(SessionState.PLANNING, f2).verdict is Verdict.STALLED


# --------------------------------------------------------------------
# firmas de fallo observadas en el enjambre real
# --------------------------------------------------------------------


def test_paused_muda_solo_alerta_porque_no_hay_resume():
    """Seis PAUSED con cola progressUpdated: la colgada silenciosa."""
    f = Freshness(ago(days=97), "progressUpdated")
    r = check(SessionState.PAUSED, f, mode=AutonomyMode.UNBLOCK_ONLY)
    assert r.verdict is Verdict.PAUSED_STALE
    assert r.action is Action.ALERT


def test_paused_reciente_no_alarma():
    f = Freshness(ago(minutes=2), "progressUpdated")
    assert check(SessionState.PAUSED, f).verdict is Verdict.HEALTHY


def test_failed_nunca_recibe_escritura():
    """sendMessage sobre terminal no esta verificado: solo se alerta."""
    s = sess(SessionState.FAILED).with_failure("Unable to install dependencies")
    r = assess(s, Freshness(), NOW, mode=AutonomyMode.UNBLOCK_ONLY)
    assert r.verdict is Verdict.FAILED
    assert r.action is Action.ALERT
    assert "dependencies" in r.reason


def test_awaiting_feedback_se_desbloquea():
    r = check(SessionState.AWAITING_USER_FEEDBACK, Freshness(ago(minutes=1), "agentMessaged"))
    assert r.verdict is Verdict.BLOCKED_FEEDBACK
    assert r.action is Action.NUDGE


def test_plan_ajeno_no_se_aprueba_solo():
    f = Freshness(ago(minutes=1), "planGenerated")
    ajena = check(SessionState.AWAITING_PLAN_APPROVAL, f, owned=False)
    assert ajena.action is Action.ALERT
    propia = check(SessionState.AWAITING_PLAN_APPROVAL, f, owned=True)
    assert propia.action is Action.APPROVE_PLAN


def test_cola_larga_sugiere_tope_de_concurrencia():
    s = sess(SessionState.QUEUED, create_time=ago(minutes=45))
    r = assess(s, Freshness(), NOW, policy=P, mode=AutonomyMode.UNBLOCK_ONLY)
    assert r.verdict is Verdict.QUEUED_SLOW
    assert "concurrencia" in r.reason


# --------------------------------------------------------------------
# el canario del prompt magico
# --------------------------------------------------------------------


def test_nudge_sin_respuesta_escala_a_alerta():
    """Riesgo 5: el dia que 'Completa la tarea' deje de funcionar."""
    f = Freshness(ago(hours=2), "progressUpdated")
    n = NudgeRecord(sent_at=ago(seconds=P.nudge_verify_s + 60))
    r = check(SessionState.IN_PROGRESS, f, nudge=n)
    assert r.verdict is Verdict.NUDGE_UNANSWERED
    assert r.action is Action.ALERT


def test_dentro_de_la_ventana_se_espera():
    f = Freshness(ago(hours=2), "progressUpdated")
    n = NudgeRecord(sent_at=ago(minutes=3))
    assert check(SessionState.IN_PROGRESS, f, nudge=n).verdict is Verdict.HEALTHY


def test_nudge_respondido_devuelve_la_sesion_a_sana():
    """Mediana medida de respuesta: 70 segundos."""
    n = NudgeRecord(sent_at=ago(minutes=5))
    f = Freshness(ago(minutes=4), "progressUpdated")
    assert check(SessionState.IN_PROGRESS, f, nudge=n).verdict is Verdict.HEALTHY


def test_presupuesto_de_nudges_se_agota():
    """Caso real: cada nudge revivio la sesion, pero se volvio a colgar.

    El agente respondio al ultimo nudge (hay actividad posterior) y
    despues se quedo mudo otra vez. Con el presupuesto gastado se deja
    de insistir: un falso positivo no debe contaminar el contexto cada
    ciclo, y uno verdadero ya demostro que el prompt no basta.
    """
    n = NudgeRecord(sent_at=ago(minutes=45), count=P.max_nudges_per_session)
    f = Freshness(ago(minutes=40), "progressUpdated")  # respondio, luego callo
    r = check(SessionState.IN_PROGRESS, f, nudge=n)
    assert r.verdict is Verdict.NUDGE_BUDGET_SPENT
    assert r.action is Action.ALERT


def test_sin_responder_tiene_precedencia_sobre_presupuesto_agotado():
    """Ambos veredictos alertan, pero no dicen lo mismo al arquitecto.

    "el nudge no obtuvo respuesta" apunta a que el prompt magico dejo de
    funcionar (riesgo 5); "se agoto el presupuesto" apunta a una sesion
    que se resiste. La primera es la mas accionable, y gana.
    """
    n = NudgeRecord(sent_at=ago(minutes=30), count=P.max_nudges_per_session)
    f = Freshness(ago(hours=1), "progressUpdated")  # nada tras el nudge
    assert check(SessionState.IN_PROGRESS, f, nudge=n).verdict is Verdict.NUDGE_UNANSWERED


# --------------------------------------------------------------------
# modos de autonomia (ADR-005)
# --------------------------------------------------------------------


def test_read_only_no_escribe_nunca():
    f = Freshness(ago(hours=1), "progressUpdated")
    r = check(SessionState.IN_PROGRESS, f, mode=AutonomyMode.READ_ONLY)
    assert r.verdict is Verdict.STALLED
    assert r.action is Action.ALERT
    assert r.downgraded_from is Action.NUDGE


def test_una_sesion_completada_no_dispara_ninguna_accion():
    """Que haya trabajo pendiente detrás no es asunto de Moon-Jules: la
    siguiente tarea la asigna una GitHub Action al fusionar el PR."""
    r = assess(
        sess(SessionState.COMPLETED),
        Freshness(ago(minutes=5), "sessionCompleted"),
        NOW,
        mode=AutonomyMode.UNBLOCK_ONLY,
    )
    assert r.action is Action.NONE
    assert not r.needs_attention


def test_full_auto_se_acepta_y_equivale_a_unblock_only():
    """Se admite en configs existentes, pero ya no significa nada extra."""
    assert AutonomyMode.parse("full_auto") is AutonomyMode.UNBLOCK_ONLY


def test_completada_sin_cola_no_hace_nada():
    r = assess(
        sess(SessionState.COMPLETED),
        Freshness(ago(minutes=5), "sessionCompleted"),
        NOW,
        mode=AutonomyMode.UNBLOCK_ONLY,
    )
    assert r.action is Action.NONE
    assert not r.needs_attention


# --------------------------------------------------------------------
# parsing: el API devuelve precision variable
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "2026-06-02T13:20:19.910909227Z",  # 9 digitos, visto en sessions
        "2026-06-02T13:22:47.696242Z",  # 6 digitos, visto en activities
        "2026-04-30T18:10:01.761Z",  # 3 digitos, visto en el enjambre
        "2026-06-02T13:20:19Z",
    ],
)
def test_timestamps_del_api_se_parsean(raw: str):
    assert parse_ts(raw) is not None


def test_estado_desconocido_no_tumba_el_loop():
    """El API esta en alpha: un estado nuevo no puede ser una excepcion."""
    assert SessionState.parse("ESTADO_DEL_FUTURO") is SessionState.UNSPECIFIED


def test_una_sesion_pausada_no_se_reporta_como_sana():
    """Encontrado en datos reales (entrega 13).

    La congelación del reloj se evaluaba antes que el estado, así que
    una sesión PAUSED cuyo último evento fue `sessionCompleted` salía
    etiquetada `healthy` — como si el agente trabajara bien en ella. El
    trabajo se entregó, sí, pero la sesión está pausada, y decir "sana"
    en un panel es engañoso.
    """
    r = check(SessionState.PAUSED, Freshness(ago(days=124), "sessionCompleted"))
    assert r.verdict is Verdict.PAUSED_DONE
    assert r.action is Action.NONE
    assert not r.needs_attention, "entregó el trabajo: informar, no alarmar"
    assert not r.is_problem


def test_una_sesion_en_curso_que_cerro_sigue_siendo_sana():
    """El caso para el que se escribió la invariante no cambia."""
    r = check(SessionState.IN_PROGRESS, Freshness(ago(hours=4), "sessionCompleted"))
    assert r.verdict is Verdict.HEALTHY


def test_una_pausada_muda_a_media_faena_sigue_alertando():
    r = check(SessionState.PAUSED, Freshness(ago(days=97), "progressUpdated"))
    assert r.verdict is Verdict.PAUSED_STALE
