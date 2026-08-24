"""Logging con redaccion de credenciales. ADR-004, epica E03.

La redaccion se hace en el *formatter*, no en un filtro, y a proposito:
el formatter ve la cadena final, incluyendo el traceback de una
excepcion y el repr de cualquier objeto interpolado. Un filtro solo ve
`msg` y `args`, y se le escapa justo el caso que mas duele — una
excepcion de httpx que arrastre la credencial en su representacion.

El modulo se llama `logs` y no `logging` para no sombrear al de la
biblioteca estandar dentro del paquete.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

MASK = "«redactado»"

#: Formas conocidas de credencial. Segunda linea de defensa: cubren el
#: caso de un secreto que llega al log por un camino que no previmos,
#: por ejemplo pegado por el usuario en un prompt de reactivacion.
PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),          # API keys de Google
    re.compile(r"AQ\.[0-9A-Za-z_\-]{20,}"),          # keys de Jules
    re.compile(r"gh[pousr]_[0-9A-Za-z]{20,}"),       # tokens de GitHub
    re.compile(r"github_pat_[0-9A-Za-z_]{20,}"),
)

#: Un secreto mas corto que esto no se redacta por valor: seria ruido.
#: (Un "x" de un test no puede convertir cada "x" del log en una mascara.)
MIN_SECRET_LEN = 12


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Sustituye credenciales por una mascara.

    Primero por valor exacto (lo que resolvimos del config), despues por
    forma conocida. El orden importa: el valor exacto es infalible, el
    patron es la red por si acaso.
    """
    for s in secrets:
        if s and len(s) >= MIN_SECRET_LEN:
            text = text.replace(s, MASK)
    for pat in PATTERNS:
        text = pat.sub(MASK, text)
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str, secrets: tuple[str, ...] = (), **kw: object) -> None:
        super().__init__(fmt, **kw)  # type: ignore[arg-type]
        self._secrets = tuple(s for s in secrets if s)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self._secrets)


FILE_FMT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
CONSOLE_FMT = "%(message)s"


def configure(
    *,
    secrets: tuple[str, ...] = (),
    log_dir: Path | None = None,
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    """Instala los handlers del proyecto. Idempotente."""
    root = logging.getLogger("moon_jules")
    root.setLevel(level)
    root.propagate = False
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(RedactingFormatter(CONSOLE_FMT, secrets))
        root.addHandler(ch)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_dir / "moon-jules.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(RedactingFormatter(FILE_FMT, secrets))
        root.addHandler(fh)

    return root


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"moon_jules.{name}")
