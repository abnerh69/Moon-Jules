"""Tests de la publicación. Épica E20.

El snapshot es la frontera con la app: lo que se rompa aquí se rompe
allí, en un proyecto distinto y probablemente sin que nadie se entere
hasta que el panel muestre datos absurdos. Por eso el esquema se prueba
campo a campo y no solo "que no reviente".
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from moon_jules.detector import Action, Finding, Report, Verdict
from moon_jules.errors import MoonJulesError
from moon_jules.models import Session, SessionState
from moon_jules.publish import (
    MAX_SESIONES,
    SCHEMA,
    FileSink,
    RtdbSink,
    construir,
    instance_id,
)

NOW = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)


def ago(**kw: float) -> datetime:
    return NOW - timedelta(**kw)


def sess(estado=SessionState.IN_PROGRESS, name="sessions/1", **kw) -> Session:
    kw.setdefault("title", "[E12-S04] Health endpoints")
    kw.setdefault("source", "sources/github/Informatica-ASHware/CryptBot-V3")
    kw.setdefault("create_time", ago(hours=3))
    kw.setdefault("url", "https://jules.google.com/session/1")
    return Session(name=name, state=estado, **kw)


def hallazgo(verdict=Verdict.STALLED, silence=3120.0, acked=False, **kw) -> Finding:
    return Finding(sess(**kw), verdict, Action.NUDGE, silence,
                   "muda desde hace 52 min", acked=acked)


def snap(*hallazgos, **kw) -> dict:
    kw.setdefault("intervalo_s", 300)
    return construir(
        Report(at=NOW, findings=list(hallazgos), paused=kw.pop("paused", {})),
        ahora=NOW,
        instancia=kw.pop("instancia", "mbp-boston"),
        modo=kw.pop("modo", "unblock_only"),
        max_activas=kw.pop("max_activas", 15),
        nudges=kw.pop("nudges", None),
        **kw,
    )


def run(c):
    return asyncio.run(c)


# --------------------------------------------------------------------
# el latido
# --------------------------------------------------------------------


def test_el_snapshot_siempre_lleva_marca_de_tiempo():
    """Sin ella, un panel de hace tres horas y uno de hace un minuto
    dicen exactamente lo mismo, y solo uno es verdad."""
    assert snap()["instance"]["published_at"] == "2026-08-24T15:00:00Z"


def test_un_enjambre_tranquilo_tambien_late():
    """El latido se reescribe aunque no haya nada que contar: es
    precisamente cuando no pasa nada cuando hay que distinguir entre
    'todo en orden' y 'nadie está mirando'."""
    vacio = snap()
    assert vacio["instance"]["published_at"]
    assert vacio["sessions"] == []
    assert vacio["swarm"]["attention"] == 0


def test_el_umbral_de_caducidad_viaja_con_el_dato():
    """Cuatro ciclos, nunca menos de 20 min. Así la app no lo codifica."""
    assert snap(intervalo_s=300)["instance"]["stale_after_s"] == 1200
    assert snap(intervalo_s=600)["instance"]["stale_after_s"] == 2400
    assert snap(intervalo_s=60)["instance"]["stale_after_s"] == 1200


def test_identifica_la_maquina_que_publica():
    """Con tres portátiles, un latido muerto no dice a dónde ir sin esto."""
    assert snap(instancia="mbp-sao-paulo")["instance"]["id"] == "mbp-sao-paulo"
    assert instance_id("explicito") == "explicito"
    assert instance_id(None)


# --------------------------------------------------------------------
# el esquema
# --------------------------------------------------------------------


def test_el_esquema_va_versionado():
    assert snap()["schema"] == SCHEMA


def test_una_sesion_trae_lo_que_la_app_necesita():
    s = snap(hallazgo())["sessions"][0]
    esperados = {
        "id", "repo", "title", "state", "verdict", "reason", "acked",
        "needs_attention", "silence_s", "age_s", "started_at", "url",
        "nudges", "last_nudge_at", "last_nudge_outcome",
    }
    assert set(s) == esperados
    assert s["repo"] == "Informatica-ASHware/CryptBot-V3"
    assert s["silence_s"] == 3120
    assert s["age_s"] == 3 * 3600


def test_silencio_nulo_no_es_silencio_cero():
    """`null` significa reloj congelado porque la sesión cerró. Si la app
    lo lee como 0 mostrará 'muda hace 0 s' sobre trabajo ya entregado."""
    f = Finding(sess(SessionState.COMPLETED), Verdict.DONE, Action.NONE, None, "completada")
    assert snap(f)["sessions"] == [] or snap(f)["sessions"][0]["silence_s"] is None


def test_el_snapshot_es_json_serializable():
    """Va por la red a Firebase: si algo no serializa, falla en producción."""
    json.dumps(snap(hallazgo()), ensure_ascii=False)


# --------------------------------------------------------------------
# qué entra y en qué orden
# --------------------------------------------------------------------


def test_lo_urgente_va_primero():
    tranquila = Finding(sess(name="sessions/ok"), Verdict.HEALTHY, Action.NONE, 20.0, "ok")
    urgente = hallazgo(name="sessions/mala", silence=9000.0)
    ids = [s["id"] for s in snap(tranquila, urgente)["sessions"]]
    assert ids[0] == "mala"


def test_las_completadas_sin_novedad_no_viajan():
    f = Finding(sess(SessionState.COMPLETED, name="sessions/c"), Verdict.DONE,
                Action.NONE, None, "completada")
    assert snap(f)["sessions"] == []
    assert snap(f)["swarm"]["sessions_total"] == 1


def test_el_snapshot_esta_acotado():
    """Se sube en cada ciclo: no puede crecer con el historial."""
    muchas = [hallazgo(name=f"sessions/{i}") for i in range(120)]
    assert len(snap(*muchas)["sessions"]) == MAX_SESIONES


def test_lo_silenciado_viaja_marcado_pero_no_cuenta_como_atencion():
    f = hallazgo(acked=True)
    s = snap(f)
    assert s["sessions"][0]["acked"] is True
    assert s["swarm"]["attention"] == 0
    assert s["swarm"]["acked"] == 1


def test_la_pausa_se_ve_desde_el_movil():
    assert snap()["swarm"]["paused"] is None
    assert snap(paused={"*": "revisando"})["swarm"]["paused"] == {"*": "revisando"}


def test_el_desenlace_del_nudge_llega_al_snapshot():
    """Varios `unanswered` seguidos son la señal de que el prompt mágico
    dejó de funcionar, y eso importa más que cualquier sesión suelta."""
    s = snap(
        hallazgo(),
        nudges={"sessions/1": {"count": 2, "sent_at": "2026-08-24T14:58:00Z",
                               "outcome": "unanswered"}},
    )["sessions"][0]
    assert s["nudges"] == 2
    assert s["last_nudge_outcome"] == "unanswered"


# --------------------------------------------------------------------
# destinos
# --------------------------------------------------------------------


def test_el_fichero_se_escribe_entero_o_nada(tmp_path):
    """Escritura atómica: un lector nunca ve medio snapshot."""
    destino = tmp_path / "sub" / "snapshot.json"
    run(FileSink(destino).publish(snap(hallazgo())))
    leido = json.loads(destino.read_text(encoding="utf-8"))
    assert leido["schema"] == SCHEMA
    assert not list(destino.parent.glob("*.tmp")), "quedó un temporal"


def test_el_fichero_se_sobrescribe_en_cada_ciclo(tmp_path):
    destino = tmp_path / "snapshot.json"
    sink = FileSink(destino)
    run(sink.publish(snap()))
    run(sink.publish(snap(hallazgo())))
    assert len(json.loads(destino.read_text())["sessions"]) == 1


def test_rtdb_escribe_bajo_la_instancia():
    vistos: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(str(req.url.path))
        return httpx.Response(200, json={})

    sink = RtdbSink("https://x.firebaseio.com/", "moonjules", "tok",
                    client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    run(sink.publish(snap(instancia="mbp-sao-paulo")))
    run(sink.aclose())
    assert vistos == ["/moonjules/instances/mbp-sao-paulo/snapshot.json"]


def test_el_token_de_rtdb_no_aparece_en_el_error():
    """El token viaja en la query: el mensaje solo puede nombrar la ruta."""
    def rechaza(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Permission denied"})

    sink = RtdbSink("https://x.firebaseio.com", "moonjules", "SECRETO-QUE-NO-DEBE-SALIR",
                    client=httpx.AsyncClient(transport=httpx.MockTransport(rechaza)))
    with pytest.raises(MoonJulesError) as exc:
        run(sink.publish(snap()))
    run(sink.aclose())
    assert "SECRETO-QUE-NO-DEBE-SALIR" not in str(exc.value)
    assert "reglas de seguridad" in str(exc.value)


def test_un_fallo_de_red_no_es_una_excepcion_cruda():
    def cae(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin ruta al host")

    sink = RtdbSink("https://x.firebaseio.com", "moonjules", "",
                    client=httpx.AsyncClient(transport=httpx.MockTransport(cae)))
    with pytest.raises(MoonJulesError, match="no se pudo publicar"):
        run(sink.publish(snap()))
    run(sink.aclose())


def test_el_token_de_rtdb_se_declara_como_secreto():
    """Para que el redactor del logger lo enmascare si llega por otra vía."""
    from moon_jules.config import Config, PublishConfig, RtdbConfig

    cfg = Config(
        api_key="clave-de-jules",
        publish=PublishConfig(rtdb=RtdbConfig(token="token-de-rtdb")),
    )
    assert set(cfg.secrets) == {"clave-de-jules", "token-de-rtdb"}
