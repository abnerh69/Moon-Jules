"""Excepciones de dominio.

Se clasifican por codigo HTTP y por `error.status` del API, nunca por el
texto del mensaje. Ver NO 12 del Inception y ADR-004.
"""

from __future__ import annotations


class MoonJulesError(Exception):
    """Raiz de todos los errores del proyecto."""


class ConfigError(MoonJulesError):
    """Configuracion ausente, mal formada o con un secreto literal."""


class JulesError(MoonJulesError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        api_status: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_status = api_status
        self.detail = detail

    def __str__(self) -> str:
        base = super().__str__()
        bits = [b for b in (self.api_status, self.detail) if b]
        return f"{base} ({'; '.join(bits)})" if bits else base


class AuthError(JulesError):
    """401/403. El mensaje del servidor es enganoso; no propagarlo solo."""


class NotFoundError(JulesError):
    """404."""


class RequestInvalidError(JulesError):
    """400 INVALID_ARGUMENT o FAILED_PRECONDITION. No se reintenta."""


class RateLimitedError(JulesError):
    """429. Reintentable con espera."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: object) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.retry_after = retry_after


class TransientError(JulesError):
    """5xx o fallo de red. Reintentable."""
