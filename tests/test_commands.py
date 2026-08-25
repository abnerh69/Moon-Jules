"""Tests del canal de comandos. Épica E24.

RTDB no es una cola de mensajes. Tratarlo como si lo fuera produce tres
formas del mismo desastre —una orden ejecutada cuando ya no tocaba— y
cada una tiene aquí su test: reejecución tras un reinicio, órdenes
zombis escritas mientras todo dormía, y relevo a media orden.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from moon_jules.commands import (
    TTL_POR_DEFECTO_S,
    VERBOS,
    Command,
    EstadoComando,
    ejecutar,
)
from moon_jules.detector import Action, Finding, Report, Verdict
from moon_jules.models import Session, SessionState
from moon_jules.store import GLOBAL_SCOPE, Store

from .fakes import FakeJules

NOW = datetime(2026, 8, 24, 21, 0, tzinfo=UTC)
SES = "sessions/12713370538437788130"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def crudo(verb: str, /, **kw) -> dict:
    d = {
        "id": kw.pop("id", "c-001"),
        "verb": verb,
        "issued_at": iso(NOW - timedelta(seconds=5)),
        "expires_at": iso(NOW + timedelta(minutes=5)),
    }
    if kw:
        d["args"] = kw
    return d


def report_con(verdict=Verdict.STALLED) -> Report:
    s = Session(name=SES, state=SessionState.IN_PROGRESS,
                source="sources/github/Informatica-ASHware/CryptBot-V3",
                title="[E12] Health endpoints", create_time=NOW - timedelta(hours=3))
    return Report(at=NOW, findings=[Finding(s, verdict, Action.NUDGE, 3120.0, "muda")])


def corre(cmd_crudo, store, *, client=None, report=None, ahora=NOW):
    cmd = Command.from_rtdb(cmd_crudo)
    return asyncio.run(
        ejecutar(cmd, client=client or FakeJules([], {}), store=store,
                 report=report or report_con(), ahora=ahora)
    )


# --------------------------------------------------------------------
# trampa 1: órdenes zombis
# --------------------------------------------------------------------


def test_un_comando_caducado_no_se_ejecuta(tmp_path):
    """Escrito mientras las tres máquinas dormían, leído horas después.

    "Desatasca esta sesión" emitido a las nueve y ejecutado a las seis
    de la tarde está mal, aunque el mecanismo haya funcionado.
    """
    viejo = crudo("nudge", session="123")
    viejo["expires_at"] = iso(NOW - timedelta(hours=6))
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        r = corre(viejo, store, client=client)
    assert r.status == EstadoComando.EXPIRED
    assert client.sent == [], "una orden caducada no puede tocar Jules"


def test_sin_caducidad_conocida_se_considera_caducado(tmp_path):
    """No poder razonar sobre la frescura basta para no ejecutar."""
    huerfano = {"id": "c-x", "verb": "nudge", "args": {"session": "123"}}
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        r = corre(huerfano, store, client=client)
    assert r.status == EstadoComando.EXPIRED
    assert client.sent == []


def test_si_falta_la_caducidad_pero_hay_emision_se_deduce():
    cmd = Command.from_rtdb(
        {"id": "c", "verb": "refresh", "issued_at": iso(NOW)}, ttl_s=600
    )
    assert cmd.expires_at == NOW + timedelta(seconds=600)
    assert not cmd.caducado(NOW + timedelta(seconds=599))
    assert cmd.caducado(NOW + timedelta(seconds=601))


def test_el_ttl_por_defecto_es_corto():
    """Una orden de mando a distancia envejece mal."""
    assert TTL_POR_DEFECTO_S <= 900


# --------------------------------------------------------------------
# trampa 2: reejecución tras un reinicio
# --------------------------------------------------------------------


def test_el_resultado_se_guarda_para_no_repetir_la_accion(tmp_path):
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("nudge", session="12713370538437788130"), store)
        store.record_command("c-001", "nudge", r.status, r.message,
                             r.completed_at, NOW)
        guardado = store.command_result("c-001")
    assert guardado["status"] == EstadoComando.DONE
    assert guardado["id"] == "c-001"


def test_un_comando_desconocido_no_tiene_resultado_previo(tmp_path):
    with Store(tmp_path / "s.db") as store:
        assert store.command_result("c-jamas-visto") is None


def test_registrar_dos_veces_el_mismo_id_no_lo_duplica(tmp_path):
    with Store(tmp_path / "s.db") as store:
        store.record_command("c-1", "nudge", "done", "primero", iso(NOW), NOW)
        store.record_command("c-1", "nudge", "failed", "segundo", iso(NOW), NOW)
        assert store.command_result("c-1")["message"] == "primero"
        assert len(store.command_log()) == 1


# --------------------------------------------------------------------
# los verbos
# --------------------------------------------------------------------


def test_nudge_desatasca_y_queda_registrado(tmp_path):
    """El que de verdad se usará: ves una sesión atascada y actúas ahora."""
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("nudge", session="12713370538437788130"), store, client=client)
        assert store.last_nudge(SES) is not None
    assert r.status == EstadoComando.DONE
    assert client.sent == [(SES, "Completa la tarea")]
    assert "CryptBot-V3" in r.message


def test_approve_plan_aprueba(tmp_path):
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("approve_plan", session="12713370538437788130"), store,
                  client=client)
    assert r.status == EstadoComando.DONE
    assert client.approved == [SES]


def test_ack_silencia_el_veredicto_vigente(tmp_path):
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("ack", session="12713370538437788130"), store)
        assert store.is_acked(SES, Verdict.STALLED.value)
    assert r.status == EstadoComando.DONE


def test_unack_funciona_aunque_la_sesion_no_este_en_el_ciclo(tmp_path):
    """Retirar un silenciamiento debe poder hacerse siempre: si no, una
    sesión silenciada y ya desaparecida quedaría muda para siempre."""
    with Store(tmp_path / "s.db") as store:
        store.ack("sessions/vieja", "paused_stale", NOW)
        r = corre(crudo("unack", session="vieja"), store, report=Report(at=NOW))
    assert r.status == EstadoComando.DONE


def test_pause_y_resume_desde_el_movil(tmp_path):
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("pause", reason="viajando"), store)
        assert r.status == EstadoComando.DONE
        assert GLOBAL_SCOPE in store.active_pauses(NOW)
        corre(crudo("resume", id="c-002"), store)
        assert store.active_pauses(NOW) == {}


def test_pause_con_plazo_se_levanta_sola(tmp_path):
    with Store(tmp_path / "s.db") as store:
        corre(crudo("pause", **{"for": "2h"}), store)
        assert GLOBAL_SCOPE in store.active_pauses(NOW + timedelta(hours=1))
        assert store.active_pauses(NOW + timedelta(hours=3)) == {}


def test_refresh_pide_no_esperar_al_siguiente_ciclo(tmp_path):
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("refresh"), store)
    assert r.status == EstadoComando.DONE
    assert r.refrescar is True


# --------------------------------------------------------------------
# lo que no se acepta
# --------------------------------------------------------------------


@pytest.mark.parametrize("verbo", ["assign_next", "archive", "delete", "create_session"])
def test_los_verbos_de_la_no_list_no_existen(verbo: str, tmp_path):
    """Crear sesiones es trabajo de la GitHub Action; archivar y borrar
    son escrituras sobre el workspace del arquitecto."""
    assert verbo not in VERBOS
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo(verbo, session="123"), store)
    assert r.status == EstadoComando.REJECTED


def test_un_verbo_que_necesita_sesion_la_exige(tmp_path):
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("nudge"), store)
    assert r.status == EstadoComando.REJECTED
    assert "session" in r.message


def test_una_sesion_que_no_esta_en_el_ciclo_se_rechaza(tmp_path):
    """La app está viendo algo que ya no existe: mejor decirlo."""
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("nudge", session="fantasma"), store, client=client)
    assert r.status == EstadoComando.REJECTED
    assert "refresca" in r.message
    assert client.sent == []


def test_un_nodo_vacio_no_es_un_comando():
    assert Command.from_rtdb(None) is None
    assert Command.from_rtdb({}) is None
    assert Command.from_rtdb("basura") is None
    assert Command.from_rtdb({"verb": "nudge"}) is None, "sin id no hay idempotencia"


def test_un_fallo_del_api_no_tumba_el_bucle(tmp_path):
    """Que un comando falle no puede impedir seguir vigilando a Jules."""
    from moon_jules.errors import MoonJulesError

    class ClienteRoto(FakeJules):
        async def send_message(self, name, prompt):
            raise MoonJulesError("el API dijo que no")

    with Store(tmp_path / "s.db") as store:
        r = corre(crudo("nudge", session="12713370538437788130"), store,
                  client=ClienteRoto([], {}))
    assert r.status == EstadoComando.FAILED
    assert "el API dijo que no" in r.message


# --------------------------------------------------------------------
# semántica: mando a distancia, no autonomía
# --------------------------------------------------------------------


def test_un_comando_se_ejecuta_aunque_la_autonomia_este_pausada(tmp_path):
    """Los modos gobiernan lo que Moon-Jules decide por su cuenta.

    Si el arquitecto pausó y luego manda un nudge, claramente quiere el
    nudge.
    """
    client = FakeJules([], {})
    with Store(tmp_path / "s.db") as store:
        store.pause(GLOBAL_SCOPE, NOW, reason="viajando")
        r = corre(crudo("nudge", session="12713370538437788130"), store, client=client)
    assert r.status == EstadoComando.DONE
    assert client.sent, "un comando explícito no lo frena la pausa"
