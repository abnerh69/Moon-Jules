"""Doble del cliente de Jules, compartido por toda la suite.

Existía uno por archivo de tests, con las mismas cuatro operaciones
copiadas cuatro veces. Al añadir dos métodos al cliente real, los cuatro
se rompieron a la vez: la duplicación no ahorraba nada y costaba cada
vez que la superficie del cliente crecía.

Este doble implementa la superficie completa y además instrumenta lo que
los tests de coste necesitan medir: peticiones emitidas, paralelismo
alcanzado y con qué cursor se pidió cada cosa.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from moon_jules.errors import NotFoundError
from moon_jules.models import Activity, Session


class FakeJules:
    def __init__(
        self,
        sessions: list[Session],
        activities: dict[str, list[Activity]] | None = None,
        *,
        pages: int = 1,
        delay: float = 0.0,
    ) -> None:
        self._sessions = list(sessions)
        self._activities = dict(activities or {})
        #: Páginas que simula `sessions.list`, para contar peticiones.
        self.pages = pages
        self.delay = delay

        self.requests = 0
        self.sent: list[tuple[str, str]] = []
        self.approved: list[str] = []
        self.created: list[dict] = []
        #: (sesión, cursor) de cada consulta de actividades.
        self.activity_calls: list[tuple[str, str | None]] = []
        self.session_gets: list[str] = []
        self.since_calls: list[str] = []
        self._en_vuelo = 0
        self.pico = 0

    # ---------- utilidades para los tests ----------

    def replace_sessions(self, sessions: list[Session]) -> None:
        self._sessions = list(sessions)

    def set_activities(self, name: str, acts: list[Activity]) -> None:
        self._activities[name] = acts

    async def _viaje(self):
        self.requests += 1
        self._en_vuelo += 1
        self.pico = max(self.pico, self._en_vuelo)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
        finally:
            self._en_vuelo -= 1

    # ---------- superficie del cliente real ----------

    async def sources(self) -> list[dict]:
        await self._viaje()
        return []

    async def sessions(self, *, include_archived: bool = False) -> list[Session]:
        self.requests += self.pages - 1  # la primera la cuenta _viaje
        await self._viaje()
        return list(self._sessions)

    async def sessions_since(self, marca: datetime) -> list[Session]:
        """Compara datetimes, como el cliente real: comparar texto miente."""
        self.since_calls.append(marca)
        await self._viaje()
        return [s for s in self._sessions if s.create_time and s.create_time > marca]

    async def session(self, name: str) -> Session:
        self.session_gets.append(name)
        await self._viaje()
        for s in self._sessions:
            if s.name == name:
                return s
        raise NotFoundError(f"{name} no existe")

    async def activities(
        self, name: str, *, after: str | None = None, limit: int | None = None
    ) -> list[Activity]:
        self.activity_calls.append((name, after))
        await self._viaje()
        acts = self._activities.get(name, [])
        if after:
            corte = datetime.fromisoformat(after.replace("Z", "+00:00"))
            acts = [a for a in acts if a.create_time and a.create_time > corte]
        return sorted(acts, key=lambda a: a.create_time)

    async def send_message(self, name: str, prompt: str) -> None:
        await self._viaje()
        self.sent.append((name, prompt))

    async def approve_plan(self, name: str) -> None:
        await self._viaje()
        self.approved.append(name)

    async def create_session(self, prompt: str, **kw: object) -> Session:
        await self._viaje()
        self.created.append({"prompt": prompt, **kw})
        return self._sessions[0]
