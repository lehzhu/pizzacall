from __future__ import annotations

import io
import math
import wave
from pathlib import Path

import httpx

from app.config import get_settings
from app.errors import ProviderConfigurationError, ProviderRequestError


class CartesiaTTS:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def synthesize_to_file(self, text: str, path: Path) -> Path:
        audio = await self.synthesize_wav(text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return path

    async def synthesize_wav(self, text: str) -> bytes:
        if not self.settings.cartesia_api_key:
            raise ProviderConfigurationError("CARTESIA_API_KEY is required for TTS synthesis.")
        return await self._cartesia_wav(text)

    async def synthesize_mulaw_frames(self, text: str, frame_ms: int = 20) -> list[bytes]:
        wav_bytes = await self.synthesize_wav(text)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_handle:
            sample_rate = wav_handle.getframerate()
            sample_width = wav_handle.getsampwidth()
            pcm = wav_handle.readframes(wav_handle.getnframes())
        if sample_width != 2:
            raise ValueError("expected 16-bit PCM audio")
        samples = _pcm_bytes_to_samples(pcm)
        if sample_rate != 8000:
            samples = _resample_samples(samples, sample_rate, 8000)
        mulaw = bytes(_linear_to_mulaw(sample) for sample in samples)
        frame_bytes = int(8000 * (frame_ms / 1000))
        return [mulaw[index : index + frame_bytes] for index in range(0, len(mulaw), frame_bytes)]

    async def _cartesia_wav(self, text: str) -> bytes:
        headers = {
            "X-API-Key": self.settings.cartesia_api_key or "",
            "Cartesia-Version": "2024-06-10",
            "Content-Type": "application/json",
        }
        payload = {
            "model_id": "sonic-2",
            "transcript": text,
            "voice": {"mode": "id", "id": self.settings.cartesia_voice_id},
            "output_format": {
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": 8000,
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post("https://api.cartesia.ai/tts/bytes", headers=headers, json=payload)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderRequestError(f"Cartesia TTS request failed: {exc}") from exc
            return response.content


def _pcm_bytes_to_samples(pcm: bytes) -> list[int]:
    return [int.from_bytes(pcm[index : index + 2], "little", signed=True) for index in range(0, len(pcm), 2)]


def _resample_samples(samples: list[int], source_rate: int, target_rate: int) -> list[int]:
    if source_rate == target_rate or not samples:
        return samples
    ratio = source_rate / target_rate
    target_length = max(1, int(len(samples) / ratio))
    return [samples[min(len(samples) - 1, int(index * ratio))] for index in range(target_length)]


def _linear_to_mulaw(sample: int) -> int:
    mu = 255.0
    normalized = max(-1.0, min(1.0, sample / 32768.0))
    magnitude = math.log1p(mu * abs(normalized)) / math.log1p(mu)
    signal = math.copysign(magnitude, normalized)
    encoded = int((signal + 1) / 2 * mu + 0.5)
    return (~encoded) & 0xFF
