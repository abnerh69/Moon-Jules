"""Comandos desde la app. Épica E24.

RTDB no es una cola de mensajes, y tratarlo como si lo fuera produce tres
formas del mismo desastre —una orden ejecutada cuando ya no tocaba—:

1. **Reejecución.** Si la instancia actúa y muere antes de anotar que lo
   hizo, al reiniciar volvería a actuar. Se evita con idempotencia por
   identificador, guardado en SQLite: un `id` ya visto no se repite.
2. **Órdenes zombis.** Un comando escrito mientras las tres máquinas
   duermen se ejecutaría horas después. "Desatasca esta sesión" emitido
   a las nueve y ejecutado a las seis de la tarde está mal, aunque el
   mecanismo haya funcionado. Se evita con `expires_at`.
3. **Relevo a media orden.** Si la designación cambia entre que se
   escribe y que se lee, la recoge otra máquina. Se evita porque solo la
   instancia activa mira el nodo, y el acuse dice cuál lo hizo.

Semántica deliberada: **un comando no es autonomía, es mando a
distancia.** Se ejecuta aunque el source esté en `read_only` o la
autonomía pausada. Si el arquitecto pausó y luego manda un nudge,
claramente quiere el nudge. Los modos gobiernan lo que Moon-Jules decide
por su cuenta, no lo que se le ordena.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .detector import Report
from .errors import MoonJulesError
from .logs import get as get_logger
from .models import parse_ts
from .store import GLOBAL_SCOPE

log = get_logger("commands")

#: Verbos admitidos. Fuera quedan a proposito los que cruzan la NO list:
#: crear sesiones o asignar tareas (trabajo de la GitHub Action) y
#: archivar o borrar (escritura sobre el workspace del arquitecto).
VERBOS = frozenset(
    {"nudge", "approve_plan", "ack", "unack", "pause", "resume", "refresh"}
)

#: Si la app no fija caducidad, cuanto vive un comando.
TTL_POR_DEFECTO_S = 600


class EstadoComando:
    DONE = "done"
    FAILED = "failed"
    EXPIRED = "expired"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Command:
    id: str
    verb: str
    args: dict
    issued_at: datetime | None = None
    expires_at: datetime | None = None

    @classmethod
    def from_rtdb(cls, crudo: object, *, ttl_s: int = TTL_POR_DEFECTO_S) -> Command | None:
        """Interpreta el nodo. Devuelve None si no hay comando alguno."""
        if not isinstance(crudo, dict) or not crudo.get("id"):
            return None
        emitido = parse_ts(crudo.get("issued_at"))
        caduca = parse_ts(crudo.get("expires_at"))
        if caduca is None and emitido is not None:
            caduca = emitido + timedelta(seconds=ttl_s)
        args = crudo.get("args")
        return cls(
            id=str(crudo["id"]),
            verb=str(crudo.get("verb") or ""),
            args=args if isinstance(args, dict) else {},
            issued_at=emitido,
            expires_at=caduca,
        )

    def caducado(self, ahora: datetime) -> bool:
        """Sin caducidad conocida se considera caducado.

        Es el lado prudente: no poder razonar sobre la frescura de una
        orden es motivo suficiente para no ejecutarla.
        """
        return self.expires_at is None or self.expires_at <= ahora


@dataclass(frozen=True)
class Resultado:
    id: str
    status: str
    message: str
    completed_at: str
    #: Pide al bucle que no espere al siguiente ciclo.
    refrescar: bool = False

    def to_rtdb(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "completed_at": self.completed_at,
        }


def _sesion(args: dict) -> str | None:
    crudo = args.get("session") or args.get("session_id")
    if not crudo:
        return None
    crudo = str(crudo)
    return crudo if crudo.startswith("sessions/") else f"sessions/{crudo}"


def _duracion(args: dict) -> timedelta | None:
    crudo = args.get("for") or args.get("duration")
    if not crudo:
        return None
    from .cli import parse_duracion

    return parse_duracion(str(crudo))


async def ejecutar(
    cmd: Command,
    *,
    client: object,
    store: object,
    report: Report,
    ahora: datetime,
    prompt: str = "Completa la tarea",
) -> Resultado:
    """Lleva a cabo un comando. Nunca levanta: el fallo es un resultado.

    Que un comando falle no puede tumbar el bucle de vigilancia: lo
    importante sigue siendo mirar a Jules.
    """

    def fin(status: str, msg: str, refrescar: bool = False) -> Resultado:
        return Resultado(
            cmd.id, status, msg, ahora.isoformat().replace("+00:00", "Z"), refrescar
        )

    if cmd.verb not in VERBOS:
        return fin(EstadoComando.REJECTED, f"verbo desconocido: {cmd.verb!r}")
    if cmd.caducado(ahora):
        cuando = cmd.expires_at.isoformat() if cmd.expires_at else "sin fecha"
        return fin(EstadoComando.EXPIRED, f"caducado ({cuando}): no se ejecuta")

    try:
        return await _despachar(cmd, client, store, report, ahora, prompt, fin)
    except MoonJulesError as exc:
        log.warning("comando %s (%s) fallo: %s", cmd.id, cmd.verb, exc)
        return fin(EstadoComando.FAILED, str(exc))
    except Exception as exc:  # noqa: BLE001 - el bucle no puede caerse por esto
        log.exception("comando %s (%s) reviento", cmd.id, cmd.verb)
        return fin(EstadoComando.FAILED, f"{type(exc).__name__}: {exc}")


async def _despachar(cmd, client, store, report, ahora, prompt, fin):  # noqa: ANN001
    if cmd.verb == "refresh":
        return fin(EstadoComando.DONE, "ciclo forzado", refrescar=True)

    if cmd.verb in ("pause", "resume"):
        scope = str(cmd.args.get("scope") or GLOBAL_SCOPE)
        donde = "toda la autonomia" if scope == GLOBAL_SCOPE else scope
        if cmd.verb == "resume":
            n = store.resume(scope)
            return fin(
                EstadoComando.DONE,
                f"reanudado: {donde}" if n else f"{donde} no estaba pausada",
            )
        hasta = ahora + (_duracion(cmd.args) or timedelta(0)) or None
        if _duracion(cmd.args) is None:
            hasta = None
        store.pause(scope, ahora, hasta, cmd.args.get("reason") or "desde la app")
        plazo = f" hasta {hasta:%H:%M UTC}" if hasta else " indefinidamente"
        return fin(EstadoComando.DONE, f"pausado: {donde}{plazo}")

    name = _sesion(cmd.args)
    if not name:
        return fin(EstadoComando.REJECTED, f"{cmd.verb} necesita `session` en args")

    hallazgo = next((f for f in report.findings if f.session.name == name), None)

    if cmd.verb == "unack":
        n = store.unack(name)
        return fin(
            EstadoComando.DONE,
            f"{n} silenciamiento(s) retirado(s)" if n else "no estaba silenciada",
        )

    if hallazgo is None:
        # Se resuelve contra el ultimo ciclo, no contra el API: si la
        # sesion no salio ahi, la app esta viendo algo que ya no existe.
        return fin(
            EstadoComando.REJECTED,
            f"{name} no aparece en el ultimo ciclo; refresca la app",
        )

    if cmd.verb == "ack":
        store.ack(name, hallazgo.verdict.value, ahora, cmd.args.get("note") or "desde la app")
        return fin(
            EstadoComando.DONE,
            f"silenciado {hallazgo.verdict.value} en {hallazgo.session.repo}",
        )

    if cmd.verb == "approve_plan":
        await client.approve_plan(name)
        return fin(EstadoComando.DONE, f"plan aprobado en {hallazgo.session.repo}")

    # nudge: el que de verdad se usara desde el movil.
    await client.send_message(name, prompt)
    store.record_nudge(name, prompt, ahora)
    return fin(EstadoComando.DONE, f"nudge enviado a {hallazgo.session.repo}")
