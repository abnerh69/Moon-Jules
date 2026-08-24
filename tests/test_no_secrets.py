"""Barrido de credenciales sobre todo el árbol del repositorio.

Este test existe por un incidente real: en la entrega 02 una credencial
del arquitecto llegó al repositorio dentro de un fixture de tests, y de
ahí a GitHub. El barrido manual existía, pero era manual — se hizo antes
de empaquetar la entrega 01 y no se repitió en la 02, justo cuando se
escribió el archivo que la introdujo.

La lección no es "acordarse de barrer". Es que un chequeo que depende de
que alguien se acuerde no es un chequeo. Por eso vive aquí, donde falla
solo, en cada `pytest`, sin que nadie tenga que recordarlo.

Reutiliza a propósito los mismos patrones que redactan los logs: si una
forma de credencial merece ocultarse al escribirla, merece bloquearse al
commitearla.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moon_jules.logs import PATTERNS

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "node_modules",
}
TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".txt", ".yml", ".yaml", ".json",
    ".cfg", ".ini", ".sh", ".env", ".example", "",
}


def source_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in p.relative_to(ROOT).parts):
            continue
        if p.suffix.lower() in TEXT_SUFFIXES or p.name.startswith("."):
            out.append(p)
    return out


def test_hay_algo_que_barrer():
    """Si el barrido no ve archivos, su silencio no significa nada."""
    assert len(source_files()) > 15


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.pattern[:14])
def test_ningun_archivo_contiene_una_credencial(pattern):
    culpables = []
    for path in source_files():
        try:
            texto = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, linea in enumerate(texto.splitlines(), 1):
            if pattern.search(linea):
                culpables.append(f"{path.relative_to(ROOT)}:{n}")
    assert not culpables, (
        "credencial con forma reconocible en el repositorio: "
        + ", ".join(culpables)
        + ". Si es un fixture de test, constrúyelo por concatenación "
        "(ver `fake()` en test_guardrails.py). Si es real, rótala ya: "
        "el valor queda en el historial de git aunque borres la línea."
    )


def test_el_env_no_esta_versionado():
    """El `.env` es el sitio correcto para el secreto, y no va al repo."""
    assert (ROOT / ".gitignore").read_text().splitlines().count(".env") == 1
    assert not (ROOT / ".env").exists(), (
        "hay un .env en el árbol de trabajo. Está en .gitignore, así que "
        "git no lo verá, pero no debe empaquetarse en una entrega."
    )


def test_el_ejemplo_no_lleva_valores_reales():
    """`.env.example` documenta las claves; los valores van vacíos."""
    ejemplo = ROOT / ".env.example"
    if not ejemplo.exists():
        pytest.skip("sin .env.example")
    for linea in ejemplo.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        _, _, valor = linea.partition("=")
        assert valor.strip() in ("", '""', "''"), (
            f"`.env.example` trae un valor: {linea}. Debe quedar vacío."
        )


def test_el_config_de_ejemplo_usa_referencias():
    """ADR-004: el config referencia el secreto, nunca lo contiene."""
    for linea in (ROOT / "config.example.toml").read_text().splitlines():
        limpia = linea.strip()
        if limpia.startswith("#") or "api_key" not in limpia:
            continue
        assert 'env:' in limpia or 'keychain:' in limpia, (
            f"api_key sin resolvedor en config.example.toml: {limpia}"
        )
