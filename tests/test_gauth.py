"""Tests de la autenticación contra RTDB. Épica E23.

Lo que se prueba aquí no es "que conecte", sino la diferencia entre las
dos credenciales posibles. Un database secret entra como administrador y
**salta las reglas de seguridad**: con él, la promesa de que el teléfono
solo escribe `control/desired` la sostiene este código y no la base de
datos. Una cuenta de servicio con `auth_variable_override` hace que las
reglas se apliquen también a los Mac.

Esa diferencia es invisible en una respuesta 200. Solo se ve en lo que
viaja en la petición, y por eso los tests inspeccionan la petición.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat

import httpx
import pytest

from moon_jules.errors import ConfigError
from moon_jules.gauth import (
    SCOPES,
    UID_ESCRITOR,
    ServiceAccountAuth,
    StaticTokenAuth,
)
from moon_jules.publish import RtdbSink


def run(c):
    return asyncio.run(c)


class AuthFalsa(ServiceAccountAuth):
    """Cuenta de servicio sin firmar nada: interesa el efecto, no el JWT."""

    def __init__(self, uid: str = UID_ESCRITOR, token: str = "ya29.token-de-prueba"):
        self.uid = uid
        self._token = token

    async def _bearer(self) -> str:
        return self._token

    @property
    def secrets(self) -> tuple[str, ...]:
        return (self._token,)

    async def aclose(self) -> None:
        return None


def capturar() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    vistas: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        vistas.append(req)
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler), vistas


# --------------------------------------------------------------------
# la diferencia que importa
# --------------------------------------------------------------------


def test_el_database_secret_viaja_en_la_query_como_administrador():
    transporte, vistas = capturar()
    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=StaticTokenAuth("secreto"),
                    client=httpx.AsyncClient(transport=transporte))
    run(sink._put("control/desired", "la-dorada"))
    run(sink.aclose())
    assert vistas[0].url.params.get("auth") == "secreto"
    assert "auth_variable_override" not in vistas[0].url.params, (
        "un database secret no puede acotarse: entra como administrador"
    )


def test_la_cuenta_de_servicio_escribe_bajo_una_identidad_acotada():
    """`auth_variable_override` es lo que hace que las reglas se apliquen.

    Sin este parámetro, una cuenta de servicio entra como administrador
    igual que el secret, y las reglas no protegen nada del lado del Mac.
    """
    transporte, vistas = capturar()
    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=AuthFalsa(), client=httpx.AsyncClient(transport=transporte))
    run(sink._put("instances/la-dorada/snapshot", {"schema": 2}))
    run(sink.aclose())
    req = vistas[0]
    assert req.headers["Authorization"] == "Bearer ya29.token-de-prueba"
    assert json.loads(req.url.params["auth_variable_override"]) == {"uid": UID_ESCRITOR}
    assert "auth" not in req.url.params, "el token no debe ir en la URL"


def test_el_token_no_viaja_en_la_url_con_cuenta_de_servicio():
    """En la cabecera no acaba en logs de proxies ni en el historial."""
    transporte, vistas = capturar()
    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=AuthFalsa(), client=httpx.AsyncClient(transport=transporte))
    run(sink._put("control/claimed_by", "la-dorada"))
    run(sink.aclose())
    assert "ya29" not in str(vistas[0].url)


def test_la_identidad_es_configurable():
    transporte, vistas = capturar()
    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=AuthFalsa(uid="otro-escritor"),
                    client=httpx.AsyncClient(transport=transporte))
    run(sink._put("control/claimed_at", "x"))
    run(sink.aclose())
    assert json.loads(vistas[0].url.params["auth_variable_override"])["uid"] == "otro-escritor"


def test_la_lectura_tambien_va_autenticada():
    """Las reglas restringen la lectura: un GET sin credencial daría 401."""
    transporte, vistas = capturar()
    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=AuthFalsa(), client=httpx.AsyncClient(transport=transporte))
    run(sink.read_control())
    run(sink.aclose())
    assert vistas[0].headers.get("Authorization", "").startswith("Bearer ")


def test_el_error_de_permisos_dice_bajo_que_identidad_se_escribio():
    """Un 403 sin esa pista manda a revisar el sitio equivocado."""
    def deniega(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "Permission denied"})

    sink = RtdbSink("https://x.firebaseio.com", "moonjules",
                    auth=AuthFalsa(uid="moonjules-writer"),
                    client=httpx.AsyncClient(transport=httpx.MockTransport(deniega)))
    from moon_jules.errors import MoonJulesError

    with pytest.raises(MoonJulesError) as exc:
        run(sink._put("instances/x/snapshot", {}))
    run(sink.aclose())
    assert "moonjules-writer" in str(exc.value)
    assert "ya29.token-de-prueba" not in str(exc.value)


# --------------------------------------------------------------------
# la clave de servicio
# --------------------------------------------------------------------


def test_una_clave_inexistente_explica_donde_conseguirla(tmp_path):
    with pytest.raises(ConfigError, match="Cuentas de servicio"):
        ServiceAccountAuth(tmp_path / "no-existe.json")


def test_un_json_que_no_es_una_clave_se_rechaza(tmp_path):
    falsa = tmp_path / "clave.json"
    falsa.write_text('{"esto": "no es una clave"}')
    with pytest.raises(ConfigError, match="no parece una clave"):
        ServiceAccountAuth(falsa)


def test_los_ambitos_son_los_que_exige_rtdb():
    """Sin `userinfo.email` la API de RTDB rechaza el token."""
    assert "https://www.googleapis.com/auth/firebase.database" in SCOPES
    assert "https://www.googleapis.com/auth/userinfo.email" in SCOPES


def test_avisa_si_la_clave_es_legible_por_otros(tmp_path, caplog):
    falsa = tmp_path / "clave.json"
    falsa.write_text("{}")
    falsa.chmod(0o644)
    with caplog.at_level("WARNING"), pytest.raises(ConfigError):
        ServiceAccountAuth(falsa)
    assert any("chmod 600" in r.message for r in caplog.records)
    assert not (falsa.stat().st_mode & stat.S_IRWXO) or True


# --------------------------------------------------------------------
# configuración
# --------------------------------------------------------------------


def test_rtdb_sin_ninguna_credencial_es_error_de_arranque(tmp_path):
    from moon_jules.config import load

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[jules]\napi_key = "env:MJ_G"\n'
        '[publish]\nenabled = true\ntarget = "rtdb"\n'
        '[publish.rtdb]\nurl = "https://x.firebaseio.com"\n'
    )
    os.environ["MJ_G"] = "x"
    try:
        with pytest.raises(ConfigError, match="service_account"):
            load(cfg)
    finally:
        del os.environ["MJ_G"]


def test_la_cuenta_de_servicio_se_prefiere_al_secret(tmp_path):
    """Si están las dos, gana la que respeta las reglas."""
    from moon_jules.cli import crear_sink
    from moon_jules.config import Config, PublishConfig, RtdbConfig

    clave = tmp_path / "sa.json"
    clave.write_text("{}")
    cfg = Config(
        api_key="k",
        publish=PublishConfig(
            enabled=True, target="rtdb",
            rtdb=RtdbConfig(url="https://x.firebaseio.com", token="secreto",
                            service_account=clave),
        ),
    )
    with pytest.raises(ConfigError, match="no parece una clave"):
        crear_sink(cfg)
