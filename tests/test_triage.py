"""Tests de triaje e historial. Épicas E05 y E13.

El caso que motiva esta épica es real y está medido: el enjambre tiene
25 sesiones muertas, la más antigua de hace 100 días. Sin triaje,
`watch` alertaría de las 25 en cada ciclo para siempre y el ruido
enterraría cualquier señal nueva — la herramienta sería inservible el
primer día.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.cli import Monitor, render
from moon_jules.config import Budgets, Config, SourceConfig
from moon_jules.detector import Policy, Verdict
from moon_jules.models import Activity, AutonomyMode, Session, SessionState
from moon_jules.store import Store

NOW = datetime.now(UTC)
SRC = "sources/github/acme/repo"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def act(kind: str, who: str, when: datetime) -> Activity:
    return Activity(f"a/{kind}/{when.timestamp()}", kind, who, when)


class FakeClient:
    def __init__(self, sessions, activities):
        self._s, self._a = sessions, activities
        self.sent: list[tuple[str, str]] = []

    async def sessions(self, *, include_archived: bool = False):
        return list(self._s)

    async def activities(self, name, *, after=None, limit=None):
        return sorted(self._a.get(name, []), key=lambda a: a.create_time)

    async def send_message(self, name, prompt):
        self.sent.append((name, prompt))

    async def approve_plan(self, name):
        pass


def config(tmp_path, mode=AutonomyMode.READ_ONLY) -> Config:
    return Config(
        api_key="x",
        default_mode=mode,
        policy=Policy(),
        budgets=Budgets(),
        sources={SRC: SourceConfig(name=SRC, mode=mode)},
        state_path=tmp_path / "state.db",
    )


def sess(state, name, **kw) -> Session:
    return Session(name=name, state=state, source=SRC,
                   create_time=ago(days=100), **kw)


def run(c):
    return asyncio.run(c)


# --------------------------------------------------------------------
# triaje
# --------------------------------------------------------------------


def test_lo_silenciado_sale_del_radar_pero_sigue_estando_mal(tmp_path):
    s = sess(SessionState.PAUSED, "sessions/muerta", update_time=ago(days=97))
    client = FakeClient([s], {s.name: [act("progressUpdated", "agent", ago(days=97))]})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        mon = Monitor(client, cfg, store)
        antes = run(mon.cycle())
        assert len(antes.attention) == 1

        store.ack(s.name, Verdict.PAUSED_STALE.value, NOW, "deuda historica")
        despues = run(mon.cycle())

    assert despues.attention == []          # fuera del radar
    assert len(despues.problems) == 1        # pero el problema sigue ahi
    assert despues.acked[0].acked is True


def test_un_veredicto_nuevo_reaparece_aunque_la_sesion_este_silenciada(tmp_path):
    """El triaje silencia un hallazgo concreto, no una sesión entera.

    Si una sesión pasa de PAUSED_STALE a FAILED, eso es información
    nueva y tiene que volver a aparecer.
    """
    s = sess(SessionState.PAUSED, "sessions/x", update_time=ago(days=90))
    acts = {s.name: [act("progressUpdated", "agent", ago(days=90))]}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.ack(s.name, Verdict.PAUSED_STALE.value, NOW)
        assert run(Monitor(FakeClient([s], acts), cfg, store).cycle()).attention == []

        empeorada = Session(name=s.name, state=SessionState.FAILED, source=SRC,
                            update_time=ago(minutes=5))
        peor = run(Monitor(FakeClient([empeorada], {}), cfg, store).cycle())
    assert len(peor.attention) == 1
    assert peor.attention[0].verdict is Verdict.FAILED


def test_unack_devuelve_la_sesion_al_radar(tmp_path):
    s = sess(SessionState.PAUSED, "sessions/y", update_time=ago(days=50))
    acts = {s.name: [act("progressUpdated", "agent", ago(days=50))]}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.ack(s.name, Verdict.PAUSED_STALE.value, NOW)
        assert run(Monitor(FakeClient([s], acts), cfg, store).cycle()).attention == []
        assert store.unack(s.name) == 1
        assert len(run(Monitor(FakeClient([s], acts), cfg, store).cycle()).attention) == 1


def test_la_deuda_historica_no_tapa_un_problema_nuevo(tmp_path):
    """El escenario completo: 25 corpses silenciados, uno nuevo visible."""
    viejas = [
        sess(SessionState.PAUSED, f"sessions/vieja{i}", update_time=ago(days=90))
        for i in range(25)
    ]
    nueva = Session(name="sessions/nueva", state=SessionState.IN_PROGRESS,
                    source=SRC, create_time=ago(hours=2), update_time=ago(minutes=1))
    acts = {v.name: [act("progressUpdated", "agent", ago(days=90))] for v in viejas}
    acts[nueva.name] = [act("progressUpdated", "agent", ago(hours=1))]
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        mon = Monitor(FakeClient([*viejas, nueva], acts), cfg, store)
        antes = run(mon.cycle())
        assert len(antes.attention) == 26

        for v in viejas:
            store.ack(v.name, Verdict.PAUSED_STALE.value, NOW, "deuda historica")
        despues = run(mon.cycle())

    assert len(despues.attention) == 1
    assert despues.attention[0].session.name == "sessions/nueva"
    assert len(despues.acked) == 25


def test_el_render_marca_lo_silenciado(tmp_path):
    s = sess(SessionState.PAUSED, "sessions/z", update_time=ago(days=80))
    acts = {s.name: [act("progressUpdated", "agent", ago(days=80))]}
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.ack(s.name, Verdict.PAUSED_STALE.value, NOW)
        salida = render(run(Monitor(FakeClient([s], acts), cfg, store).cycle()))
    assert "~~" in salida
    assert "1 silenciadas" in salida


# --------------------------------------------------------------------
# cierre del registro de nudges (E05)
# --------------------------------------------------------------------


def test_un_nudge_respondido_se_registra_como_respondido(tmp_path):
    """Sin esto los nudges se quedaban en 'pending' para siempre.

    Y sin ese dato, `history` no puede decir si el prompt mágico sigue
    funcionando — que es justo el canario del riesgo 5.
    """
    s = Session(name="sessions/n", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=3))
    mudo = {s.name: [act("progressUpdated", "agent", ago(hours=2))]}
    cfg = config(tmp_path, AutonomyMode.UNBLOCK_ONLY)
    with Store(cfg.state_path) as store:
        run(Monitor(FakeClient([s], mudo), cfg, store).cycle(execute=True))
        assert store.nudge_stats()["pending"] == 1

        # El evento del agente tiene que ser posterior al nudge, y el
        # nudge se envia en el instante real del ciclo, no en NOW (que
        # se fija al importar el modulo).
        revivido = {
            s.name: [*mudo[s.name], act("progressUpdated", "agent", NOW + timedelta(minutes=1))]
        }
        run(Monitor(FakeClient([s], revivido), cfg, store).cycle(execute=True))
        st = store.nudge_stats()
    assert st["answered"] == 1
    assert st["pending"] == 0


def test_un_nudge_ignorado_se_registra_como_sin_respuesta(tmp_path):
    s = Session(name="sessions/m", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=3))
    mudo = {s.name: [act("progressUpdated", "agent", ago(hours=2))]}
    cfg = Config(
        api_key="x", default_mode=AutonomyMode.UNBLOCK_ONLY,
        # ventana de verificacion 0: el segundo ciclo ya la considera vencida
        policy=Policy(nudge_verify_s=0), budgets=Budgets(),
        sources={SRC: SourceConfig(name=SRC, mode=AutonomyMode.UNBLOCK_ONLY,
                                   policy=Policy(nudge_verify_s=0))},
        state_path=tmp_path / "state.db",
    )
    with Store(cfg.state_path) as store:
        mon = Monitor(FakeClient([s], mudo), cfg, store)
        run(mon.cycle(execute=True))
        run(mon.cycle(execute=True))
        st = store.nudge_stats()
    assert st["unanswered"] == 1


def test_la_recuperacion_mediana_se_calcula(tmp_path):
    with Store(tmp_path / "s.db") as store:
        for i, mins in enumerate((1, 5, 9)):
            store.record_nudge(f"sessions/{i}", "Completa la tarea", NOW)
            store.resolve_nudge(f"sessions/{i}", "answered", NOW + timedelta(minutes=mins))
        assert store.nudge_stats()["median_recovery_s"] == pytest.approx(300, abs=1)


def test_historial_vacio_no_revienta(tmp_path):
    with Store(tmp_path / "s.db") as store:
        st = store.nudge_stats()
    assert st["total"] == 0
    assert st["median_recovery_s"] is None


def test_el_ack_sobrevive_al_reinicio(tmp_path):
    """El triaje vive en SQLite: reiniciar `watch` no lo pierde."""
    db = tmp_path / "state.db"
    with Store(db) as store:
        store.ack("sessions/a", "paused_stale", NOW, "vieja")
    with Store(db) as store:
        assert store.is_acked("sessions/a", "paused_stale")
        assert len(store.list_acks()) == 1


# --------------------------------------------------------------------
# presentación
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "segundos,esperado",
    [
        (None, "-"),
        (25, "0m"),
        (50 * 60, "50m"),
        (3 * 3600, "3h"),
        (95 * 24 * 3600, "95d"),
    ],
)
def test_las_duraciones_se_leen(segundos, esperado):
    """Una sesión muerta hace 95 días no se reporta como `136800m`."""
    from moon_jules.cli import humano

    assert humano(segundos).strip() == esperado
