"""Carga de configuracion y resolucion de secretos.

Regla dura (ADR-004): el config referencia la credencial, nunca la
contiene. Un valor literal sin prefijo de resolvedor es un error de
arranque, no un aviso. Asi el config.toml es versionable de verdad.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from .detector import Policy
from .errors import ConfigError
from .logs import get as get_logger
from .models import AutonomyMode

log = get_logger("config")

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "moon-jules"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "moon-jules"
CONFIG_PATH = CONFIG_HOME / "config.toml"
ENV_NAME = ".env"

RESOLVERS = ("env:", "keychain:")


def _parse_dotenv(text: str) -> dict[str, str]:
    """Formato dotenv minimo: KEY=VALUE, comentarios y comillas opcionales."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_dotenv(extra: Path | None = None) -> list[Path]:
    """Carga variables desde `.env` en el entorno del proceso.

    Orden de busqueda: el directorio de configuracion primero, el
    directorio actual despues (que puede sobrescribir al anterior). Una
    variable ya presente en el entorno real **siempre gana**: asi se
    puede sobrescribir para una sola ejecucion sin editar ficheros.

    El `.env` nunca se versiona: esta en `.gitignore` desde el primer
    commit y aqui se avisa si sus permisos son demasiado abiertos.
    """
    cargados: list[Path] = []
    for path in (CONFIG_HOME / ENV_NAME, Path.cwd() / ENV_NAME, extra):
        if path is None or not path.is_file():
            continue
        try:
            modo = path.stat().st_mode
        except OSError:
            modo = 0
        if modo & 0o077:
            log.warning(
                "%s es legible por otros usuarios; ajusta con: chmod 600 %s", path, path
            )
        for key, value in _parse_dotenv(path.read_text(encoding="utf-8")).items():
            if key not in os.environ:  # el entorno real manda
                os.environ[key] = value
        cargados.append(path)
    return cargados


@dataclass(frozen=True)
class SourceConfig:
    name: str
    mode: AutonomyMode = AutonomyMode.READ_ONLY
    starting_branch: str = "main"
    policy: Policy = field(default_factory=Policy)


@dataclass(frozen=True)
class Budgets:
    """Topes del plan Jules in Pro. ADR-005.

    Solo queda el de concurrencia, y no como limite propio sino como
    contexto: explica por que una sesion lleva rato en QUEUED. Los
    presupuestos de creacion desaparecieron con `assign-next`, que nunca
    fue trabajo de Moon-Jules.
    """

    max_active_sessions: int = 15


@dataclass(frozen=True)
class RtdbConfig:
    url: str = ""
    root: str = "moonjules"
    #: Database secret. Legado: administrador y salta las reglas.
    token: str = ""
    #: Ruta a la clave JSON de la cuenta de servicio. Preferida.
    service_account: Path | None = None
    #: Identidad bajo la que escriben las instancias, para que las
    #: reglas de seguridad se les apliquen. Ver docs/RTDB.md.
    uid: str = "moonjules-writer"


@dataclass(frozen=True)
class PublishConfig:
    """Publicacion del snapshot. Epica E20."""

    enabled: bool = False
    target: str = "file"          # stdout | file | rtdb
    instance_id: str = ""         # vacio: se usa el hostname
    path: Path = field(default=STATE_HOME / "snapshot.json")
    decisions: bool = True        # sube acks, pausas y nudges (son KB)
    rtdb: RtdbConfig = field(default_factory=RtdbConfig)


@dataclass(frozen=True)
class RelayConfig:
    """Relevo entre instancias. Epica E21.

    Solo tiene sentido con `publish.target = "rtdb"`: hace falta un punto
    de encuentro que las tres maquinas y el telefono compartan.
    """

    enabled: bool = False
    #: Que hacer mientras nadie ha designado a nadie. `false` es lo
    #: prudente con varias maquinas: nadie actua hasta que se elija.
    active_by_default: bool = False


@dataclass(frozen=True)
class NotifyConfig:
    """Dos vias que no son la misma cosa.

    `local` avisa a la maquina que vigila; `fcm` avisa a donde esta el
    arquitecto. Cuando la vigilante esta en otro pais, se quiere lo
    segundo sin lo primero, y un unico interruptor no lo permitia.
    """

    enabled: bool = False
    cooldown_s: int = 3600
    #: Notificacion del sistema operativo en la maquina que vigila.
    local: bool = True
    #: Push a los dispositivos registrados. Requiere rtdb con cuenta de
    #: servicio.
    fcm: bool = False


