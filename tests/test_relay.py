"""Tests del relevo entre instancias. Épica E21.

Tres portátiles en tres países y solo uno vigilando a la vez. El
teléfono elige cuál. La regla que gobierna todo el diseño es que eso sea
una **reclamación y no una asignación**: el teléfono propone, la
instancia elegida confirma, y la app puede ver ambas cosas.

Sin esa separación, escribir "ahora manda São Paulo" mostraría esa
máquina como vigilante aunque estuviera dormida y nadie hubiera recogido
el encargo — que es exactamente la clase de mentira con autoridad que
este proyecto existe para eliminar.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from moon_jules.cli import Monitor, leer_control
from moon_jules.config import (
    Budgets,
    Config,
    PublishConfig,
    RelayConfig,
    RtdbConfig,
    SourceConfig,
)
from moon_jules.detector import Policy
from moon_jules.models import Activity, AutonomyMode, Session, SessionState
from moon_jules.publish import Control, RtdbSink
from moon_jules.store import Store

from .fakes import FakeJules

NOW = datetime.now(UTC)
SRC = "sources/github/acme/repo"


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def run(c):
    return asyncio.run(c)


# --------------------------------------------------------------------
# quién manda
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "control,esperado",
    [
        (Control(desired="la-dorada"), "active"),
        (Control(desired="boston"), "standby"),
        (Control(desired=None), "standby"),
    ],
)
def test_el_papel_sale_de_quien_este_designado(control: Control, esperado: str):
    assert control.role_for("la-dorada", por_defecto_activo=False) == esperado


def test_sin_designacion_manda_lo_que_diga_el_config():
    sin = Control(desired=None)
    assert sin.role_for("x", por_defecto_activo=True) == "active"
    assert sin.role_for("x", por_defecto_activo=False) == "standby"


def test_si_el_control_no_se_puede_leer_nadie_actua():
    """Ante la duda, callar.

    El presupuesto de nudges es por sesión, no por máquina: si tres
    instancias actuaran a la vez lo agotarían en una sola pasada y la
    sesión recibiría el prompt triplicado.
    """
    ciego = Control(known=False)
    assert ciego.role_for("x", por_defecto_activo=True) == "standby"
    assert ciego.role_for("x", por_defecto_activo=False) == "standby"


# --------------------------------------------------------------------
# el efecto real: quién escribe
# --------------------------------------------------------------------


def config(tmp_path) -> Config:
    return Config(
        api_key="x",
        default_mode=AutonomyMode.UNBLOCK_ONLY,
        policy=Policy(),
        budgets=Budgets(),
        sources={SRC: SourceConfig(name=SRC, mode=AutonomyMode.UNBLOCK_ONLY)},
        state_path=tmp_path / "state.db",
    )


def sesion_muda() -> tuple[Session, list[Activity]]:
    s = Session(name="sessions/1", state=SessionState.IN_PROGRESS, source=SRC,
                create_time=ago(hours=3), update_time=NOW)
    return s, [Activity("a", "progressUpdated", "agent", ago(hours=2))]


def test_la_instancia_activa_actua(tmp_path):
    s, a = sesion_muda()
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        run(Monitor(client, cfg, store).cycle(execute=True, standby=False))
    assert len(client.sent) == 1


def test_la_instancia_en_reserva_vigila_pero_no_escribe(tmp_path):
    """Sigue detectando y publicando: su latido dice que está viva y
    disponible. Lo único que no hace es tocar Jules."""
    s, a = sesion_muda()
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        report = run(Monitor(client, cfg, store).cycle(execute=True, standby=True))
    assert client.sent == []
    assert len(report.attention) == 1, "la reserva deja de actuar, no de mirar"


def test_pasar_a_activa_devuelve_la_capacidad_de_actuar(tmp_path):
    s, a = sesion_muda()
    client = FakeJules([s], {s.name: a})
    cfg = config(tmp_path)
    with Store(cfg.state_path) as store:
        mon = Monitor(client, cfg, store)
        run(mon.cycle(execute=True, standby=True))
        assert client.sent == []
        run(mon.cycle(execute=True, standby=False))
    assert len(client.sent) == 1


# --------------------------------------------------------------------
# la reclamación
# --------------------------------------------------------------------


class RtdbFalso:
    """RTDB en memoria, con el mismo contrato REST que usa el sink."""

    def __init__(self, control: dict | None = None):
        self.datos: dict = {"control": dict(control or {})}
        self.escrituras: list[str] = []

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            ruta = req.url.path.removeprefix("/moonjules/").removesuffix(".json")
            if req.method == "GET":
                nodo: object = self.datos
                for parte in ruta.split("/"):
                    nodo = (nodo or {}).get(parte) if isinstance(nodo, dict) else None
                return httpx.Response(200, json=nodo)
            self.escrituras.append(ruta)
            partes = ruta.split("/")
            nodo = self.datos
            for parte in partes[:-1]:
                nodo = nodo.setdefault(parte, {})
            nodo[partes[-1]] = req.read() and __import__("json").loads(req.read())
            return httpx.Response(200, json={})

        return httpx.MockTransport(handler)

    def sink(self) -> RtdbSink:
        return RtdbSink(
            "https://x.firebaseio.com", "moonjules", "tok",
            client=httpx.AsyncClient(transport=self.transport()),
        )


def cfg_relevo(tmp_path, instancia: str, *, por_defecto=False) -> Config:
    c = config(tmp_path)
    return Config(
        api_key=c.api_key, default_mode=c.default_mode, policy=c.policy,
        budgets=c.budgets, sources=c.sources, state_path=c.state_path,
        publish=PublishConfig(
            enabled=True, target="rtdb", instance_id=instancia,
            rtdb=RtdbConfig(url="https://x.firebaseio.com", token="tok"),
        ),
        relay=RelayConfig(enabled=True, active_by_default=por_defecto),
    )


def test_la_designada_reclama_al_recoger_el_encargo(tmp_path):
    """La mitad que convierte una asignación en una reclamación."""
    db = RtdbFalso({"desired": "la-dorada"})
    sink = db.sink()
    control, rol = run(leer_control(cfg_relevo(tmp_path, "la-dorada"), sink))
    run(sink.aclose())
    assert rol == "active"
    assert control.claimed_by == "la-dorada"
    assert "control/claimed_by" in db.escrituras
    assert "control/claimed_at" in db.escrituras


def test_una_maquina_no_designada_no_reclama(tmp_path):
    db = RtdbFalso({"desired": "boston"})
    sink = db.sink()
    _, rol = run(leer_control(cfg_relevo(tmp_path, "la-dorada"), sink))
    run(sink.aclose())
    assert rol == "standby"
    assert db.escrituras == [], "una reserva no debe tocar el control"


def test_no_se_reclama_dos_veces(tmp_path):
    """Reclamar en cada ciclo sería ruido en RTDB sin información nueva."""
    db = RtdbFalso({"desired": "la-dorada", "claimed_by": "la-dorada"})
    sink = db.sink()
    _, rol = run(leer_control(cfg_relevo(tmp_path, "la-dorada"), sink))
    run(sink.aclose())
    assert rol == "active"
    assert db.escrituras == []


def test_una_designacion_sin_reclamar_se_distingue_de_una_recogida(tmp_path):
    """El caso que justifica todo el diseño: el teléfono designó São
    Paulo, pero ese portátil está dormido y nunca leyó el encargo."""
    db = RtdbFalso({"desired": "sao-paulo"})
    sink = db.sink()
    control, rol = run(leer_control(cfg_relevo(tmp_path, "la-dorada"), sink))
    run(sink.aclose())
    assert rol == "standby"
    assert control.desired == "sao-paulo"
    assert control.claimed_by is None, "nadie recogió: la app debe poder verlo"


def test_sin_relevo_configurado_esta_instancia_manda(tmp_path):
    """El caso de una sola máquina, que es el que había hasta ahora."""
    c = config(tmp_path)
    control, rol = run(leer_control(c, None))
    assert rol == "active"
    assert control.desired is None


def test_el_snapshot_lleva_el_papel_y_el_control():
    from moon_jules.detector import Report
    from moon_jules.publish import construir

    snap = construir(
        Report(at=NOW), ahora=NOW, instancia="la-dorada", intervalo_s=300,
        modo="unblock_only", max_activas=15,
        control=Control(desired="la-dorada", claimed_by="la-dorada",
                        claimed_at="2026-08-24T21:00:00Z"),
        role="active",
    )
    assert snap["instance"]["role"] == "active"
    assert snap["control"]["desired"] == "la-dorada"
    assert snap["control"]["claimed_by"] == "la-dorada"
    assert snap["control"]["known"] is True


def test_el_snapshot_avisa_cuando_no_pudo_leer_el_control():
    from moon_jules.detector import Report
    from moon_jules.publish import construir

    snap = construir(
        Report(at=NOW), ahora=NOW, instancia="x", intervalo_s=300,
        modo="read_only", max_activas=15,
        control=Control(known=False), role="standby",
    )
    assert snap["control"]["known"] is False
    assert snap["instance"]["role"] == "standby"


def test_el_relevo_exige_un_punto_de_encuentro(tmp_path):
    """Sin RTDB no hay dónde acordar nada: es error de arranque."""
    from moon_jules.config import ConfigError, load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_R"\n'
        '[publish]\nenabled = true\ntarget = "file"\n'
        '[relay]\nenabled = true\n'
    )
    import os

    os.environ["MJ_R"] = "x"
    try:
        with pytest.raises(ConfigError, match="punto de encuentro"):
            load(cfg)
    finally:
        del os.environ["MJ_R"]
