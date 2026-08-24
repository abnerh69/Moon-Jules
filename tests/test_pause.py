"""Tests del interruptor de autonomía. Épica E08, ADR-005.

Dos modos de fallo guían estos tests. El obvio: pausar y que aun así se
escriba. Y el que preocupa más: **olvidarse de reanudar** y creer que la
autonomía está encendida cuando lleva días apagada — que es la misma
clase de problema que motiva el proyecto entero, alguien convencido de
que algo avanza cuando está parado.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.cli import Monitor, parse_duracion, render
from moon_jules.config import Budgets, Config, SourceConfig
from moon_jules.detector import Policy
from moon_jules.models import Activity, AutonomyMode, Session, SessionState
from moon_jules.store import GLOBAL_SCOPE, Store

from .fakes import FakeJules

NOW = datetime.now(UTC)
SRC_A = "sources/github/acme/uno"
SRC_B = "sources/github/acme/dos"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def muda(name: str, source: str) -> tuple[Session, list[Activity]]:
    s = Session(name=name, state=SessionState.IN_PROGRESS, source=source,
                create_time=ago(hours=3))
    return s, [Activity("a", "progressUpdated", "agent", ago(hours=2))]


def config(tmp_path, mode=AutonomyMode.UNBLOCK_ONLY) -> Config:
    return Config(
        api_key="x", default_mode=mode, policy=Policy(), budgets=Budgets(),
        sources={
            SRC_A: SourceConfig(name=SRC_A, mode=mode),
            SRC_B: SourceConfig(name=SRC_B, mode=mode),
        },
        state_path=tmp_path / "state.db",
    )


def run(c):
    return asyncio.run(c)


# --------------------------------------------------------------------


def test_sin_pausa_la_autonomia_actua(tmp_path):
    """Control: si esto no escribe, el resto de los tests no prueban nada."""
    s, a = muda("sessions/1", SRC_A)
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        run(Monitor(client, cfg, store).cycle(execute=True))
    assert len(client.sent) == 1


def test_la_pausa_global_corta_toda_escritura(tmp_path):
    sa, aa = muda("sessions/1", SRC_A)
    sb, ab = muda("sessions/2", SRC_B)
    client = FakeJules([sa, sb], {sa.name: aa, sb.name: ab})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(GLOBAL_SCOPE, NOW, reason="revisando")
        report = run(Monitor(client, cfg, store).cycle(execute=True))
    assert client.sent == []
    assert len(report.attention) == 2  # sigue detectando y avisando
    assert report.paused[GLOBAL_SCOPE] == "revisando"


def test_la_pausa_por_source_no_afecta_a_los_demas(tmp_path):
    """Con 24 repos, un source que se porta mal no debe apagar el resto."""
    sa, aa = muda("sessions/1", SRC_A)
    sb, ab = muda("sessions/2", SRC_B)
    client = FakeJules([sa, sb], {sa.name: aa, sb.name: ab})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(SRC_A, NOW)
        run(Monitor(client, cfg, store).cycle(execute=True))
    assert [n for n, _ in client.sent] == ["sessions/2"]


def test_pausar_no_apaga_la_deteccion(tmp_path):
    """Pausar la autonomía no es dejar de mirar: sigue detectando y avisando."""
    s, a = muda("sessions/1", SRC_A)
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(GLOBAL_SCOPE, NOW)
        report = run(Monitor(FakeJules([s], {s.name: a}), cfg, store).cycle(execute=True))
    assert report.attention[0].reason.startswith("muda")


def test_resume_devuelve_la_autonomia(tmp_path):
    s, a = muda("sessions/1", SRC_A)
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(GLOBAL_SCOPE, NOW)
        run(Monitor(client, cfg, store).cycle(execute=True))
        assert client.sent == []
        assert store.resume(GLOBAL_SCOPE) == 1
        run(Monitor(client, cfg, store).cycle(execute=True))
    assert len(client.sent) == 1


def test_resume_de_algo_no_pausado_no_miente(tmp_path):
    with Store(tmp_path / "s.db") as store:
        assert store.resume(GLOBAL_SCOPE) == 0


# --------------------------------------------------------------------
# vencimiento: el modo de fallo que de verdad preocupa
# --------------------------------------------------------------------


def test_una_pausa_con_plazo_se_levanta_sola(tmp_path):
    s, a = muda("sessions/1", SRC_A)
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(GLOBAL_SCOPE, NOW, until=NOW + timedelta(hours=1))
        assert GLOBAL_SCOPE in store.active_pauses(NOW)
        # dos horas despues ya no rige
        assert store.active_pauses(NOW + timedelta(hours=2)) == {}
        run(Monitor(client, cfg, store).cycle(execute=True))
    assert len(client.sent) == 1


def test_la_pausa_vencida_se_retira_de_la_tabla(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.pause(GLOBAL_SCOPE, NOW, until=NOW - timedelta(minutes=1))
        store.active_pauses(NOW)
        assert store.db.execute("SELECT COUNT(*) c FROM pauses").fetchone()["c"] == 0


def test_la_pausa_indefinida_sobrevive_al_reinicio(tmp_path):
    """Se persiste a propósito: reiniciar `watch` no debe reactivar nada."""
    db = tmp_path / "state.db"
    with Store(db) as store:
        store.pause(GLOBAL_SCOPE, NOW, reason="incidente")
    with Store(db) as store:
        assert store.active_pauses(NOW)[GLOBAL_SCOPE]["reason"] == "incidente"


# --------------------------------------------------------------------
# visibilidad
# --------------------------------------------------------------------


def test_el_estado_pausado_grita_en_el_render(tmp_path):
    s, a = muda("sessions/1", SRC_A)
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(GLOBAL_SCOPE, NOW, reason="revisando")
        salida = render(run(Monitor(FakeJules([s], {s.name: a}), cfg, store).cycle()))
    assert "AUTONOMIA PAUSADA" in salida
    assert "revisando" in salida


def test_el_banner_nombra_los_sources_pausados(tmp_path):
    s, a = muda("sessions/1", SRC_A)
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        store.pause(SRC_A, NOW)
        salida = render(run(Monitor(FakeJules([s], {s.name: a}), cfg, store).cycle()))
    assert "acme/uno" in salida


def test_sin_pausa_no_hay_banner(tmp_path):
    s, a = muda("sessions/1", SRC_A)
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        salida = render(run(Monitor(FakeJules([s], {s.name: a}), cfg, store).cycle()))
    assert "PAUSADA" not in salida


# --------------------------------------------------------------------
# duraciones
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,segundos",
    [("30m", 1800), ("2h", 7200), ("1d", 86400), ("45s", 45), (" 3 H ", 10800)],
)
def test_duraciones_validas(texto: str, segundos: int):
    assert parse_duracion(texto).total_seconds() == segundos


@pytest.mark.parametrize("texto", ["2", "", "dos horas", "2 semanas", "-1h", "h"])
def test_duraciones_invalidas_explican_el_formato(texto: str):
    """Un número suelto es ambiguo: ¿minutos, horas? Se exige la unidad."""
    with pytest.raises(ValueError, match="30m, 2h, 1d"):
        parse_duracion(texto)
