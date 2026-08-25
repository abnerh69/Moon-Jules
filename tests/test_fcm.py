"""Tests de las notificaciones push. Épica E28.

RTDB en tiempo real solo despierta a la app en primer plano. Sin FCM,
"recibo una alerta" se queda en "veo la alerta cuando miro", que es
donde estaba el arquitecto antes de que existiera este proyecto.
"""

from __future__ import annotations

import httpx
import pytest

from moon_jules.detector import Action, Finding, Verdict
from moon_jules.fcm import MUERTOS, FcmBackend
from moon_jules.models import Session, SessionState
from moon_jules.notify import Notifier
from moon_jules.store import Store

from .test_publish import NOW, hallazgo


class AuthFalsa:
    project_id = "moon-jules"
    uid = "moonjules-writer"
    name = "service_account"

    def bearer_sync(self) -> str:
        return "ya29.token"


def backend(handler, tokens: list[str] | None = None) -> FcmBackend:
    b = FcmBackend(
        AuthFalsa(), "moon-jules",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    b.set_tokens(tokens if tokens is not None else ["tok-movil"])
    return b


def ok(_req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"name": "projects/moon-jules/messages/1"})


# --------------------------------------------------------------------
# el envío
# --------------------------------------------------------------------


def test_envia_al_proyecto_correcto_y_autenticado():
    vistas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return ok(req)

    assert backend(handler).send("Moon-Jules: CryptBot-V3", "muda 52 min") is True
    req = vistas[0]
    assert "projects/moon-jules/messages:send" in str(req.url)
    assert req.headers["Authorization"] == "Bearer ya29.token"


def test_el_mensaje_lleva_titulo_cuerpo_y_prioridad():
    import json

    vistas: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(json.loads(req.read()))
        return ok(req)

    backend(handler).send("titulo", "cuerpo")
    msg = vistas[0]["message"]
    assert msg["token"] == "tok-movil"
    assert msg["notification"] == {"title": "titulo", "body": "cuerpo"}
    assert msg["android"]["priority"] == "high", "una alerta no puede esperar a Doze"


def test_envia_a_todos_los_dispositivos():
    enviados: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        enviados.append(json.loads(req.read())["message"]["token"])
        return ok(req)

    backend(handler, ["movil", "tablet"]).send("t", "c")
    assert enviados == ["movil", "tablet"]


def test_sin_dispositivos_no_se_intenta_nada():
    def estalla(_req: httpx.Request) -> httpx.Response:
        raise AssertionError("no debería haber salido ninguna petición")

    assert backend(estalla, []).send("t", "c") is False


# --------------------------------------------------------------------
# tokens muertos
# --------------------------------------------------------------------


