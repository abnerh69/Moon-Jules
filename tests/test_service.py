"""Tests del arranque persistente. Épica E12.

`launchctl` no existe en este contenedor, así que lo que se prueba es lo
que se genera: rutas, argumentos y las tres precauciones que separan un
servicio que funciona de uno que llena el disco de logs.

Es la parte que más importa probar, precisamente porque la instalación
solo se verifica en la máquina del arquitecto y un plist mal formado
falla en silencio.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from moon_jules.service import (
    LABEL,
    THROTTLE_S,
    Entorno,
    aviso_sueno,
    plist,
    ruta_plist,
    ruta_unit,
    unit,
)

HOME = Path("/Users/arquitecto")
BIN = Path("/Users/arquitecto/Dev/Moon-Jules/.venv/bin/moon-jules")
LOGS = HOME / ".local/state/moon-jules/logs"


def entorno(**kw) -> Entorno:
    return Entorno(ejecutable=BIN, home=HOME, log_dir=LOGS, **kw)


def leer(env: Entorno) -> dict:
    return plistlib.loads(plist(env))


# --------------------------------------------------------------------
# lo que launchd necesita y no perdona
# --------------------------------------------------------------------


def test_el_plist_es_valido():
    """Un plist mal formado lo rechaza launchd sin explicar gran cosa."""
    assert leer(entorno())["Label"] == LABEL


def test_todas_las_rutas_son_absolutas():
    """launchd no expande `~` ni tiene directorio de trabajo heredado.

    Es el fallo más común al escribir uno de estos a mano.
    """
    d = leer(entorno())
    rutas = [
        d["ProgramArguments"][0], d["WorkingDirectory"],
        d["StandardOutPath"], d["StandardErrorPath"],
    ]
    for r in rutas:
        assert r.startswith("/"), f"ruta relativa: {r}"
        assert "~" not in r


def test_lleva_un_path_explicito():
    """El PATH de launchd es mínimo: sin esto, `osascript` o `security`
    fallarían en silencio al notificar o leer el llavero."""
    entorno_plist = leer(entorno())["EnvironmentVariables"]
    assert "/usr/bin" in entorno_plist["PATH"]
    assert entorno_plist["HOME"] == str(HOME)


def test_reintenta_pero_no_en_bucle_cerrado():
    """Un error de configuración —una credencial ausente— haría que el
    servicio muriera y renaciera sin pausa, llenando el disco de logs en
    minutos. `ThrottleInterval` es lo que lo impide."""
    d = leer(entorno())
    assert d["KeepAlive"] is True
    assert d["RunAtLoad"] is True
    assert d["ThrottleInterval"] >= 30 == THROTTLE_S


def test_el_servicio_corre_en_silencio():
    """Bajo launchd, la salida estándar va a un fichero que no rota. El
    log rotado ya recoge todo, así que la consola sobra."""
    assert "--quiet" in leer(entorno())["ProgramArguments"]


def test_el_config_a_medida_viaja_en_los_argumentos():
    args = leer(entorno(config=Path("/Users/arquitecto/otro.toml")))["ProgramArguments"]
    assert "--config" in args
    assert "/Users/arquitecto/otro.toml" in args
    assert args.index("--config") < args.index("watch")


def test_sin_config_a_medida_no_se_inventa_uno():
    assert "--config" not in leer(entorno())["ProgramArguments"]


# --------------------------------------------------------------------
# el sueño, que ningún servicio arregla
# --------------------------------------------------------------------


def test_caffeinate_envuelve_la_orden(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda self: True)
    args = entorno(caffeinate=True).argumentos
    assert args[0] == "/usr/bin/caffeinate"
    assert args[1] == "-i"
    assert str(BIN) in args


def test_sin_caffeinate_se_invoca_directo():
    assert entorno().argumentos[0] == str(BIN)


def test_si_no_hay_caffeinate_no_se_rompe(monkeypatch):
    """En Linux o en un macOS recortado, el binario puede no estar."""
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert entorno(caffeinate=True).argumentos[0] == str(BIN)


def test_el_aviso_del_sueno_no_se_esconde(monkeypatch):
    """Es un límite real, no una opción avanzada: cerrar la tapa duerme
    el portátil y ningún servicio lo impide."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    aviso = aviso_sueno()
    assert aviso and "tapa" in aviso
    assert "caffeinate" in aviso


def test_en_linux_no_se_avisa_de_la_tapa(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert aviso_sueno() is None


# --------------------------------------------------------------------
# systemd
# --------------------------------------------------------------------


def test_la_unidad_de_systemd_reinicia_con_pausa():
    texto = unit(entorno())
    assert "Restart=always" in texto
    assert f"RestartSec={THROTTLE_S}" in texto
    assert "WantedBy=default.target" in texto, "debe ser servicio de usuario"


def test_la_unidad_lleva_la_orden_completa():
    assert str(BIN) in unit(entorno())
    assert "watch --quiet" in unit(entorno())


def test_las_rutas_de_instalacion_son_de_usuario():
    """Servicio de usuario, no de sistema: Moon-Jules no necesita root y
    necesita el entorno del arquitecto (llavero, .env)."""
    assert "LaunchAgents" in str(ruta_plist())
    assert str(Path.home()) in str(ruta_plist())
    assert "systemd/user" in str(ruta_unit())


# --------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------


@pytest.mark.parametrize("accion", ["install", "uninstall", "status", "show"])
def test_las_acciones_del_servicio_se_parsean(accion: str):
    from moon_jules.cli import build_parser

    args = build_parser().parse_args(["service", accion])
    assert args.cmd == "service"
    assert args.accion == accion


def test_service_exige_una_accion():
    from moon_jules.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["service"])


def test_watch_admite_quiet():
    from moon_jules.cli import build_parser

    assert build_parser().parse_args(["watch", "--quiet"]).quiet is True
    assert build_parser().parse_args(["watch"]).quiet is False
