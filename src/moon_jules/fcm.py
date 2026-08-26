"""Notificaciones push al móvil. Épica E28.

RTDB en tiempo real solo despierta a la app en primer plano. Para que
una alerta llegue con el teléfono en el bolsillo hace falta FCM, y la
cuenta de servicio que ya publica el snapshot sirve también para enviar:
mismo proyecto, otro ámbito. Sin Cloud Functions y sin plan de pago.

Hay una alerta que **no puede salir de aquí**, y conviene tenerlo claro:
la de instancia caída. La máquina que se cayó es precisamente la que
tendría que avisar. Esa la detecta el teléfono vigilando `heartbeat_ms`.

La lógica de a quién avisar y cuándo no se reimplementa: se reutiliza el
`Notifier`, que ya suprime repetidos por (sesión, veredicto) contra
SQLite. Una sesión colgada notificaría en cada ciclo —doce veces por
hora— y el arquitecto silenciaría la app, que es peor que no tenerla.
"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import MoonJulesError
from .gauth import ServiceAccountAuth
from .logs import get as get_logger
from .notify import Backend

log = get_logger("fcm")

ENDPOINT = "https://fcm.googleapis.com/v1/projects/{proyecto}/messages:send"

#: Ambito de la API de mensajeria, ademas de los de RTDB.
SCOPE_MENSAJERIA = "https://www.googleapis.com/auth/firebase.messaging"

#: Respuestas que significan "este dispositivo ya no existe". Se retiran
#: sus tokens: si no, cada ciclo intentaria enviar a telefonos muertos.
MUERTOS = ("UNREGISTERED", "INVALID_ARGUMENT")


class FcmBackend(Backend):
    """Backend de `Notifier` que envía a los dispositivos registrados.

    Los tokens los escribe la app en `{root}/devices/{token}`. Se leen en
    cada envío en vez de cachearse: son uno o dos, y un token recién
    registrado debe funcionar sin reiniciar el servicio.
    """

    name = "fcm"

    def __init__(
        self,
        auth: ServiceAccountAuth,
        proyecto: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._auth = auth
        self._proyecto = proyecto
        # Los tokens los inyecta el ciclo, que ya esta en contexto
        # asincrono. `Notifier` es sincrono y hacerle esperar una
        # corrutina desde dentro exigiria hilos o bucles anidados.
        self._tokens: list[str] = []
        #: Tokens que FCM dio por muertos. El ciclo los retira de RTDB.
        self.retirados: list[str] = []
        self._http = client or httpx.Client(timeout=timeout)

    def set_tokens(self, tokens: list[str]) -> None:
        self._tokens = list(tokens)
        self.retirados.clear()

    @staticmethod
    def available() -> bool:
        return True

    def send(self, title: str, body: str) -> bool:
        """Síncrono a propósito: `Notifier` lo es, y esto es un POST corto
        por dispositivo, que además solo ocurre cuando hay algo que
        avisar. Devuelve True si al menos uno lo recibió.
        """
        tokens = self._tokens
        if not tokens:
            # A nivel INFO y no debug: "no hay a quien enviar" es
            # justo lo que hay que poder leer cuando el push no llega,
            # y en debug no se ve con la configuracion normal.
            log.info("push omitido: ningun dispositivo registrado")
            return False
        entregados = 0
        for token in tokens:
            try:
                if self._enviar(token, title, body):
                    entregados += 1
            except MoonJulesError as exc:
                log.warning("fallo al enviar a un dispositivo: %s", exc)
        # Cuantos, no solo si alguno: un "1 notificacion enviada" que no
        # dice a cuantos aparatos llego hizo buscar el fallo en el sitio
        # equivocado durante una noche entera.
        log.info(
            "push entregado a %d de %d dispositivo(s)", entregados, len(tokens)
        )
        return entregados > 0

    def _enviar(self, token: str, title: str, body: str) -> bool:
        cabeceras = self._auth.bearer_sync()
        cuerpo = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "android": {"priority": "high"},
            }
        }
        try:
            r = self._http.post(
                ENDPOINT.format(proyecto=self._proyecto),
                headers={"Authorization": f"Bearer {cabeceras}"},
                json=cuerpo,
            )
        except httpx.TransportError as exc:
            raise MoonJulesError(f"no se pudo contactar con FCM: {exc}") from exc
        if r.is_success:
            return True
        motivo = _motivo(r)
        if motivo in MUERTOS:
            # El telefono se desinstalo o reinstalo. Sin esta limpieza,
            # cada ciclo insistiria con un token que ya no existe.
            log.info("token retirado (%s)", motivo)
            self.retirados.append(token)
            return False
        raise MoonJulesError(f"FCM rechazo el envio: HTTP {r.status_code} {motivo}")


def _motivo(r: httpx.Response) -> str:
    try:
        error: Any = (r.json() or {}).get("error") or {}
    except ValueError:
        return "sin detalle"
    for d in error.get("details") or []:
        if d.get("errorCode"):
            return str(d["errorCode"])
    return str(error.get("status") or error.get("message") or "sin detalle")