@pytest.mark.parametrize("codigo", MUERTOS)
def test_un_token_muerto_se_marca_para_retirar(codigo: str):
    """El teléfono se reinstaló. Sin limpieza, cada ciclo insistiría con
    un token que ya no existe, para siempre."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {
            "status": "NOT_FOUND",
            "details": [{"errorCode": codigo}],
        }})

    b = backend(handler)
    assert b.send("t", "c") is False
    assert b.retirados == ["tok-movil"]


def test_un_fallo_pasajero_no_retira_el_token():
    """Un 503 de FCM no significa que el teléfono haya desaparecido."""
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})

    b = backend(handler)
    assert b.send("t", "c") is False
    assert b.retirados == []


def test_un_dispositivo_muerto_no_impide_avisar_al_resto():
    def handler(req: httpx.Request) -> httpx.Response:
        import json

        if json.loads(req.read())["message"]["token"] == "muerto":
            return httpx.Response(404, json={"error": {
                "details": [{"errorCode": "UNREGISTERED"}]}})
        return ok(req)

    b = backend(handler, ["muerto", "vivo"])
    assert b.send("t", "c") is True
    assert b.retirados == ["muerto"]


def test_set_tokens_limpia_los_retirados_del_ciclo_anterior():
    b = backend(ok)
    b.retirados.append("viejo")
    b.set_tokens(["nuevo"])
    assert b.retirados == []


def test_un_fallo_de_red_no_tumba_el_envio():
    def cae(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin ruta")

    assert backend(cae).send("t", "c") is False


# --------------------------------------------------------------------
# integración con la supresión de repetidos
# --------------------------------------------------------------------


def test_no_repite_la_misma_alerta_en_cada_ciclo(tmp_path):
    """Una sesión colgada notificaría doce veces por hora y el arquitecto
    silenciaría la app, que es peor que no tenerla. La lógica de
    supresión no se reimplementa: es la del `Notifier`."""
    enviados: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        enviados.append(1)
        return ok(req)

    with Store(tmp_path / "s.db") as store:
        n = Notifier(store, enabled=True, cooldown_s=3600, backend=backend(handler))
        n.notify_findings([hallazgo()], NOW)
        n.notify_findings([hallazgo()], NOW)
    assert len(enviados) == 1


def test_el_titulo_nombra_el_repositorio(tmp_path):
    """En la pantalla de bloqueo hay sitio para una línea: que diga dónde."""
    vistas: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        vistas.append(json.loads(req.read())["message"]["notification"])
        return ok(req)

    with Store(tmp_path / "s.db") as store:
        Notifier(store, enabled=True, backend=backend(handler)).notify_findings(
            [hallazgo()], NOW
        )
    assert "CryptBot-V3" in vistas[0]["title"]


def test_lo_sano_no_notifica(tmp_path):
    def estalla(_req: httpx.Request) -> httpx.Response:
        raise AssertionError("una sesión sana no puede notificar")

    s = Session(name="sessions/ok", state=SessionState.IN_PROGRESS,
                source="sources/github/a/b", title="t")
    sano = Finding(s, Verdict.HEALTHY, Action.NONE, 20.0, "activa")
    with Store(tmp_path / "s.db") as store:
        assert Notifier(store, enabled=True, backend=backend(estalla)).notify_findings(
            [sano], NOW
        ) == 0


# --------------------------------------------------------------------
# las dos vías no son la misma cosa
# --------------------------------------------------------------------


def test_fcm_sin_enabled_es_error_de_arranque(tmp_path):
    """Contradicción silenciosa: con `enabled = false` el notificador
    está apagado entero y el push nunca saldría. Mejor no arrancar."""
    import os

    from moon_jules.config import ConfigError, load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_F"\n[notify]\nenabled = false\nfcm = true\n'
    )
    os.environ["MJ_F"] = "x"
    try:
        with pytest.raises(ConfigError, match="nunca saldria"):
            load(cfg)
    finally:
        del os.environ["MJ_F"]


def test_avisar_sin_ninguna_via_tampoco_tiene_sentido(tmp_path):
    import os

    from moon_jules.config import ConfigError, load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_F2"\n'
        "[notify]\nenabled = true\nlocal = false\nfcm = false\n"
    )
    os.environ["MJ_F2"] = "x"
    try:
        with pytest.raises(ConfigError, match="no hay por donde avisar"):
            load(cfg)
    finally:
        del os.environ["MJ_F2"]


def test_se_puede_avisar_al_movil_sin_molestar_al_portatil(tmp_path):
    """El caso que motiva separarlas: la máquina que vigila está en otro
    país y el aviso local no lo ve nadie."""
    import os

    from moon_jules.config import load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_F3"\n'
        "[notify]\nenabled = true\nlocal = false\nfcm = true\n"
        '[publish]\nenabled = true\ntarget = "rtdb"\n'
        '[publish.rtdb]\nurl = "https://x.firebaseio.com"\nauth = "env:MJ_T"\n'
    )
    os.environ.update({"MJ_F3": "x", "MJ_T": "t"})
    try:
        c = load(cfg)
        assert c.notify.fcm and not c.notify.local
    finally:
        for k in ("MJ_F3", "MJ_T"):
            del os.environ[k]
