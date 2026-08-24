"""Compatibilidad con la versión mínima de Python declarada.

La suite corre en el intérprete del contenedor, no en el del arquitecto.
`pyproject.toml` declara `>=3.11` y este proyecto se opera en macOS,
donde 3.11 sigue siendo habitual.

Ya pasó una vez: un salto de línea dentro de un f-string es sintaxis
válida desde 3.12 (PEP 701) y **error de sintaxis** en 3.11. Los tests
pasaban porque el contenedor era 3.12; en la máquina del arquitecto el
módulo no habría llegado ni a importarse.

El primer intento de test usó `ast.parse(feature_version=(3, 11))` y no
servía: PEP 701 es un cambio del tokenizador, y `feature_version` solo
gobierna el parser — se comprobó que acepta la sintaxis nueva sin
rechistar. Quien sí lo detecta es ruff con `--target-version`, así que
el test se apoya en ruff y no en una suposición.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBJETIVOS = [d for d in ("src", "tests", "tools") if (ROOT / d).is_dir()]


def version_minima() -> tuple[int, int]:
    datos = tomllib.loads((ROOT / "pyproject.toml").read_text())
    crudo = datos["project"]["requires-python"].lstrip(">=~^ ")
    mayor, menor = crudo.split(".")[:2]
    return int(mayor), int(menor)


def _ruff(args: list[str]) -> subprocess.CompletedProcess[str]:
    binario = shutil.which("ruff")
    orden = [binario, *args] if binario else [sys.executable, "-m", "ruff", *args]
    return subprocess.run(orden, capture_output=True, text=True, cwd=ROOT)


def _hay_ruff() -> bool:
    try:
        return _ruff(["--version"]).returncode == 0
    except OSError:
        return False


def test_el_proyecto_declara_una_version_minima():
    assert version_minima() >= (3, 11)


def test_no_hay_sintaxis_posterior_a_la_version_minima():
    """El gate real: falla si un fuente usa sintaxis de una versión
    posterior a la declarada, aunque el intérprete que corre la acepte."""
    if not _hay_ruff():
        pytest.skip("ruff no disponible")
    mayor, menor = version_minima()
    # `--select` se acota a una regla irrelevante a proposito: los
    # errores de sintaxis se reportan siempre, y asi este test falla por
    # incompatibilidad de version y no por deuda de estilo, que es otra
    # conversacion y tiene su propio comando.
    proc = _ruff([
        "check", "--target-version", f"py{mayor}{menor}",
        "--select", "F401", "--no-cache", *OBJETIVOS,
    ])
    incompatibles = [
        linea for linea in proc.stdout.splitlines()
        if "invalid-syntax" in linea or "SyntaxError" in linea
    ]
    assert not incompatibles, (
        f"sintaxis incompatible con py{mayor}{menor}:\n" + "\n".join(incompatibles)
    )


def test_la_configuracion_de_ruff_apunta_a_la_version_minima():
    """Si divergen, el linter del día a día deja pasar lo que rompe en la
    máquina del arquitecto."""
    datos = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert datos["tool"]["ruff"]["target-version"] == "py{}{}".format(*version_minima())
