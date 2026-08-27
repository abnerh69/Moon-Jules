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
        backends: list[Backend] | None = None,
    ) -> None:
        self.enabled = enabled
        self.cooldown_s = cooldown_s
        self.store = store
        # Varias vias a la vez, no una que sustituye a la otra. Que
        # activar el push apagara el aviso local era un comportamiento
        # que el config no anunciaba, y dejo al arquitecto sin ninguna
        # alerta efectiva mientras el push no tenia destinatario.
        self.backends = [b for b in (backends or ([backend] if backend else [detect()]))
                         if b is not None]
        if enabled and not any(b.name != "none" for b in self.backends):
            log.info(
                "notificaciones activadas pero no hay ninguna via "
                "disponible en esta plataforma; se omiten"
            )

    @property
    def backend(self) -> Backend:
        """La primera via. Se conserva por comodidad de los tests."""
        return self.backends[0] if self.backends else NullBackend()

    def notify_findings(self, findings: list, now) -> int:
        """Notifica lo que requiere atencion. Devuelve cuantas salieron."""
        if not self.enabled or not self.backends:
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
            # Basta con que una via entregue para darlo por avisado: si
            # el push llego, repetirlo cada ciclo por que el portatil
            # estaba dormido seria ruido.
            entregado = [b.send(title, body) for b in self.backends]
            if any(entregado):
                self.store.record_notification(f.session.name, f.verdict.value, now)
                sent += 1
            elif self.backends:
                log.warning(
                    "ninguna via entrego el aviso de %s (%s): "
                    "revisa que haya dispositivos registrados",
                    f.session.repo,
                    f.verdict.value,
                )
        return sent

    def notify_sources(self, hallazgos: list, now) -> int:
        """Avisa de las cintas paradas.

        La suppresion se comparte con las sesiones usando el nombre del
        repositorio como clave: sin ella, un proyecto parado avisaria en
        cada ciclo hasta que alguien lo mirara.
        """
        if not self.enabled or not self.backends:
            return 0
        sent = 0
        for h in hallazgos:
            if not h.needs_attention:
                continue
            if not self.store.should_notify(
                h.source, h.verdict.value, now, self.cooldown_s
            ):
                continue
            title = f"Moon-Jules: {h.repo}"
            body = f"La cinta no avanza — {h.reason}"
            if any(b.send(title, body) for b in self.backends):
                self.store.record_notification(h.source, h.verdict.value, now)
                sent += 1
        return sent
