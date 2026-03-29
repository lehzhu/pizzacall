from __future__ import annotations

import json
from asyncio import Lock
from pathlib import Path
from typing import Any

from app.logging.events import EventLogger
from app.models import NormalizedOrderRequest, OrderResult, Phase, SessionState


class SessionStore:
    def __init__(self, event_logger: EventLogger, results_dir: Path) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._call_sid_to_session: dict[str, str] = {}
        self._stream_sid_to_session: dict[str, str] = {}
        self._lock = Lock()
        self._event_logger = event_logger
        self._results_dir = results_dir

    async def create(self, order_request: NormalizedOrderRequest) -> SessionState:
        session = SessionState(session_id=order_request.session_id, order_request=order_request)
        async with self._lock:
            self._sessions[session.session_id] = session
        self._event_logger.log(
            session_id=session.session_id,
            phase=session.phase,
            event_type="session_created",
            payload={"customer_name": order_request.customer_name},
        )
        return session

    async def get(self, session_id: str) -> SessionState | None:
        async with self._lock:
            return self._sessions.get(session_id)

    async def get_by_call_sid(self, call_sid: str) -> SessionState | None:
        async with self._lock:
            session_id = self._call_sid_to_session.get(call_sid)
            return self._sessions.get(session_id) if session_id else None

    async def bind_call_sid(self, session_id: str, call_sid: str) -> SessionState:
        async with self._lock:
            session = self._sessions[session_id]
            session.call_sid = call_sid
            self._call_sid_to_session[call_sid] = session_id
            return session

    async def bind_stream_sid(self, session_id: str, stream_sid: str) -> SessionState:
        async with self._lock:
            session = self._sessions[session_id]
            session.stream_sid = stream_sid
            self._stream_sid_to_session[stream_sid] = session_id
            return session

    async def apply_event(
        self,
        session_id: str,
        event_id: str,
        mutator: callable,
    ) -> SessionState:
        async with self._lock:
            session = self._sessions[session_id]
            if event_id in session.events_seen:
                return session
            session.events_seen.add(event_id)
            mutator(session)
            return session

    async def transition_phase(self, session_id: str, phase: Phase, subphase: str) -> SessionState:
        def mutator(session: SessionState) -> None:
            session.phase = phase
            session.subphase = subphase
            session.timestamps[f"phase_{phase.value}"] = session.timestamps.get(f"phase_{phase.value}") or session.timestamps["created_at"]

        return await self.apply_event(session_id, f"phase:{phase.value}:{subphase}", mutator)

    async def set_final_result(self, session_id: str, result: OrderResult) -> SessionState:
        def mutator(session: SessionState) -> None:
            session.final_result = result
            session.phase = Phase.completed if result.outcome == "completed" else session.phase

        session = await self.apply_event(session_id, f"final:{result.outcome}", mutator)
        path = self._results_dir / f"{session_id}.json"
        path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        self._event_logger.log(
            session_id=session.session_id,
            call_sid=session.call_sid,
            stream_sid=session.stream_sid,
            phase=session.phase,
            event_type="final_outcome",
            payload=result.model_dump(mode="json"),
        )
        return session

    async def snapshot(self, session_id: str) -> dict[str, Any]:
        session = await self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return json.loads(session.model_dump_json())
