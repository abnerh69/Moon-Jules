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
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .detector import Report
from .errors import MoonJulesError
from .logs import get as get_logger

log = get_logger("publish")

#: Versión del esquema. Se sube al añadir campos; se sube de mayor al
#: quitar o cambiar el significado de uno. La app debe rechazar lo que
#: no entienda en vez de interpretarlo a medias.
SCHEMA = 1

#: Cuántas sesiones caben en el snapshot. Con el tope de 15 concurrentes
#: del plan, 40 deja sitio de sobra para lo activo más lo que requiere
#: atención, y acota lo que se sube en cada ciclo.
MAX_SESIONES = 40


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


def construir(
    report: Report,
    *,
    ahora: datetime,
    instancia: str,
    intervalo_s: int,
    modo: str,
    max_activas: int,
    nudges: dict[str, Any] | None = None,
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

    return {
        "schema": SCHEMA,
        "instance": {
            "id": instancia,
            "version": __version__,
            "published_at": _iso(ahora),
            "cycle_interval_s": intervalo_s,
            # El criterio de caducidad viaja con el dato: cuatro ciclos,
            # nunca menos de 20 minutos. Así la app no lo codifica.
            "stale_after_s": max(20 * 60, 4 * intervalo_s),
            "mode": modo,
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
    }


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
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base = url.rstrip("/")
        self.root = root.strip("/")
        self._token = token
        self._http = client or httpx.AsyncClient(timeout=timeout)

    def _url(self, ruta: str) -> str:
        return f"{self.base}/{self.root}/{ruta}.json"

    async def _put(self, ruta: str, cuerpo: Any) -> None:
        params = {"auth": self._token} if self._token else {}
        try:
            r = await self._http.put(self._url(ruta), params=params, json=cuerpo)
        except httpx.TransportError as exc:
            raise MoonJulesError(f"no se pudo publicar en RTDB: {exc}") from exc
        if r.is_success:
            log.debug("publicado en %s/%s", self.root, ruta)
            return
        # El cuerpo del error de Firebase no lleva el token, pero la URL
        # sí: por eso solo se nombra la ruta.
        raise MoonJulesError(
            f"RTDB rechazo la escritura en {self.root}/{ruta}: "
            f"HTTP {r.status_code}. Revisa las reglas de seguridad y el token."
        )

    async def publish(self, snapshot: dict) -> None:
        instancia = snapshot["instance"]["id"]
        await self._put(f"instances/{instancia}/snapshot", snapshot)

    async def publish_decisions(self, instancia: str, decisiones: dict) -> None:
        await self._put(f"instances/{instancia}/decisions", decisiones)

    async def aclose(self) -> None:
        await self._http.aclose()
