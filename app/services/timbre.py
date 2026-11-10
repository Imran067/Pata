"""Gnani Timbre v3.0, text to speech.

Every Timbre v3.0 voice speaks all ten supported languages, so one voice per listener is
enough. Text can carry inline audio tags such as <slow> and <pauses>; Pata uses <slow>
for directions a rider hears in traffic.

Audio is cached on disk by (model, voice, language, text): the AI disclosure line and any
repeated phrase cost credits only once.
"""
from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path

import httpx

from ..config import Settings
from .prisma import SpeechError


def _cache_name(*parts: object) -> str:
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{digest}.wav"


class TimbreClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http
        self.dir = Path(settings.audio_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    async def speak(self, text: str, *, language: str, voice: str) -> str:
        """Synthesise `text` and return the cached file name inside the audio directory."""
        s = self.settings
        name = _cache_name(s.timbre_model, voice, language, s.timbre_sample_rate, text)
        path = self.dir / name
        if path.exists() and path.stat().st_size > 44:
            return name
        payload = {
            "text": text,
            "voice": voice,
            "model": s.timbre_model,
            "language": language,
            "audio_config": {
                "sample_rate": s.timbre_sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "wav",
            },
        }
        try:
            response = await self.http.post(
                f"{s.gnani_base_url}/api/v1/tts/inference",
                headers={"X-API-Key-ID": s.gnani_api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise SpeechError(f"Could not reach Timbre ({exc.__class__.__name__}).") from exc
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or "json" in content_type or len(response.content) <= 44:
            detail = response.text[:300] if "json" in content_type or response.status_code != 200 else "empty audio"
            raise SpeechError(f"Timbre error (HTTP {response.status_code}): {detail}")
        path.write_bytes(response.content)
        return name


class MockTimbre:
    """Writes a short two-note chime instead of speech, so audio playback can be tested."""

    def __init__(self, settings: Settings):
        self.dir = Path(settings.audio_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    async def speak(self, text: str, *, language: str, voice: str) -> str:
        name = _cache_name("mock-chime-v1")
        path = self.dir / name
        if not path.exists():
            rate, frames = 16000, []
            for freq, length in ((660, 0.09), (880, 0.12)):
                count = int(rate * length)
                for i in range(count):
                    fade = min(1.0, i / 200, (count - i) / 200)
                    frames.append(int(6000 * fade * math.sin(2 * math.pi * freq * i / rate)))
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(rate)
                out.writeframes(struct.pack(f"<{len(frames)}h", *frames))
        return name
