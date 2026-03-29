from __future__ import annotations

from dataclasses import dataclass

from twilio.rest import Client
from twilio.twiml.voice_response import Redirect, VoiceResponse

from app.config import Settings
from app.logging.events import EventLogger
from app.models import NormalizedOrderRequest, SessionState


@dataclass(slots=True)
class CallCreateResult:
    call_sid: str
    status: str


class CallOrchestrator:
    def __init__(self, settings: Settings, event_logger: EventLogger) -> None:
        self.settings = settings
        self.event_logger = event_logger

    def _client(self) -> Client:
        return Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    def create_outbound_call(self, order: NormalizedOrderRequest) -> CallCreateResult:
        if not all([self.settings.twilio_account_sid, self.settings.twilio_auth_token, self.settings.twilio_from_number]):
            call_sid = f"mock-{order.session_id}"
            self.event_logger.log(
                session_id=order.session_id,
                phase="dialing",
                event_type="twilio_call_created_mock",
                payload={"to": order.destination_number_e164},
                call_sid=call_sid,
            )
            return CallCreateResult(call_sid=call_sid, status="queued")
        call = self._client().calls.create(
            to=order.destination_number_e164,
            from_=self.settings.twilio_from_number,
            url=f"{self.settings.public_base_url}/twilio/voice?session_id={order.session_id}",
            status_callback=f"{self.settings.public_base_url}/twilio/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        self.event_logger.log(
            session_id=order.session_id,
            phase="dialing",
            event_type="twilio_call_created",
            payload={"to": order.destination_number_e164, "status": call.status},
            call_sid=call.sid,
        )
        return CallCreateResult(call_sid=call.sid, status=call.status)

    def _update_call_twiml(self, *, call_sid: str, twiml: str) -> None:
        if call_sid.startswith("mock-"):
            return
        self._client().calls(call_sid).update(twiml=twiml)

    async def redirect_call_for_dtmf(self, session: SessionState, digits: str) -> None:
        if session.call_sid is None:
            return
        url = f"{self.settings.public_base_url}/twilio/action/{session.session_id}?digits={digits}"
        response = VoiceResponse()
        response.redirect(url=url, method="POST")
        self._update_call_twiml(call_sid=session.call_sid, twiml=str(response))
