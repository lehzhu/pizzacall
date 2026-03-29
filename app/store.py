from __future__ import annotations

import asyncio

from app.models import SessionState


class InMemoryCallStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: SessionState) -> SessionState:
        async with self._lock:
            self._sessions[session.call_id] = session
            return session

    async def get(self, call_id: str) -> SessionState:
        async with self._lock:
            try:
                return self._sessions[call_id]
            except KeyError as exc:
                raise KeyError(f"unknown call_id: {call_id}") from exc

    async def update(self, session: SessionState) -> SessionState:
        async with self._lock:
            self._sessions[session.call_id] = session
            return session

    async def all(self) -> list[SessionState]:
        async with self._lock:
            return list(self._sessions.values())
