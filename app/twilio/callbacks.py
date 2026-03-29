from __future__ import annotations

from typing import Any

from twilio.request_validator import RequestValidator

from app.agent.session import SessionStore
from app.config import Settings
from app.logging.events import EventLogger
from app.models import Outcome, Phase
from app.agent.result import ResultAssembler


class TwilioCallbackHandler:
    def __init__(self, store: SessionStore, event_logger: EventLogger, settings: Settings, result_assembler: ResultAssembler) -> None:
        self.store = store
        self.event_logger = event_logger
        self.settings = settings
        self.result_assembler = result_assembler

    def verify_signature(self, *, url: str, params: dict[str, Any], signature: str | None) -> bool:
        if not self.settings.twilio_auth_token:
            return True
        if not signature:
            return False
        validator = RequestValidator(self.settings.twilio_auth_token)
        return validator.validate(url, params, signature)

    async def handle_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        call_sid = payload.get("CallSid")
        call_status = payload.get("CallStatus", "")
        if not call_sid:
            return {"accepted": False, "reason": "missing CallSid"}
        session = await self.store.get_by_call_sid(call_sid)
        if session is None:
            return {"accepted": False, "reason": "unknown CallSid"}
        event_id = f"twilio_status:{call_sid}:{call_status}:{payload.get('Timestamp', '')}"

        def mutate(current_session) -> None:
            current_session.timestamps[f"status_{call_status}"] = payload.get("Timestamp", "")
            if call_status == "completed" and current_session.phase not in {Phase.completed, Phase.failed}:
                current_session.phase = Phase.failed
                current_session.subphase = "call_completed_before_valid_outcome"

        session = await self.store.apply_event(session.session_id, event_id, mutate)
        self.event_logger.log(
            session_id=session.session_id,
            call_sid=session.call_sid,
            stream_sid=session.stream_sid,
            phase=session.phase,
            event_type="twilio_status_callback",
            payload=payload,
        )
        if call_status == "completed" and session.final_result is None:
            result = self.result_assembler.from_session(
                session=session,
                outcome=Outcome.failed,
                notes=["Call ended before completion criteria were satisfied"],
            )
            await self.store.set_final_result(session.session_id, result)
        return {"accepted": True, "session_id": session.session_id}
