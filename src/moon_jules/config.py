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
from .models import AutonomyMode

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "moon-jules"
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "moon-jules"
CONFIG_PATH = CONFIG_HOME / "config.toml"

RESOLVERS = ("env:", "keychain:")


@dataclass(frozen=True)
class SourceConfig:
    name: str
    mode: AutonomyMode = AutonomyMode.READ_ONLY
    starting_branch: str = "main"
    policy: Policy = field(default_factory=Policy)


@dataclass(frozen=True)
class Budgets:
    """Topes del plan Jules in Pro. ADR-005."""

    max_active_sessions: int = 15
    daily_session_budget: int = 100
    reserve_for_manual: int = 20

    @property
    def usable_daily(self) -> int:
        return max(0, self.daily_session_budget - self.reserve_for_manual)


@dataclass(frozen=True)
class NotifyConfig:
    enabled: bool = False
    cooldown_s: int = 3600


@dataclass(frozen=True)
class Config:
    api_key: str
    poll_interval_s: int = 300
    default_mode: AutonomyMode = AutonomyMode.READ_ONLY
    policy: Policy = field(default_factory=Policy)
    budgets: Budgets = field(default_factory=Budgets)
    sources: dict[str, SourceConfig] = field(default_factory=dict)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    state_path: Path = field(default=STATE_HOME / "state.db")
    log_dir: Path = field(default=STATE_HOME / "logs")
    lock_path: Path = field(default=STATE_HOME / "watch.lock")

    def for_source(self, source: str | None) -> SourceConfig:
        if source and source in self.sources:
            return self.sources[source]
        return SourceConfig(name=source or "", mode=self.default_mode, policy=self.policy)

    @property
    def secrets(self) -> tuple[str, ...]:
        """Valores a redactar en logs. Ver logging.redactor."""
        return tuple(s for s in (self.api_key,) if s)


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
            f'{field_name} = "env:JULES_API_KEY" o "keychain:moon-jules/jules". '
            "Ver ADR-004."
        )
    kind, _, rest = ref.partition(":")
    if kind == "env":
        val = os.environ.get(rest, "")
        if not val:
            raise ConfigError(
                f"la variable de entorno {rest} no esta definida. "
                f"Exportala con: read -rs {rest} && export {rest}"
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


def load(path: Path | None = None) -> Config:
    p = path or CONFIG_PATH
    if not p.exists():
        raise ConfigError(
            f"no existe {p}. Copia config.example.toml ahi y ajusta los valores."
        )
    with p.open("rb") as fh:
        raw = tomllib.load(fh)

    jules = raw.get("jules") or {}
    api_key = resolve_secret(jules.get("api_key", ""))

    watch = raw.get("watch") or {}
    base_policy = _policy_from(watch, Policy())
    default_mode = AutonomyMode(watch.get("default_mode", "read_only"))

    b = raw.get("budgets") or {}
    budgets = Budgets(
        max_active_sessions=int(b.get("max_active_sessions", 15)),
        daily_session_budget=int(b.get("daily_session_budget", 100)),
        reserve_for_manual=int(b.get("reserve_for_manual", 20)),
    )

    sources: dict[str, SourceConfig] = {}
    for name, sraw in (raw.get("sources") or {}).items():
        sources[name] = SourceConfig(
            name=name,
            mode=AutonomyMode(sraw.get("mode", default_mode.value)),
            starting_branch=sraw.get("starting_branch", "main"),
            policy=_policy_from(sraw, base_policy),
        )

    n = raw.get("notify") or {}
    notify = NotifyConfig(
        enabled=bool(n.get("enabled", False)),
        cooldown_s=int(n.get("cooldown_s", 3600)),
    )

    state = raw.get("state") or {}
    state_path = Path(state.get("path", STATE_HOME / "state.db")).expanduser()
    return Config(
        api_key=api_key,
        poll_interval_s=int(watch.get("poll_interval_s", 300)),
        default_mode=default_mode,
        policy=base_policy,
        budgets=budgets,
        sources=sources,
        notify=notify,
        state_path=state_path,
        log_dir=Path(state.get("log_dir", state_path.parent / "logs")).expanduser(),
        lock_path=state_path.parent / "watch.lock",
    )
