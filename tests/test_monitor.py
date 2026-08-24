"""Tests del ciclo de vigilancia completo.

Usan un cliente falso en vez del mock HTTP: el objetivo es el cableado
—cursor, persistencia, ejecucion de acciones, presupuesto de nudges—,
no el transporte, que ya cubre el cliente.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.cli import Monitor
from moon_jules.config import Budgets, Config, SourceConfig
from moon_jules.detector import Action, Policy, Verdict
from moon_jules.models import Activity, AutonomyMode, Session, SessionState
from moon_jules.store import Store

from .fakes import FakeJules

NOW = datetime.now(UTC)
SRC = "sources/github/acme/repo"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def act(kind: str, who: str, when: datetime, text: str | None = None) -> Activity:
    return Activity(f"a/{kind}/{when.timestamp()}", kind, who, when, text=text)


def config(mode: AutonomyMode, tmp_path, **policy_kw) -> Config:
    pol = Policy(**policy_kw) if policy_kw else Policy()
    return Config(
        api_key="x",
        default_mode=mode,
        policy=pol,
        budgets=Budgets(),
        sources={SRC: SourceConfig(name=SRC, mode=mode, policy=pol)},
        state_path=tmp_path / "state.db",
    )


def sess(state: SessionState, name="sessions/1", **kw) -> Session:
    kw.setdefault("update_time", ago(minutes=1))
    return Session(name=name, state=state, source=SRC,
                   create_time=kw.pop("create_time", ago(hours=1)), **kw)


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------


def test_ciclo_detecta_estancamiento_y_envia_nudge(tmp_path):
    s = sess(SessionState.IN_PROGRESS, title="tarea larga")
    client = FakeJules([s], {s.name: [act("progressUpdated", "agent", ago(minutes=40))]})
    cfg = config(AutonomyMode.UNBLOCK_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle(execute=True))
        assert report.findings[0].verdict is Verdict.STALLED
        assert client.sent == [(s.name, "Completa la tarea")]
        assert store.last_nudge(s.name).count == 1


def test_read_only_no_escribe_aunque_detecte(tmp_path):
    s = sess(SessionState.IN_PROGRESS)
    client = FakeJules([s], {s.name: [act("progressUpdated", "agent", ago(hours=3))]})
    cfg = config(AutonomyMode.READ_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle(execute=True))
        assert report.findings[0].verdict is Verdict.STALLED
        assert report.findings[0].action is Action.ALERT
        assert client.sent == []


def test_el_nudge_no_reinicia_su_propio_reloj(tmp_path):
    """El fallo mas insidioso posible: el monitor engañandose a si mismo.

    Tras el nudge, la unica actividad nueva es la nuestra. La sesion debe
    seguir considerandose muda, no rejuvenecida.
    """
    s = sess(SessionState.IN_PROGRESS)
    acts = [
        act("progressUpdated", "agent", ago(hours=2)),
        act("userMessaged", "user", ago(minutes=1)),  # nuestro nudge
    ]
    client = FakeJules([s], {s.name: acts})
    cfg = config(AutonomyMode.READ_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle(execute=False))
        assert report.findings[0].silence_s == pytest.approx(7200, abs=60)


def test_segundo_ciclo_usa_el_cursor(tmp_path):
    """La segunda pasada pide solo lo nuevo (ADR-001).

    La primera tampoco pide la historia entera: arranca en una ventana
    reciente. Lo que se comprueba es que el cursor avanza.
    """
    s = sess(SessionState.IN_PROGRESS)
    a = act("progressUpdated", "agent", ago(minutes=2))
    client = FakeJules([s], {s.name: [a]})
    cfg = config(AutonomyMode.READ_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        run(mon.cycle())
    primera, segunda = client.activity_calls[0][1], client.activity_calls[1][1]
    assert primera is not None, "la primera vista debe acotarse, no pedirlo todo"
    assert segunda > primera, "el cursor no avanzo"


def test_frescura_sobrevive_al_cursor_vacio(tmp_path):
    """Si el cursor ya consumio todo, la frescura sale del store.

    Sin esto, la segunda pasada veria cero actividades del agente y
    perderia el reloj justo cuando mas importa.
    """
    s = sess(SessionState.IN_PROGRESS)
    client = FakeJules([s], {s.name: [act("progressUpdated", "agent", ago(minutes=30))]})
    cfg = config(AutonomyMode.READ_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        mon = Monitor(client, cfg, store)
        run(mon.cycle())
        segundo = run(mon.cycle())
    assert segundo.findings[0].silence_s == pytest.approx(1800, abs=60)
    assert segundo.findings[0].verdict is Verdict.STALLED


def test_sesiones_terminales_no_gastan_requests(tmp_path):
    """Sobre COMPLETED el reloj estaria congelado igual: no se consultan."""
    s = sess(SessionState.COMPLETED, update_time=ago(minutes=5))
    client = FakeJules([s], {})
    cfg = config(AutonomyMode.FULL_AUTO, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle())
    assert client.activity_calls == []
    assert report.findings[0].verdict is Verdict.DONE


def test_failed_recupera_la_razon_y_no_recibe_escritura(tmp_path):
    s = sess(SessionState.FAILED, update_time=ago(minutes=5))
    client = FakeJules(
        [s],
        {s.name: [act("sessionFailed", "agent", ago(minutes=5), "Unable to install deps")]},
    )
    cfg = config(AutonomyMode.FULL_AUTO, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle(execute=True))
    assert "Unable to install deps" in report.findings[0].reason
    assert client.sent == []


def test_presupuesto_de_nudges_frena_la_insistencia(tmp_path):
    s = sess(SessionState.IN_PROGRESS)
    client = FakeJules([s], {s.name: [act("progressUpdated", "agent", ago(hours=5))]})
    cfg = config(AutonomyMode.UNBLOCK_ONLY, tmp_path, nudge_verify_s=1)
    with Store(cfg.state_path) as store:
        mon = Monitor(client, cfg, store)
        run(mon.cycle(execute=True))          # nudge 1
        for _ in range(4):
            run(mon.cycle(execute=True))      # el resto no debe insistir sin fin
    # tras el primer nudge sin respuesta se escala a alerta, no se repite
    assert len(client.sent) == 1


def test_multiples_sesiones_se_ordenan_por_atencion(tmp_path):
    sana = sess(SessionState.IN_PROGRESS, name="sessions/ok")
    mala = sess(SessionState.PAUSED, name="sessions/bad", update_time=ago(days=90))
    client = FakeJules(
        [sana, mala],
        {
            sana.name: [act("progressUpdated", "agent", ago(seconds=20))],
            mala.name: [act("progressUpdated", "agent", ago(days=90))],
        },
    )
    cfg = config(AutonomyMode.READ_ONLY, tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle())
    assert len(report.attention) == 1
    assert report.attention[0].verdict is Verdict.PAUSED_STALE
