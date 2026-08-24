"""Cliente del API de Jules (v1alpha).

Contrato verificado contra el API en vivo el 2026-08-24. Dos trampas que
este cliente evita y que cualquier implementacion copiada de la
documentacion publica repite:

1. El filtro incremental de actividades es `filter=create_time > "..."`.
   El parametro plano `?createTime=` que muestra el changelog de enero
   devuelve 400 INVALID_ARGUMENT.
2. Los errores se clasifican por codigo HTTP y `error.status`, NUNCA por
   el texto del mensaje: una API key revocada responde literalmente
   "API keys are not supported by this API", que es falso y manda a
   depurar el problema equivocado. NO 12 del Inception.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .errors import (
    AuthError,
    JulesError,
    NotFoundError,
    RateLimitedError,
    RequestInvalidError,
    TransientError,
)
from .models import Activity, Session

BASE_URL = "https://jules.googleapis.com/v1alpha"
PAGE_MAX = 100  # tope duro del API para sessions y activities


class JulesClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise AuthError("credencial vacia: revisa la configuracion")
        self._max_retries = max_retries
        self._latencies: list[float] = []
        self._http = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
        )

    @property
    def latencies(self) -> list[float]:
        """Milisegundos de cada peticion, para diagnostico."""
        return list(self._latencies)

    async def __aenter__(self) -> JulesClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- transporte ----------

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        """Traduce la respuesta a una excepcion de dominio.

        Clasifica por codigo y por `error.status`. El campo `message`
        solo se propaga como contexto para el humano, nunca como senal.
        """
        if resp.is_success:
            return
        try:
            err = (resp.json() or {}).get("error") or {}
        except ValueError:
            err = {}
        status = err.get("status") or ""
        msg = err.get("message") or resp.reason_phrase
        code = resp.status_code
        if code in (401, 403) or status == "UNAUTHENTICATED":
            raise AuthError(
                "credencial rechazada por el API. Revisa JULES_API_KEY; "
                "el mensaje del servidor puede ser enganoso.",
                status_code=code,
                api_status=status,
                detail=msg,
            )
        if code == 404 or status == "NOT_FOUND":
            raise NotFoundError(msg, status_code=code, api_status=status)
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            raise RateLimitedError(
                msg,
                status_code=code,
                api_status=status,
                retry_after=_retry_after(resp),
            )
        if code == 400 or status in ("INVALID_ARGUMENT", "FAILED_PRECONDITION"):
            raise RequestInvalidError(msg, status_code=code, api_status=status)
        if code >= 500:
            raise TransientError(msg, status_code=code, api_status=status)
        raise JulesError(msg, status_code=code, api_status=status)

    async def _request(self, method: str, path: str, **kw: Any) -> dict:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self._max_retries):
            t0 = time.monotonic()
            try:
                resp = await self._http.request(method, path, **kw)
                # Se mide cada intento por separado: promediar con las
                # esperas del backoff daria una latencia inventada.
                self._latencies.append((time.monotonic() - t0) * 1000)
                self._raise_for(resp)
                return resp.json() if resp.content else {}
            except (RateLimitedError, TransientError) as exc:
                last = exc
                wait = getattr(exc, "retry_after", None) or delay
                if attempt == self._max_retries - 1:
                    break
                await asyncio.sleep(wait)
                delay *= 2
            except httpx.TransportError as exc:
                last = TransientError(f"fallo de red: {exc}")
                if attempt == self._max_retries - 1:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise last if last else JulesError("fallo desconocido")

    async def _paginate(
        self, path: str, key: str, params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict]:
        token: str | None = None
        while True:
            q = dict(params or {})
            q["pageSize"] = PAGE_MAX
            if token:
                q["pageToken"] = token
            data = await self._request("GET", path, params=q)
            for item in data.get(key) or []:
                yield item
            token = data.get("nextPageToken")
            if not token:
                return

    # ---------- recursos ----------

    async def sources(self) -> list[dict]:
        return [s async for s in self._paginate("/sources", "sources")]

    async def sessions(self, *, include_archived: bool = False) -> list[Session]:
        """Poll global. ADR-001.

        `sessions.list` no filtra por source ni por estado; su unico
        filtro es `archived`, y sin filtro devuelve solo las activas.
        """
        params = (
            {"filter": "archived = true OR archived = false"} if include_archived else {}
        )
        return [
            Session.from_api(raw)
            async for raw in self._paginate("/sessions", "sessions", params)
        ]

    async def session(self, name: str) -> Session:
        return Session.from_api(await self._request("GET", f"/{_norm(name)}"))

    async def activities(
        self, name: str, *, after: str | None = None, limit: int | None = None
    ) -> list[Activity]:
        """Actividades de una sesion, en orden ascendente por createTime.

        `after` es el cursor: el `createTime` maximo ya visto. El filtro
        con `>` es EXCLUSIVO (verificado), asi que el cursor se pasa tal
        cual, sin restarle delta.
        """
        params = {"filter": f'create_time > "{after}"'} if after else {}
        out: list[Activity] = []
        async for raw in self._paginate(f"/{_norm(name)}/activities", "activities", params):
            out.append(Activity.from_api(raw))
            if limit and len(out) >= limit:
                break
        out.sort(key=lambda a: (a.create_time is None, a.create_time))
        return out

    # ---------- escrituras ----------

    async def send_message(self, name: str, prompt: str) -> None:
        """Envia un mensaje a una sesion activa. Respuesta vacia."""
        await self._request(
            "POST", f"/{_norm(name)}:sendMessage", json={"prompt": prompt}
        )

    async def approve_plan(self, name: str) -> None:
        await self._request("POST", f"/{_norm(name)}:approvePlan", json={})

    async def create_session(
        self,
        prompt: str,
        *,
        source: str,
        starting_branch: str,
        title: str | None = None,
        auto_pr: bool = True,
    ) -> Session:
        body: dict[str, Any] = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {"startingBranch": starting_branch},
            },
            "requirePlanApproval": False,
        }
        if title:
            body["title"] = title
        if auto_pr:
            body["automationMode"] = "AUTO_CREATE_PR"
        return Session.from_api(await self._request("POST", "/sessions", json=body))


def _norm(name: str) -> str:
    return name if name.startswith("sessions/") else f"sessions/{name}"


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
