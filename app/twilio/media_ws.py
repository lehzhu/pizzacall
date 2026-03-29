from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.agent.session import SessionStore
from app.agent.state_machine import AgentStateMachine
from app.logging.events import EventLogger
from app.pipeline.live_session import LiveSessionManager


class MediaWebSocketHandler:
    def __init__(self, store: SessionStore, state_machine: AgentStateMachine, event_logger: EventLogger, live_sessions: LiveSessionManager) -> None:
        self.store = store
        self.state_machine = state_machine
        self.event_logger = event_logger
        self.live_sessions = live_sessions

    async def handle(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        session = await self.store.get(session_id)
        if session is None:
            await websocket.close(code=4404)
            return
        transition = self.state_machine.begin_live_call(session)
        await self.live_sessions.connect(session, websocket)
        self.event_logger.log(
            session_id=session_id,
            call_sid=session.call_sid,
            phase=transition.phase,
            event_type="media_websocket_connected",
            payload={"subphase": transition.subphase},
        )
        try:
            while True:
                message = await websocket.receive_text()
                payload = json.loads(message)
                await self._handle_event(session_id, payload)
        except WebSocketDisconnect as exc:
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="media_websocket_closed",
                payload={"error": f"disconnect:{exc.code}"},
            )
            await self.live_sessions.disconnect(session_id)
        except Exception as exc:
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="media_websocket_closed",
                payload={"error": str(exc)},
            )
            await self.live_sessions.disconnect(session_id)

    async def _handle_event(self, session_id: str, payload: dict[str, Any]) -> None:
        session = await self.store.get(session_id)
        if session is None:
            return
        event_type = payload.get("event")
        if event_type == "start":
            stream_sid = payload.get("start", {}).get("streamSid")
            if stream_sid:
                session = await self.store.bind_stream_sid(session_id, stream_sid)
            if session.pending_action and session.pending_action.type == "dtmf":
                session.pending_action = None
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=stream_sid,
                phase=session.phase,
                event_type="media_stream_start",
                payload=payload,
            )
            return
        if event_type == "stop":
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="media_stream_stop",
                payload=payload,
            )
            return
        if event_type == "media":
            media_payload = payload.get("media", {}).get("payload")
            if media_payload:
                await self.live_sessions.ingest_audio(session_id, __import__("base64").b64decode(media_payload))
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="media_frame_received",
                payload={"track": payload.get("media", {}).get("track")},
            )
            return
        if event_type == "mark":
            self.event_logger.log(
                session_id=session_id,
                call_sid=session.call_sid,
                stream_sid=session.stream_sid,
                phase=session.phase,
                event_type="media_mark",
                payload=payload.get("mark", {}),
            )
