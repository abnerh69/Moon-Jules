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
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import __version__
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


def localizar_ejecutable() -> Path:
    """El `moon-jules` que corresponde a *este* proceso.

    Resolver por PATH es incorrecto y falla en silencio: si el servicio
    se instala desde un shell sin el entorno virtual activo, `which`
    encuentra otra instalacion —la global de pyenv, por ejemplo— y el
    servicio queda ejecutando codigo distinto del que el arquitecto cree
    haber desplegado, de forma permanente.

    El orden correcto parte del proceso: el script de consola vive en el
    mismo `bin/` que el interprete que lo esta ejecutando.
    """
    candidatos: list[Path] = []
    invocado = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if invocado and invocado.name.startswith("moon-jules"):
        candidatos.append(invocado if invocado.is_absolute() else invocado.resolve())
    candidatos.append(Path(sys.executable).parent / "moon-jules")
    del_path = shutil.which("moon-jules")
    if del_path:
        candidatos.append(Path(del_path))

    for c in candidatos:
        if c.is_file():
            return c.resolve()
    raise MoonJulesError(
        "no encuentro el ejecutable `moon-jules`. Instala con "
        '`pip install -e "."` dentro del entorno virtual y vuelve a '
        "intentarlo desde ese mismo entorno."
    )


def verificar_version(binario: Path) -> str | None:
    """Version que reporta el binario, o None si no se pudo preguntar."""
    r = _correr([str(binario), "--version"])
    if r.returncode != 0:
        return None
    return r.stdout.strip().replace("moon-jules", "").strip() or None


def detectar(
    cfg_log_dir: Path,
    config: Path | None = None,
    *,
    caffeinate: bool = False,
    forzar: bool = False,
) -> Entorno:
    """Deduce el entorno del servicio desde el proceso actual.

    Comprueba ademas que el binario elegido sea el mismo codigo que esta
    corriendo. Si no lo es, el servicio ejecutaria otra version para
    siempre sin que nada lo delate.
    """
    binario = localizar_ejecutable()
    entorno_activo = os.environ.get("VIRTUAL_ENV")
    if (
        entorno_activo
        and not forzar
        and not str(binario).startswith(str(Path(entorno_activo).resolve()))
    ):
        # El caso que la comprobacion de version no detecta: un shim de
        # pyenv responde con la version del entorno activo aunque el
        # paquete al que apunta sea otro.
        raise MoonJulesError(
            f"hay un entorno virtual activo ({entorno_activo}) pero el "
            f"ejecutable elegido esta fuera de el:\n  {binario}\n"
            "El servicio quedaria apuntando a otra instalacion. Prueba "
            "`hash -r` y repite, o usa --force si es lo que quieres."
        )
    reportada = verificar_version(binario)
    if reportada and reportada != __version__ and not forzar:
        raise MoonJulesError(
            f"{binario} dice ser la version {reportada}, pero esta ejecutandose "
            f"la {__version__}. El servicio quedaria corriendo otra instalacion.\n"
            f"Activa el entorno virtual correcto y repite, o usa --force si "
            f"sabes lo que haces."
        )
    return Entorno(
        ejecutable=binario,
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


def _rechazar_root() -> None:
    """Este servicio es de usuario y con root no funciona.

    Bajo `sudo`, `os.getuid()` es 0 y el dominio `gui/0` no existe
    —launchctl responde "Domain does not support specified action"—, y
    ademas `Path.home()` pasa a ser `/var/root`, asi que el plist acaba
    en el sitio equivocado. Mejor negarse que dejar ese desorden.
    """
    if os.geteuid() != 0:
        return
    raise MoonJulesError(
        "no ejecutes esto con sudo. El servicio es de usuario: necesita tu "
        "sesion grafica, tu HOME y tu llavero.\n"
        "Si ya lo intentaste, limpia con:\n"
        "  sudo rm -f /var/root/Library/LaunchAgents/com.ashware.moonjules.plist"
    )


def _descargar(uid: int, espera: float = 3.0) -> None:
    """Descarga el servicio y espera a que desaparezca de verdad.

    `bootout` puede volver antes de que el proceso haya muerto, y
    entonces `bootstrap` falla con "Input/output error" porque la
    etiqueta sigue registrada. Ese error no dice nada de esto.
    """
    _correr(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if _correr(["launchctl", "print", f"gui/{uid}/{LABEL}"]).returncode != 0:
            return
        time.sleep(0.25)


def instalar(env: Entorno) -> Path:
    _rechazar_root()
    env.log_dir.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        destino = ruta_plist()
        destino.parent.mkdir(parents=True, exist_ok=True)
        uid = os.getuid()
        # Descargar ANTES de tocar el fichero: cambiar el plist bajo un
        # servicio cargado es lo que provoca el "Input/output error".
        _descargar(uid)
        destino.write_bytes(plist(env))
        r = _correr(["launchctl", "bootstrap", f"gui/{uid}", str(destino)])
        if r.returncode != 0:
            raise MoonJulesError(_explicar_launchctl(r, destino, uid))
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


def _explicar_launchctl(r: subprocess.CompletedProcess[str], plist_path: Path, uid: int) -> str:
    """launchctl explica poco. Se traduce lo que de verdad ocurre."""
    crudo = (r.stderr or r.stdout or "").strip()
    # El codigo se extrae con expresion regular y se compara como
    # numero: buscarlo como subcadena hace que "5:" case dentro de
    # "125:" y se de el consejo equivocado justo al error mas confuso.
    pistas = {
        5: (
            "el servicio seguia cargado. Descargalo a mano y repite:\n"
            f"  launchctl bootout gui/{uid}/{LABEL}"
        ),
        125: "estas en un dominio sin sesion grafica. No uses sudo.",
        112: "el plist esta mal formado o apunta a un ejecutable inexistente.",
    }
    m = re.search(r"failed:\s*(\d+)\s*:", crudo)
    if m and int(m.group(1)) in pistas:
        return f"launchctl rechazo el servicio ({crudo}).\n{pistas[int(m.group(1))]}"
    return (
        f"launchctl rechazo el servicio ({crudo or r.returncode}).\n"
        f"Revisa {plist_path} y el log en {ruta_plist().parent}."
    )


def desinstalar() -> bool:
    """Devuelve si habia algo que desinstalar."""
    _rechazar_root()
    if platform.system() == "Darwin":
        destino = ruta_plist()
        _descargar(os.getuid())
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
        salida = _campo(r.stdout, "last exit code = ")
        return {
            "sistema": "launchd",
            "cargado": True,
            "instalado": ruta_plist().exists(),
            "pid": _campo(r.stdout, "pid = "),
            # launchctl dice "(never exited)" en ingles y sin espacio.
            "ultima salida": (
                "nunca ha caido" if salida in (None, "(never exited)") else salida
            ),
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
