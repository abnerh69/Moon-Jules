"""Publicación del estado. Épica E20.

Escribe un snapshot del último ciclo donde otro proceso pueda leerlo —un
fichero, la salida estándar o Firebase RTDB—. Es la frontera entre
Moon-Jules y la app de Android: el esquema está versionado y
documentado en `docs/SNAPSHOT.md`, y romperlo rompe la app.

Dos ideas gobiernan el diseño.

**El latido es el dato más importante del snapshot.** Si el MacBook está
dormido, nadie publica, y la app debe poder deducirlo. Por eso
`published_at` se reescribe en cada ciclo aunque no haya cambiado nada:
un snapshot fresco que dice "todo en orden" y uno viejo que dice lo
mismo son afirmaciones muy distintas, y solo la marca de tiempo las
distingue. Una máquina muerta no puede avisar de que está muerta; solo
puede dejar de hablar.

**El umbral de caducidad viaja en el snapshot.** Se publica
`stale_after_s` para que el criterio viva en un solo sitio y no
codificado en la app.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .detector import Report
from .errors import MoonJulesError
from .gauth import RtdbAuth, StaticTokenAuth
from .logs import get as get_logger

log = get_logger("publish")

#: Versión del esquema. Se sube al añadir campos; se sube de mayor al
#: quitar o cambiar el significado de uno. La app debe rechazar lo que
#: no entienda en vez de interpretarlo a medias.
SCHEMA = 3

#: Cuántas sesiones caben en el snapshot. Con el tope de 15 concurrentes
#: del plan, 40 deja sitio de sobra para lo activo más lo que requiere
#: atención, y acota lo que se sube en cada ciclo.
MAX_SESIONES = 40


@dataclass(frozen=True)
class Control:
    """Quien deberia estar vigilando, segun el punto de encuentro.

    `desired` lo escribe el telefono; `claimed` lo escribe la instancia
    que recoge el encargo. Se guardan por separado a proposito: si solo
    hubiera uno, el telefono podria escribir "ahora manda Sao Paulo" y
    mostrarlo como hecho aunque ese portatil estuviera dormido y nadie
    hubiera recogido nada. Deseado y real son preguntas distintas, y la
    app debe poder ver ambas.
    """

    desired: str | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    #: False si no se pudo leer el punto de encuentro.
    known: bool = True

    def role_for(self, instancia: str, *, por_defecto_activo: bool) -> str:
        if not self.known:
            # Ante la duda, callar. Que nadie actue es preferible a que
            # actuen tres: el presupuesto de nudges es por sesion, no por
            # maquina, y tres instancias lo agotarian en una pasada.
            return "standby"
        if self.desired is None:
            return "active" if por_defecto_activo else "standby"
        return "active" if self.desired == instancia else "standby"


def instance_id(configurado: str | None = None) -> str:
    """Identifica la máquina que publica.

    Sin esto, un latido muerto no dice a dónde ir: con tres portátiles
    en tres países, saber *cuál* estaba corriendo es la mitad de la
    información útil.
    """
    if configurado:
        return configurado
    nombre = socket.gethostname().split(".")[0]
    return nombre or platform.node() or "desconocido"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt else None


def sin_nulos(valor: Any) -> Any:
    """Poda las claves con valor nulo, en profundidad.

    Firebase RTDB **no almacena nulos**: los omite al escribir. Sin esta
    normalizacion, el mismo snapshot tendria dos formas segun el destino
    —con las claves en un fichero, sin ellas en RTDB— y la app tendria
    que tolerar ambas. Se poda aqui para que el contrato sea uno solo:
    **una clave ausente significa desconocida o no aplicable.**
    """
    if isinstance(valor, dict):
        return {k: sin_nulos(v) for k, v in valor.items() if v is not None}
    if isinstance(valor, list):
        return [sin_nulos(v) for v in valor]
    return valor


def construir(
    report: Report,
    *,
    ahora: datetime,
    instancia: str,
    intervalo_s: int,
    modo: str,
    max_activas: int,
    nudges: dict[str, Any] | None = None,
    control: Control | None = None,
    role: str = "active",
) -> dict:
    """Arma el snapshot. Función pura: se prueba sin red ni ficheros."""
    nudges = nudges or {}
    interesantes = sorted(
        (f for f in report.findings if f.is_problem or f.session.state.value
         not in ("COMPLETED", "FAILED")),
        key=lambda f: (not f.needs_attention, -(f.silence_s or 0)),
    )[:MAX_SESIONES]

    sesiones = []
    for f in interesantes:
        s = f.session
        n = nudges.get(s.name)
        sesiones.append(
            {
                "id": s.id,
                "repo": s.repo,
                "title": s.title,
                "state": s.state.value,
                "verdict": f.verdict.value,
                "reason": f.reason,
                "acked": f.acked,
                "needs_attention": f.needs_attention,
                # Cuánto lleva muda. `null` si el reloj está congelado
                # porque la sesión cerró: eso es reposo, no silencio.
                "silence_s": round(f.silence_s) if f.silence_s is not None else None,
                # Cuánto lleva abierta, que es otra pregunta distinta.
                "age_s": (
                    round((ahora - s.create_time).total_seconds())
                    if s.create_time
                    else None
                ),
                "started_at": _iso(s.create_time),
                "url": s.url,
                "nudges": n.get("count", 0) if n else 0,
                "last_nudge_at": n.get("sent_at") if n else None,
                "last_nudge_outcome": n.get("outcome") if n else None,
            }
        )

    return sin_nulos({
        "schema": SCHEMA,
        "instance": {
            "id": instancia,
            "version": __version__,
            "published_at": _iso(ahora),
            # El mismo instante en milisegundos. Las reglas de RTDB
            # comparan numeros contra `now`, no cadenas ISO: sin este
            # campo no se puede impedir por regla que la app designe a
            # una maquina que lleva horas callada.
            "heartbeat_ms": int(ahora.timestamp() * 1000),
            "cycle_interval_s": intervalo_s,
            # El criterio de caducidad viaja con el dato: cuatro ciclos,
            # nunca menos de 20 minutos. Así la app no lo codifica.
            "stale_after_s": max(20 * 60, 4 * intervalo_s),
            "mode": modo,
            "role": role,
        },
        "control": {
            "desired": control.desired if control else None,
            "claimed_by": control.claimed_by if control else None,
            "claimed_at": control.claimed_at if control else None,
            # False significa que esta instancia no pudo leer el punto de
            # encuentro, no que no haya nadie designado.
            "known": control.known if control else True,
        },
        "swarm": {
            "sessions_total": len(report.findings),
            "active": sum(
                1
                for f in report.findings
                if f.session.state.value not in ("COMPLETED", "FAILED")
            ),
            "max_active": max_activas,
            "attention": len(report.attention),
            "acked": len(report.acked),
            "paused": report.paused or None,
        },
        "sessions": sesiones,
    })


# ---------- destinos ----------


class Sink(ABC):
    """Dónde se deja el snapshot. Pequeña a propósito: RTDB hoy, otra
    cosa mañana, sin tocar nada más."""

    name = "none"

    @abstractmethod
    async def publish(self, snapshot: dict) -> None: ...

    async def aclose(self) -> None:
        return None


class StdoutSink(Sink):
    name = "stdout"

    async def publish(self, snapshot: dict) -> None:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))


class FileSink(Sink):
    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def publish(self, snapshot: dict) -> None:
        """Escritura atómica: un lector nunca ve medio snapshot."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class RtdbSink(Sink):
    """Firebase Realtime Database por REST, sin SDK.

    El token viaja en la query, así que la URL **nunca** se registra
    entera: se loguea solo la ruta. Además el token se declara como
    secreto del proceso para que el redactor del logger lo enmascare si
    aparece por cualquier otro camino (ADR-004).
    """

    name = "rtdb"

    def __init__(
        self,
        url: str,
        root: str,
        token: str = "",
        *,
        auth: RtdbAuth | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base = url.rstrip("/")
        self.root = root.strip("/")
        self.auth = auth or StaticTokenAuth(token)
        self._http = client or httpx.AsyncClient(timeout=timeout)

    def _url(self, ruta: str) -> str:
        return f"{self.base}/{self.root}/{ruta}.json"

    async def _put(self, ruta: str, cuerpo: Any) -> None:
        cabeceras, params = await self.auth.apply()
        try:
            r = await self._http.put(
                self._url(ruta), params=params, json=cuerpo, headers=cabeceras
            )
        except httpx.TransportError as exc:
            raise MoonJulesError(f"no se pudo publicar en RTDB: {exc}") from exc
        if r.is_success:
            log.debug("publicado en %s/%s", self.root, ruta)
            return
        # El cuerpo del error de Firebase no lleva el token, pero la URL
        # sí: por eso solo se nombra la ruta.
        raise MoonJulesError(
            f"RTDB rechazo la escritura en {self.root}/{ruta}: "
            + self._explicar(r)
        )

    async def publish(self, snapshot: dict) -> None:
        instancia = snapshot["instance"]["id"]
        await self._put(f"instances/{instancia}/snapshot", snapshot)

    async def _get(self, ruta: str) -> Any:
        cabeceras, params = await self.auth.apply()
        try:
            r = await self._http.get(
                self._url(ruta), params=params, headers=cabeceras
            )
        except httpx.TransportError as exc:
            raise MoonJulesError(f"no se pudo leer de RTDB: {exc}") from exc
        if not r.is_success:
            raise MoonJulesError(
                f"RTDB rechazo la lectura de {self.root}/{ruta}: " + self._explicar(r)
            )
        return r.json()

    def _explicar(self, r: httpx.Response) -> str:
        """Traduce la respuesta de Firebase.

        RTDB devuelve **401 tambien cuando son las reglas las que
        deniegan**, no solo cuando la credencial es mala. Confundir
        ambos casos manda a revisar el sitio equivocado, y el cuerpo de
        la respuesta es justo donde Firebase lo aclara.
        """
        try:
            cuerpo = str((r.json() or {}).get("error", ""))
        except ValueError:
            cuerpo = ""
        uid = getattr(self.auth, "uid", None)
        if "Permission denied" in cuerpo:
            if uid:
                return (
                    f"HTTP {r.status_code}: las reglas denegaron a uid '{uid}'.\n"
                    "No es la credencial: con `auth_variable_override` la cuenta "
                    "de servicio deja de ser administradora y las reglas se le "
                    "aplican. Publica las de docs/RTDB.md."
                )
            return f"HTTP {r.status_code}: las reglas denegaron el acceso."
        if r.status_code in (401, 403):
            return (
                f"HTTP {r.status_code}: {cuerpo or 'sin detalle'}. Revisa la "
                "credencial y que el project_id de la clave coincida con la URL."
            )
        return f"HTTP {r.status_code}: {cuerpo or 'sin detalle'}"

    async def read_control(self) -> Control:
        """Lee quien deberia vigilar. Nunca levanta: la duda es un dato."""
        try:
            crudo = await self._get("control") or {}
        except MoonJulesError as exc:
            log.warning("no se pudo leer el control: %s", exc)
            return Control(known=False)
        if not isinstance(crudo, dict):
            return Control(known=False)
        return Control(
            desired=crudo.get("desired") or None,
            claimed_by=crudo.get("claimed_by") or None,
            claimed_at=crudo.get("claimed_at") or None,
        )

    async def claim(self, instancia: str, ahora: datetime) -> None:
        """Confirma que esta instancia recogio el encargo.

        Es la mitad que convierte una asignacion en una reclamacion: sin
        esto, la app mostraria como vigilada una maquina dormida.
        """
        await self._put(
            "control/claimed_by", instancia
        )
        await self._put("control/claimed_at", _iso(ahora))

    async def set_desired(self, instancia: str | None) -> None:
        """Designa quien debe vigilar. Lo normal es que lo haga la app."""
        await self._put("control/desired", instancia)

    async def read_devices(self) -> list[str]:
        """Tokens FCM que la app ha registrado. Nunca levanta."""
        try:
            crudo = await self._get("devices")
        except MoonJulesError as exc:
            log.warning("no se pudieron leer los dispositivos: %s", exc)
            return []
        if isinstance(crudo, dict):
            return [k for k, v in crudo.items() if v]
        return []

    async def forget_device(self, token: str) -> None:
        await self._put(f"devices/{token}", None)

    async def read_command(self) -> Any:
        """Lee el comando pendiente. Nunca levanta: sin comando, None."""
        try:
            return await self._get("command")
        except MoonJulesError as exc:
            log.warning("no se pudo leer el comando: %s", exc)
            return None

    async def publish_result(self, instancia: str, resultado: dict) -> None:
        await self._put(f"instances/{instancia}/command_result", resultado)

    async def publish_decisions(self, instancia: str, decisiones: dict) -> None:
        await self._put(f"instances/{instancia}/decisions", decisiones)

    async def aclose(self) -> None:
        await self.auth.aclose()
        await self._http.aclose()
