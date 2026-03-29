from __future__ import annotations

from twilio.twiml.voice_response import Play, Redirect, VoiceResponse


def build_stream_twiml(*, websocket_url: str) -> str:
    response = VoiceResponse()
    connect = response.connect()
    connect.stream(url=websocket_url)
    return str(response)


def build_dtmf_redirect_twiml(*, digits: str, redirect_url: str) -> str:
    response = VoiceResponse()
    response.play(digits=digits)
    response.redirect(url=redirect_url, method="POST")
    return str(response)
