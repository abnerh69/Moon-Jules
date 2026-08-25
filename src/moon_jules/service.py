"""Arranque persistente. Épica E12.

Un `watch` en una pestaña de terminal muere al cerrar la terminal, al
cerrar la sesión y al dormirse la máquina. Eso deja un latido que
depende de que nadie toque nada, que es una forma elegante de no vigilar
nada.

Este módulo genera e instala el servicio de usuario que lo mantiene en
pie: `launchd` en macOS, `systemd --user` en Linux.

Hay un límite que conviene decir en voz alta en vez de esconderlo en una
opción: **en un portátil, cerrar la tapa duerme la máquina, y ningún
servicio lo impide.** `caffeinate -i` evita el sueño por inactividad, no
el de la tapa. Con el relevo de la entrega 14 eso no es catastrófico —la
app avisa y se designa otra—, pero conviene saberlo antes de confiar en
que la máquina de casa vigila mientras viajas.
"""

from __future__ import annotations

import os
import platform
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import MoonJulesError

LABEL = "com.ashware.moonjules"

#: Segundos que launchd espera antes de reintentar. Sin esto, un error
#: de configuracion —una credencial ausente, por ejemplo— produce un
#: bucle de reinicio que llena el disco de logs en minutos.
THROTTLE_S = 30


@dataclass(frozen=True)
class Entorno:
    """Todo lo que el servicio necesita saber para arrancar.

    Se resuelve a rutas absolutas a proposito: launchd no expande `~` ni
    hereda el PATH de la sesion interactiva, y el fallo mas comun al
    instalar esto a mano es un ejecutable que el servicio no encuentra.
    """

    ejecutable: Path
    home: Path
    log_dir: Path
    config: Path | None = None
    caffeinate: bool = False

    @property
    def argumentos(self) -> list[str]:
        args = [str(self.ejecutable)]
        if self.config:
            args += ["--config", str(self.config)]
        args += ["watch", "--quiet"]
        if self.caffeinate and Path("/usr/bin/caffeinate").exists():
            # `-i` evita el sueno por inactividad. No el de la tapa.
            return ["/usr/bin/caffeinate", "-i", *args]
        return args


def detectar(cfg_log_dir: Path, config: Path | None = None, *, caffeinate: bool = False):
    """Deduce el entorno del servicio desde el proceso actual."""
    binario = shutil.which("moon-jules")
    if not binario:
        # Instalado pero sin el script en PATH: se invoca el modulo.
        raise MoonJulesError(
            "no encuentro el ejecutable `moon-jules` en el PATH. "
            'Instala con `pip install -e "."` dentro del entorno virtual '
            "y vuelve a intentarlo desde ese mismo entorno."
        )
    return Entorno(
        ejecutable=Path(binario).resolve(),
        home=Path.home(),
        log_dir=cfg_log_dir,
        config=config.resolve() if config else None,
        caffeinate=caffeinate,
    )


# ---------- macOS ----------


def ruta_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist(env: Entorno) -> bytes:
    contenido = {
        "Label": LABEL,
        "ProgramArguments": env.argumentos,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": THROTTLE_S,
        "WorkingDirectory": str(env.home),
        "StandardOutPath": str(env.log_dir / "service.out"),
        "StandardErrorPath": str(env.log_dir / "service.err"),
        "EnvironmentVariables": {
            # El PATH de launchd es minimo: sin esto, cualquier
            # subproceso (osascript, security) fallaria en silencio.
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(env.home),
        },
    }
    return plistlib.dumps(contenido)


# ---------- Linux ----------


def ruta_unit() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "moon-jules.service"


def unit(env: Entorno) -> str:
    orden = " ".join(env.argumentos)
    return f"""[Unit]
Description=Moon-Jules: monitor del enjambre de Jules
After=network-online.target

[Service]
Type=simple
ExecStart={orden}
Restart=always
RestartSec={THROTTLE_S}
WorkingDirectory={env.home}
Environment=HOME={env.home}

[Install]
WantedBy=default.target
"""


# ---------- operaciones ----------


def _correr(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True)


def instalar(env: Entorno) -> Path:
    env.log_dir.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        destino = ruta_plist()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(plist(env))
        uid = os.getuid()
        # `bootout` antes de `bootstrap`: recargar sin descargar deja la
        # definicion vieja corriendo y confunde el diagnostico.
        _correr(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        r = _correr(["launchctl", "bootstrap", f"gui/{uid}", str(destino)])
        if r.returncode != 0:
            raise MoonJulesError(
                f"launchctl rechazo el servicio: {r.stderr.strip() or r.returncode}"
            )
        return destino
    if platform.system() == "Linux":
        destino = ruta_unit()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(unit(env), encoding="utf-8")
        _correr(["systemctl", "--user", "daemon-reload"])
        r = _correr(["systemctl", "--user", "enable", "--now", "moon-jules.service"])
        if r.returncode != 0:
            raise MoonJulesError(
                f"systemctl rechazo el servicio: {r.stderr.strip() or r.returncode}"
            )
        return destino
    raise MoonJulesError(
        f"no se como instalar un servicio en {platform.system()}. "
        "Moon-Jules soporta macOS y Linux (NO 2 del Inception)."
    )


def desinstalar() -> bool:
    """Devuelve si habia algo que desinstalar."""
    if platform.system() == "Darwin":
        destino = ruta_plist()
        _correr(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        if destino.exists():
            destino.unlink()
            return True
        return False
    if platform.system() == "Linux":
        destino = ruta_unit()
        _correr(["systemctl", "--user", "disable", "--now", "moon-jules.service"])
        if destino.exists():
            destino.unlink()
            _correr(["systemctl", "--user", "daemon-reload"])
            return True
        return False
    raise MoonJulesError(f"no soportado en {platform.system()}")


def estado() -> dict[str, object]:
    """Qué dice el sistema. `cargado` no implica que esté publicando."""
    sistema = platform.system()
    if sistema == "Darwin":
        r = _correr(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"])
        if r.returncode != 0:
            return {"sistema": "launchd", "cargado": False, "instalado": ruta_plist().exists()}
        pid = _campo(r.stdout, "pid = ")
        return {
            "sistema": "launchd",
            "cargado": True,
            "instalado": ruta_plist().exists(),
            "pid": pid,
            "ultima_salida": _campo(r.stdout, "last exit code = "),
        }
    if sistema == "Linux":
        r = _correr(["systemctl", "--user", "is-active", "moon-jules.service"])
        return {
            "sistema": "systemd",
            "cargado": r.stdout.strip() == "active",
            "instalado": ruta_unit().exists(),
            "estado": r.stdout.strip(),
        }
    return {"sistema": sistema, "cargado": False, "instalado": False}


def _campo(salida: str, prefijo: str) -> str | None:
    for linea in salida.splitlines():
        limpia = linea.strip()
        if limpia.startswith(prefijo):
            return limpia[len(prefijo):].strip()
    return None


def aviso_sueno() -> str | None:
    """Lo que ningún servicio arregla, dicho donde se lee."""
    if platform.system() != "Darwin":
        return None
    return (
        "Cerrar la tapa duerme el portatil y detiene el servicio. "
        "`--caffeinate` evita el sueno por inactividad, no el de la tapa. "
        "Si esta maquina debe vigilar sin supervision, dejala abierta y "
        "conectada, o cuenta con que el relevo se disparara."
    )


def python_del_entorno() -> str:
    return sys.executable
