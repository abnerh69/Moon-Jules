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
    # `last_nudge_at` y `last_nudge_outcome` no aparecen: sin nudges no
    # tienen valor, y una clave ausente significa "no aplica".
    esperados = {
        "id", "repo", "title", "state", "verdict", "reason", "acked",
        "needs_attention", "silence_s", "age_s", "started_at", "url", "nudges",
    }
    assert set(s) == esperados
    assert s["repo"] == "Informatica-ASHware/CryptBot-V3"
    assert s["silence_s"] == 3120
    assert s["age_s"] == 3 * 3600


def test_el_silencio_ausente_no_es_silencio_cero():
    """Encontrado en datos reales (entrega 19).

    Firebase omite los nulos, así que `silence_s` llega **ausente**
    cuando el reloj está congelado. Si la app hace `silence_s ?? 0`
    mostrará "muda hace 0 s" sobre trabajo ya entregado. Una clave que
    no está significa desconocida, nunca cero.
    """
    f = Finding(sess(SessionState.PAUSED), Verdict.PAUSED_DONE, Action.NONE, None,
                "pausada tras entregar el trabajo")
    s = snap(f)["sessions"][0]
    assert "silence_s" not in s
    assert s["age_s"] > 0, "la edad sí se conoce; son preguntas distintas"


def test_ninguna_clave_nula_sobrevive():
    """El contrato es uno solo para fichero y para RTDB."""

    def hay_nulos(v) -> bool:
        if isinstance(v, dict):
            return any(x is None or hay_nulos(x) for x in v.values())
        if isinstance(v, list):
            return any(hay_nulos(x) for x in v)
        return False

    assert not hay_nulos(snap(hallazgo(), nudges=None))


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
    """Sin pausa la clave no viaja; su ausencia es la respuesta."""
    assert "paused" not in snap()["swarm"]
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
    assert "reglas denegaron" in str(exc.value)


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


# --------------------------------------------------------------------
# resumen por repositorio
# --------------------------------------------------------------------


def fuente(owner="Informatica-ASHware", repo="CryptBot-V3") -> dict:
    return {
        "name": f"sources/github/{owner}/{repo}",
        "githubRepo": {"owner": owner, "repo": repo},
    }


def snap_con_sources(*hallazgos, sources=None, **kw) -> dict:
    return construir(
        Report(at=NOW, findings=list(hallazgos), sources=sources or []),
        ahora=NOW, instancia="la-dorada", intervalo_s=300,
        modo="unblock_only", max_activas=15, **kw,
    )


def test_un_repositorio_sin_sesiones_tambien_aparece():
    """Es información: un repo sin nada corriendo puede significar que
    la cadena de la GitHub Action se rompió."""
    s = snap_con_sources(sources=[fuente()])
    assert len(s["sources"]) == 1
    assert s["sources"][0]["repo"] == "Informatica-ASHware/CryptBot-V3"
    assert s["sources"][0]["sessions"] == 0
    assert "current" not in s["sources"][0], "sin nada que hacer, no hay actual"


def test_un_repositorio_que_va_bien_aparece_aunque_no_publique_sesiones():
    """`sessions[]` solo lleva lo problemático y lo activo. Sin el
    resumen por source, un repo cuyo trabajo va perfecto sería invisible
    para la vista por proyecto."""
    sano = Finding(sess(SessionState.IN_PROGRESS), Verdict.HEALTHY,
                   Action.NONE, 20.0, "activa")
    s = snap_con_sources(sano, sources=[fuente()])
    fila = s["sources"][0]
    assert fila["active"] == 1
    assert fila["attention"] == 0
    assert fila["current"]["state"] == "IN_PROGRESS"


def test_se_muestra_en_que_esta_trabajando_ahora():
    sano = Finding(sess(SessionState.IN_PROGRESS), Verdict.HEALTHY,
                   Action.NONE, 20.0, "activa")
    fila = snap_con_sources(sano, sources=[fuente()])["sources"][0]
    assert fila["current"]["title"] == "[E12-S04] Health endpoints"


def test_sin_nada_vivo_se_muestra_lo_que_requiere_atencion():
    """Lo siguiente que importa cuando no hay nada corriendo."""
    muerta = Finding(sess(SessionState.FAILED), Verdict.FAILED, Action.ALERT,
                     None, "sesion fallida")
    fila = snap_con_sources(muerta, sources=[fuente()])["sources"][0]
    assert fila["active"] == 0
    assert fila["attention"] == 1
    assert fila["current"]["verdict"] == "failed"


def test_lo_que_preocupa_va_primero():
    otra = fuente(repo="Job-Hunter-EU")
    sano = Finding(
        sess(SessionState.IN_PROGRESS, name="sessions/ok",
             source=otra["name"]),
        Verdict.HEALTHY, Action.NONE, 20.0, "activa",
    )
    s = snap_con_sources(hallazgo(), sano, sources=[fuente(), otra])
    assert s["sources"][0]["repo"].endswith("CryptBot-V3")


def test_un_source_desconocido_por_el_api_no_se_pierde():
    """Si una sesión apunta a un source que el listado no trajo, más
    vale mostrarlo con el nombre crudo que ocultarlo."""
    fila = snap_con_sources(hallazgo(), sources=[])["sources"][0]
    assert fila["repo"] == "Informatica-ASHware/CryptBot-V3"


def test_la_ultima_senal_del_repositorio_viaja():
    from datetime import timedelta as _td

    s = sess()
    s = s.with_details(agent_at=NOW - _td(hours=2))
    f = Finding(s, Verdict.STALLED, Action.NUDGE, 7200.0, "muda")
    fila = snap_con_sources(f, sources=[fuente()])["sources"][0]
    assert fila["last_signal_at"].startswith("2026-08-24T13:00")
