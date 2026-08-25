"""Autenticación contra Firebase RTDB. Épica E23.

Hay dos formas de que Moon-Jules escriba en RTDB, y la diferencia no es
de comodidad sino de a quién protege.

Un **database secret** es una cadena fija de administrador: no caduca, no
se rota, y **salta todas las reglas de seguridad**. Con él, la promesa de
que "el teléfono solo escribe `control/desired`" la sostiene el buen
comportamiento de este código, no la base de datos. Google además lo
tiene obsoleto desde hace años.

Una **cuenta de servicio** firma un JWT, lo canjea por un token OAuth2 de
una hora y lo renueva sola. Y, lo que de verdad importa, admite
`auth_variable_override`: la petición se evalúa **bajo una identidad
acotada**, así que las reglas se aplican también a los Mac. El contrato
deja de ser una convención y pasa a estar impuesto por Firebase.

El transporte va sobre httpx para no meter una segunda pila HTTP en el
proceso: `google-auth` trae `requests` solo como extra opcional.
"""

from __future__ import annotations

import asyncio
import json
import stat
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from .errors import ConfigError, MoonJulesError
from .logs import get as get_logger

log = get_logger("gauth")

#: Ámbitos que exige la API REST de Realtime Database.
SCOPES = (
    "https://www.googleapis.com/auth/firebase.database",
    "https://www.googleapis.com/auth/userinfo.email",
)

#: Identidad por defecto bajo la que escriben las instancias. Debe
#: coincidir con la de las reglas de seguridad (ver docs/RTDB.md).
UID_ESCRITOR = "moonjules-writer"


class RtdbAuth(ABC):
    """Cómo se autentica una petición. Dos implementaciones, un contrato."""

    name = "none"

    @abstractmethod
    async def apply(self) -> tuple[dict[str, str], dict[str, str]]:
        """Devuelve (cabeceras, parámetros) para la petición."""

    @property
    def secrets(self) -> tuple[str, ...]:
        """Valores que el logger debe enmascarar."""
        return ()

    async def aclose(self) -> None:
        return None


class StaticTokenAuth(RtdbAuth):
    """Database secret. Funciona, pero es administrador y está obsoleto."""

    name = "static"

    def __init__(self, token: str) -> None:
        self._token = token
        if token:
            log.warning(
                "usando un database secret: es credencial de administrador y "
                "salta las reglas de seguridad. Ver docs/RTDB.md para migrar "
                "a una cuenta de servicio."
            )

    async def apply(self) -> tuple[dict[str, str], dict[str, str]]:
        return {}, ({"auth": self._token} if self._token else {})

    @property
    def secrets(self) -> tuple[str, ...]:
        return (self._token,) if self._token else ()


class ServiceAccountAuth(RtdbAuth):
    """Cuenta de servicio con identidad acotada.

    El token se renueva solo: `google-auth` lo considera inválido cinco
    minutos antes de expirar, así que nunca se usa uno caducado.
    """

    name = "service_account"

    def __init__(
        self,
        key_path: Path,
        *,
        uid: str = UID_ESCRITOR,
        timeout: float = 20.0,
    ) -> None:
        self.uid = uid
        self._path = key_path
        self._creds = _cargar_credenciales(key_path)
        self._request = _HttpxRequest(timeout)

    async def apply(self) -> tuple[dict[str, str], dict[str, str]]:
        token = await self._bearer()
        # `auth_variable_override` hace que la peticion se evalue como
        # `uid`, de modo que las reglas se aplican tambien aqui. Sin
        # esto, una cuenta de servicio entra como administrador y las
        # reglas no protegen nada del lado del Mac.
        override = json.dumps({"uid": self.uid}, separators=(",", ":"))
        return (
            {"Authorization": f"Bearer {token}"},
            {"auth_variable_override": override},
        )

    async def _bearer(self) -> str:
        if not self._creds.valid:
            # Firmar y canjear bloquea unos cientos de milisegundos, una
            # vez por hora. Fuera del hilo del bucle.
            try:
                await asyncio.to_thread(self._creds.refresh, self._request)
            except Exception as exc:  # google.auth.exceptions.*
                raise MoonJulesError(
                    "no se pudo renovar el token de la cuenta de servicio: "
                    f"{type(exc).__name__}. Revisa que la clave siga activa y "
                    "que el proyecto tenga habilitada la API de RTDB."
                ) from exc
        return str(self._creds.token)

    @property
    def secrets(self) -> tuple[str, ...]:
        token = getattr(self._creds, "token", None)
        return (token,) if token else ()

    async def aclose(self) -> None:
        self._request.close()


def _cargar_credenciales(path: Path) -> Any:
    """Lee la clave de servicio, con los errores explicados."""
    if not path.is_file():
        raise ConfigError(
            f"no existe la clave de la cuenta de servicio: {path}. "
            "Se descarga desde la consola de Firebase, en Configuración del "
            "proyecto > Cuentas de servicio."
        )
    modo = path.stat().st_mode
    if modo & (stat.S_IRWXG | stat.S_IRWXO):
        # Mismo criterio que con el `.env`: avisar, no bloquear.
        log.warning(
            "%s es legible por otros usuarios; ajusta con: chmod 600 %s", path, path
        )
    try:
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover
        raise ConfigError(
            "falta la dependencia `google-auth`. Instala con: "
            'pip install -e "."'
        ) from exc
    try:
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=list(SCOPES)
        )
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"{path} no parece una clave de cuenta de servicio válida: {exc}"
        ) from exc


class _Respuesta:
    """La forma que `google-auth` espera de una respuesta HTTP."""

    def __init__(self, r: httpx.Response) -> None:
        self.status = r.status_code
        self.data = r.content
        self.headers = r.headers


class _HttpxRequest:
    """Transporte para `google-auth` sobre httpx.

    Existe para no arrastrar `requests` al proceso solo por renovar un
    token una vez por hora: dos pilas HTTP en un proyecto que presume de
    tener una sola dependencia sería mal negocio.
    """

    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.Client(timeout=timeout)

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **_kw: object,
    ) -> _Respuesta:
        r = self._client.request(
            method, url, content=body, headers=headers, timeout=timeout or 20.0
        )
        return _Respuesta(r)

    def close(self) -> None:
        self._client.close()