@dataclass(frozen=True)
class Config:
    api_key: str
    #: Se expone para poder apuntar la CLI al mock (`tools/mock_jules_api.py`)
    #: sin tocar el codigo, y para sobrevivir a un cambio de version del API.
    base_url: str = "https://jules.googleapis.com/v1alpha"
    poll_interval_s: int = 300
    #: Peticiones de actividades en paralelo. El API no publica cuota
    #: (ADR-001), asi que el limite es autoimpuesto y conservador.
    max_concurrency: int = 5
    #: Ventana de la primera consulta de actividades de una sesion. Muy
    #: superior a N: si no hay nada en 24 h, la sesion esta parada y no
    #: hace falta su historia para saberlo.
    bootstrap_lookback_s: int = 86400
    #: Cada cuantos ciclos se repagina el historial completo. El
    #: incremental no ve revivir una sesion ya terminada; esto acota
    #: cuanto puede tardarse en notarlo.
    full_refresh_every: int = 12
    #: Vida de un comando sin caducidad propia. Una orden vieja
    #: ejecutada tarde es peor que una orden perdida.
    command_ttl_s: int = 600
    default_mode: AutonomyMode = AutonomyMode.READ_ONLY
    policy: Policy = field(default_factory=Policy)
    budgets: Budgets = field(default_factory=Budgets)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    publish: PublishConfig = field(default_factory=PublishConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    state_path: Path = field(default=STATE_HOME / "state.db")
    log_dir: Path = field(default=STATE_HOME / "logs")
    lock_path: Path = field(default=STATE_HOME / "watch.lock")

    def for_source(self, source: str | None) -> SourceConfig:
        if source and source in self.sources:
            return self.sources[source]
        return SourceConfig(name=source or "", mode=self.default_mode, policy=self.policy)

    @property
    def secrets(self) -> tuple[str, ...]:
        """Valores a redactar en logs. Ver logs.redact.

        El token de RTDB viaja en la query de cada escritura, asi que
        entra aqui igual que la credencial de Jules: cualquier camino por
        el que acabe en un log queda enmascarado.
        """
        return tuple(s for s in (self.api_key, self.publish.rtdb.token) if s)


def resolve_secret(ref: str, *, field_name: str = "api_key") -> str:
    """Resuelve `env:VAR` o `keychain:servicio/cuenta`.

    Un literal sin prefijo se rechaza: es el modo en que las claves
    acaban en git.
    """
    if not isinstance(ref, str) or not ref.strip():
        raise ConfigError(f"{field_name} vacio")
    if not ref.startswith(RESOLVERS):
        raise ConfigError(
            f"{field_name} parece un secreto literal. Usa una referencia: "
            f'{field_name} = "env:JULES_API_KEY" o "keychain:moon-jules/jules", '
            f"y pon el valor en {CONFIG_HOME / ENV_NAME} o en el entorno. "
            "Ver ADR-004."
        )
    kind, _, rest = ref.partition(":")
    if kind == "env":
        val = os.environ.get(rest, "")
        if not val:
            raise ConfigError(
                f"la variable de entorno {rest} no esta definida. Ponla en "
                f"{CONFIG_HOME / ENV_NAME} (recomendado, no se versiona) o "
                f"expórtala con: read -rs {rest} && export {rest}"
            )
        return val
    service, _, account = rest.partition("/")
    if not shutil.which("security"):
        raise ConfigError("el resolvedor keychain solo esta disponible en macOS")
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account or service, "-w"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ConfigError(f"no se encontro {rest} en el llavero") from exc
    return out.stdout.strip()


def _policy_from(raw: dict, base: Policy) -> Policy:
    known = {f: raw[f] for f in ("stall_after_s", "plan_warn_s", "queue_warn_s",
                                 "nudge_verify_s", "max_nudges_per_session",
                                 "nudge_prompt") if f in raw}
    return replace(base, **known) if known else base


def load(path: Path | None = None, *, dotenv: Path | None = None) -> Config:
    load_dotenv(dotenv)
    p = path or CONFIG_PATH
    if not p.exists():
        raise ConfigError(
            f"no existe {p}. Copia config.example.toml ahi y ajusta los valores."
        )
    with p.open("rb") as fh:
        raw = tomllib.load(fh)

    jules = raw.get("jules") or {}
    api_key = resolve_secret(jules.get("api_key", ""))
    base_url = jules.get("base_url", "https://jules.googleapis.com/v1alpha")

    watch = raw.get("watch") or {}
    base_policy = _policy_from(watch, Policy())
    default_mode = AutonomyMode.parse(watch.get("default_mode", "read_only"))

    b = raw.get("budgets") or {}
    budgets = Budgets(max_active_sessions=int(b.get("max_active_sessions", 15)))

    sources: dict[str, SourceConfig] = {}
    for name, sraw in (raw.get("sources") or {}).items():
        sources[name] = SourceConfig(
            name=name,
            mode=AutonomyMode.parse(sraw.get("mode", default_mode.value)),
            starting_branch=sraw.get("starting_branch", "main"),
            policy=_policy_from(sraw, base_policy),
        )

    n = raw.get("notify") or {}
    notify = NotifyConfig(
        enabled=bool(n.get("enabled", False)),
        cooldown_s=int(n.get("cooldown_s", 3600)),
        local=bool(n.get("local", True)),
        fcm=bool(n.get("fcm", False)),
    )
    if notify.fcm and not notify.enabled:
        # Contradiccion silenciosa: con `enabled = false` el notificador
        # esta apagado entero y el backend de FCM nunca se usa. Mejor no
        # arrancar que arrancar sin avisar a nadie.
        raise ConfigError(
            "notify.fcm = true pero notify.enabled = false: las "
            "notificaciones estan apagadas y el push nunca saldria. "
            "Pon enabled = true."
        )
    if notify.enabled and not (notify.local or notify.fcm):
        raise ConfigError(
            "notify.enabled = true pero ni local ni fcm estan activos: "
            "no hay por donde avisar."
        )

    pub_raw = raw.get("publish") or {}
    rtdb_raw = pub_raw.get("rtdb") or {}
    token = (
        resolve_secret(rtdb_raw.get("auth", ""), field_name="publish.rtdb.auth")
        if rtdb_raw.get("auth")
        else ""
    )
    publish = PublishConfig(
        enabled=bool(pub_raw.get("enabled", False)),
        target=pub_raw.get("target", "file"),
        instance_id=pub_raw.get("instance_id", ""),
        path=Path(
            pub_raw.get("path", STATE_HOME / "snapshot.json")
        ).expanduser(),
        decisions=bool(pub_raw.get("decisions", True)),
        rtdb=RtdbConfig(
            url=rtdb_raw.get("url", ""),
            root=rtdb_raw.get("root", "moonjules"),
            token=token,
            service_account=(
                Path(rtdb_raw["service_account"]).expanduser()
                if rtdb_raw.get("service_account")
                else None
            ),
            uid=rtdb_raw.get("uid", "moonjules-writer"),
        ),
    )
    if publish.enabled and publish.target == "rtdb":
        if not publish.rtdb.url:
            raise ConfigError("publish.target = 'rtdb' pero falta publish.rtdb.url")
        if not publish.rtdb.service_account and not publish.rtdb.token:
            raise ConfigError(
                "publish.rtdb necesita `service_account` (recomendado) o "
                "`auth` (database secret, obsoleto). Ver docs/RTDB.md."
            )

    rel_raw = raw.get("relay") or {}
    relay = RelayConfig(
        enabled=bool(rel_raw.get("enabled", False)),
        active_by_default=bool(rel_raw.get("active_by_default", False)),
    )
    if relay.enabled and publish.target != "rtdb":
        raise ConfigError(
            "relay.enabled requiere publish.target = 'rtdb': el relevo "
            "necesita un punto de encuentro compartido."
        )

    state = raw.get("state") or {}
    state_path = Path(state.get("path", STATE_HOME / "state.db")).expanduser()
    return Config(
        api_key=api_key,
        base_url=base_url,
        poll_interval_s=int(watch.get("poll_interval_s", 300)),
        max_concurrency=max(1, int(watch.get("max_concurrency", 5))),
        bootstrap_lookback_s=int(watch.get("bootstrap_lookback_s", 86400)),
        full_refresh_every=max(1, int(watch.get("full_refresh_every", 12))),
        command_ttl_s=int(watch.get("command_ttl_s", 600)),
        default_mode=default_mode,
        policy=base_policy,
        budgets=budgets,
        sources=sources,
        notify=notify,
        publish=publish,
        relay=relay,
        state_path=state_path,
        log_dir=Path(state.get("log_dir", state_path.parent / "logs")).expanduser(),
        lock_path=state_path.parent / "watch.lock",
    )
