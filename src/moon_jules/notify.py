"""Notificaciones nativas del sistema operativo. Epica E02.

`osascript` en macOS, `notify-send` en Linux, y un backend nulo en
cualquier otro sitio. La integracion es opcional y desactivable
(Inception §5); si no hay backend, Moon-Jules sigue funcionando y solo
lo anota una vez.

Nada de lo que llega aqui se pasa por un shell: los titulos de sesion
vienen del API y pueden contener comillas. `notify-send` recibe argv;
para AppleScript se escapa el literal.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from abc import ABC, abstractmethod

from .logs import get

log = get("notify")


class Backend(ABC):
    name = "none"

    @abstractmethod
    def send(self, title: str, body: str) -> bool:
        """Devuelve True si la notificacion salio."""

    @staticmethod
    def available() -> bool:
        return False


class NullBackend(Backend):
    def send(self, title: str, body: str) -> bool:
        return False

    @staticmethod
    def available() -> bool:
        return True


def _applescript_literal(text: str) -> str:
    """Escapa una cadena para incrustarla en un literal de AppleScript."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


class MacBackend(Backend):
    name = "osascript"

    @staticmethod
    def available() -> bool:
        return platform.system() == "Darwin" and bool(shutil.which("osascript"))

    def send(self, title: str, body: str) -> bool:
        script = (
            f'display notification "{_applescript_literal(body)}" '
            f'with title "{_applescript_literal(title)}"'
        )
        return _run(["osascript", "-e", script])


class LinuxBackend(Backend):
    name = "notify-send"

    @staticmethod
    def available() -> bool:
        return platform.system() == "Linux" and bool(shutil.which("notify-send"))

    def send(self, title: str, body: str) -> bool:
        # argv directo: sin shell, sin escapado que se nos pueda escapar.
        return _run(["notify-send", "--app-name=Moon-Jules", "--", title, body])


def _run(argv: list[str]) -> bool:
    try:
        subprocess.run(argv, check=True, capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug("fallo al notificar con %s: %s", argv[0], exc)
        return False


def detect() -> Backend:
    for cls in (MacBackend, LinuxBackend):
        if cls.available():
            return cls()
    return NullBackend()


class Notifier:
    """Notifica hallazgos, con supresion de repetidos.

    Sin supresion, una sesion colgada notificaria en cada ciclo: con
    intervalo de 300 s serian doce avisos por hora de la misma cosa, y
    el arquitecto silenciaria las notificaciones — que es peor que no
    tenerlas.
    """

    def __init__(
        self,
        store: object,
        *,
        enabled: bool = True,
        cooldown_s: int = 3600,
        backend: Backend | None = None,
    ) -> None:
        self.enabled = enabled
        self.cooldown_s = cooldown_s
        self.store = store
        self.backend = backend or detect()
        if enabled and self.backend.name == "none":
            log.info(
                "notificaciones activadas pero no hay backend nativo "
                "disponible en esta plataforma; se omiten"
            )

    def notify_findings(self, findings: list, now) -> int:
        """Notifica lo que requiere atencion. Devuelve cuantas salieron."""
        if not self.enabled or self.backend.name == "none":
            return 0
        sent = 0
        for f in findings:
            if not f.needs_attention:
                continue
            if not self.store.should_notify(
                f.session.name, f.verdict.value, now, self.cooldown_s
            ):
                continue
            title = f"Moon-Jules: {f.session.repo}"
            body = f"{f.session.title or f.session.id} — {f.reason}"
            if self.backend.send(title, body):
                self.store.record_notification(f.session.name, f.verdict.value, now)
                sent += 1
        return sent
