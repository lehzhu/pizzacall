from __future__ import annotations

from urllib.parse import urlencode

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from app.config import get_settings
from app.errors import ProviderConfigurationError, ProviderRequestError
from app.models import Phase, SessionState


class TwilioAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = None
        if self.settings.twilio_account_sid and self.settings.twilio_auth_token:
            self.client = Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    async def start_outbound_call(self, session: SessionState) -> str:
        if not self.client or not self.settings.twilio_from_number:
            raise ProviderConfigurationError(
                "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER are required for outbound calling."
            )
        voice_url = f"{self.settings.public_base_url}/twilio/voice?{urlencode({'call_id': session.call_id})}"
        status_url = f"{self.settings.public_base_url}/twilio/status?{urlencode({'call_id': session.call_id})}"
        try:
            call = self.client.calls.create(
                to=session.store_phone_number,
                from_=self.settings.twilio_from_number,
                url=voice_url,
                status_callback=status_url,
                status_callback_event=["initiated", "ringing", "answered", "completed"],
            )
            return call.sid
        except TwilioRestException as exc:
            raise ProviderRequestError(f"Twilio outbound call failed: {exc.msg}") from exc

    def build_voice_response(self, session: SessionState) -> str:
        response = VoiceResponse()
        next_url = f"{self.settings.public_base_url}/twilio/voice?{urlencode({'call_id': session.call_id})}"
        if session.phase in {Phase.dialing, Phase.ivr_menu}:
            response.pause(length=1)
            response.play(digits="1")
            response.redirect(next_url)
            return str(response)
        if session.phase == Phase.ivr_name:
            response.play(self._artifact_url(session, "name.wav"))
            response.redirect(next_url)
            return str(response)
        if session.phase == Phase.ivr_callback:
            response.pause(length=1)
            response.play(digits="w" + session.input_order.phone_number)
            response.redirect(next_url)
            return str(response)
        if session.phase == Phase.ivr_zip:
            response.play(self._artifact_url(session, "zip.wav"))
            response.redirect(next_url)
            return str(response)
        if session.phase == Phase.ivr_confirm:
            response.play(self._artifact_url(session, "yes.wav"))
            response.redirect(next_url)
            return str(response)
        if session.phase in {Phase.transfer_wait, Phase.hold, Phase.human_greeting, Phase.human_ordering, Phase.human_confirming, Phase.closing}:
            connect = Connect()
            connect.stream(url=self._media_ws_url(session.call_id))
            response.append(connect)
            response.pause(length=600)
            return str(response)
        response.pause(length=1)
        return str(response)

    def _artifact_url(self, session: SessionState, filename: str) -> str:
        return f"{self.settings.public_base_url}/artifacts/{session.call_id}/{filename}"

    def _media_ws_url(self, call_id: str) -> str:
        base = self.settings.public_base_url
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1) + f"/ws/media/{call_id}"
        return base.replace("http://", "ws://", 1) + f"/ws/media/{call_id}"
