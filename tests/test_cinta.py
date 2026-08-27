"""Tests de la cinta transportadora. Épica E54.

Cuando una sesión termina, el repositorio toma uno de tres caminos:
arranca otra sesión, la misma se reanuda para corregir, o no pasa nada.
Los tres se distinguen **sin tocar GitHub**: los dos primeros dejan una
sesión activa y el tercero no.

Los umbrales salen de medir 40 transiciones reales del enjambre:
mediana 3.8 min, p90 20 min, p95 35 min, máximo 53.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from moon_jules.detector import (
    Action,
    Finding,
    Freshness,
    Policy,
    Report,
    SourceVerdict,
    Verdict,
    assess,
    evaluar_fuentes,
)
from moon_jules.models import AutonomyMode, Session, SessionState

NOW = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
SRC = "sources/github/Informatica-ASHware/Strategies-Manager"
P = Policy()


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def ses(estado: SessionState, *, fin=None, abierta_desde=None, name="sessions/1"):
    return Session(
        name=name,
        state=estado,
        source=SRC,
        create_time=abierta_desde or ago(hours=2),
        last_agent_at=fin,
    )


def hallazgo(s: Session, verdict=Verdict.DONE, atencion=False) -> Finding:
    return Finding(
        s, verdict,
        Action.ALERT if atencion else Action.NONE,
        None, "x",
    )


def fuente() -> dict:
    return {
        "name": SRC,
        "githubRepo": {"owner": "Informatica-ASHware", "repo": "Strategies-Manager"},
    }


def evaluar(*hallazgos, sources=None, ahora=NOW, policy=P):
    return evaluar_fuentes(
        Report(at=ahora, findings=list(hallazgos), sources=sources or [fuente()]),
        ahora,
        policy,
    )


# --------------------------------------------------------------------
# los tres caminos
# --------------------------------------------------------------------


def test_camino_feliz_arranco_otra_sesion():
    """La Action fusionó, etiquetó el siguiente issue y Jules lo tomó."""
    vieja = hallazgo(ses(SessionState.COMPLETED, fin=ago(minutes=10)))
    nueva = hallazgo(
        ses(SessionState.IN_PROGRESS, abierta_desde=ago(minutes=6),
            name="sessions/2"),
        Verdict.HEALTHY,
    )
    h = evaluar(vieja, nueva)[0]
    assert h.verdict is SourceVerdict.MOVING
    assert not h.needs_attention


def test_camino_de_correccion_la_misma_sesion_sigue():
    """La auditoría encontró fallos y Jules corrige en la misma sesión."""
    h = evaluar(
        hallazgo(ses(SessionState.IN_PROGRESS, abierta_desde=ago(minutes=20)),
                 Verdict.HEALTHY)
    )[0]
    assert h.verdict is SourceVerdict.MOVING


def test_camino_fallido_no_paso_nada():
    """El caso que no se ve: algo terminó y la cinta se quedó quieta."""
    h = evaluar(hallazgo(ses(SessionState.COMPLETED, fin=ago(hours=3))))[0]
    assert h.verdict is SourceVerdict.BELT_STOPPED
    assert h.needs_attention
    assert h.parada_min is not None and h.parada_min > 45


# --------------------------------------------------------------------
# el umbral, medido
# --------------------------------------------------------------------


def test_una_transicion_normal_no_alarma():
    """El 92% de las transiciones reales ocurren en menos de 20 min."""
    h = evaluar(hallazgo(ses(SessionState.COMPLETED, fin=ago(minutes=18))))[0]
    assert h.verdict is SourceVerdict.MOVING


def test_la_transicion_mas_lenta_observada_tampoco():
    """El máximo medido fue 53 min... y ese sí alarma con el umbral de
    45. Es el precio de detectar en menos de una hora en vez de dos
    días, y está elegido a sabiendas."""
    a_los_40 = evaluar(hallazgo(ses(SessionState.COMPLETED, fin=ago(minutes=40))))[0]
    a_los_53 = evaluar(hallazgo(ses(SessionState.COMPLETED, fin=ago(minutes=53))))[0]
    assert a_los_40.verdict is SourceVerdict.MOVING
    assert a_los_53.verdict is SourceVerdict.BELT_STOPPED


def test_el_umbral_es_configurable():
    corto = Policy(belt_stopped_m=10)
    h = evaluar(hallazgo(ses(SessionState.COMPLETED, fin=ago(minutes=15))),
                policy=corto)[0]
    assert h.verdict is SourceVerdict.BELT_STOPPED


# --------------------------------------------------------------------
# no repetir lo que ya se está gritando
# --------------------------------------------------------------------


def test_si_una_sesion_ya_reclama_no_se_avisa_dos_veces():
    """Decir «la cinta no avanza» sobre un repositorio cuya sesión ya
    está gritando es repetir lo mismo con otras palabras."""
    rota = hallazgo(ses(SessionState.FAILED, fin=ago(hours=3)),
                    Verdict.FAILED, atencion=True)
    h = evaluar(rota)[0]
    assert h.verdict is SourceVerdict.MOVING
    assert not h.needs_attention


def test_pero_si_esta_silenciada_la_cinta_si_avisa():
    """Silenciar un hallazgo lo saca del radar; que el proyecto entero
    esté parado sigue siendo noticia."""
    silenciada = Finding(
        ses(SessionState.FAILED, fin=ago(hours=3)),
        Verdict.FAILED, Action.ALERT, None, "x", acked=True,
    )
    h = evaluar(silenciada)[0]
    assert h.verdict is SourceVerdict.BELT_STOPPED


# --------------------------------------------------------------------
# repositorios sin nada
# --------------------------------------------------------------------


def test_un_repositorio_sin_ninguna_sesion_se_distingue():
    """No es lo mismo que una cinta parada: aquí nunca hubo nada."""
    h = evaluar(sources=[fuente()])[0]
    assert h.verdict is SourceVerdict.IDLE
    assert not h.needs_attention


def test_sin_saber_cuando_termino_no_se_inventa_una_parada():
    sin_fecha = hallazgo(ses(SessionState.COMPLETED, fin=None))
    assert evaluar(sin_fecha) == []


# --------------------------------------------------------------------
# la sesión que lleva demasiado abierta
# --------------------------------------------------------------------


def test_una_sesion_viva_pero_muy_larga_merece_una_mirada():
    """Su reloj de silencio no lo detecta: cada `progressUpdated` lo
    reinicia. Puede haber terminado sin avisar, haber fallado sin
    avisar, o estar dando vueltas."""
    s = Session(name="sessions/l", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=5))
    r = assess(s, Freshness(ago(minutes=1), "progressUpdated"), NOW,
               mode=AutonomyMode.UNBLOCK_ONLY)
    assert r.verdict is Verdict.LONG_RUNNING
    assert r.needs_attention


def test_no_se_le_escribe_a_una_sesion_que_esta_trabajando():
    """Interrumpir a Jules a media faena no ayuda a nadie."""
    s = Session(name="sessions/l", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=5))
    r = assess(s, Freshness(ago(minutes=1), "progressUpdated"), NOW,
               mode=AutonomyMode.UNBLOCK_ONLY)
    assert r.action is Action.ALERT


def test_una_sesion_larga_pero_normal_no_alarma():
    """El 30% de las sesiones que terminan bien pasan de 45 min y el
    p90 esta en 102. Alertar ahi seria ruido, y el ruido es lo que hace
    que uno acabe ignorando las alertas."""
    for minutos in (30, 60, 100):
        s = Session(name="sessions/n", state=SessionState.IN_PROGRESS,
                    source=SRC, create_time=ago(minutes=minutos))
        r = assess(s, Freshness(ago(minutes=1), "progressUpdated"), NOW)
        assert r.verdict is Verdict.HEALTHY, f"{minutos} min no deberia alarmar"


def test_estar_muda_pesa_mas_que_estar_larga():
    """Si además lleva rato callada, eso es lo urgente."""
    s = Session(name="sessions/m", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=5))
    r = assess(s, Freshness(ago(minutes=40), "progressUpdated"), NOW)
    assert r.verdict is Verdict.STALLED
