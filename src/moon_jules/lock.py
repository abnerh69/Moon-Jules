"""Lock de instancia unica. Epica E04, consecuencia de ADR-003.

Dos `watch` simultaneos sobre el mismo state.db se pisan de la peor
forma posible: ambos ven la misma sesion muda, ambos deciden nudgear, y
la sesion recibe el prompt dos veces. El presupuesto de tres nudges se
gasta en la mitad de ciclos y el contexto de la sesion se contamina el
doble. Por eso el segundo proceso falla con un mensaje claro en vez de
esperar en silencio.

`fcntl.flock` esta disponible en macOS y Linux, los dos unicos sistemas
que este proyecto soporta (NO 2 del Inception).
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from .errors import MoonJulesError


class AlreadyRunningError(MoonJulesError):
    """Otra instancia tiene el lock."""


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def acquire(self) -> InstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.seek(0)
            holder = fh.read().strip() or "desconocido"
            fh.close()
            raise AlreadyRunningError(
                f"ya hay un `moon-jules watch` corriendo (pid {holder}). "
                f"Si estas seguro de que no, borra {self.path}."
            ) from exc
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._fh = fh
        return self

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
            # El fichero se deja: su contenido es informativo y el lock
            # real lo lleva el kernel, no la existencia del archivo.

    def __enter__(self) -> InstanceLock:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
