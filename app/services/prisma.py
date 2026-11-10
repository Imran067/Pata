"""Gnani Prisma v3.0, speech to text.

Each press-to-talk turn is one short clip (under 30 seconds), so the REST endpoint is
enough. Three Prisma features do real work here:
  * language_code=indic-auto on the customer's first turn: nobody picks a language;
    Prisma reports what it heard in detected_language_code.
  * keyterms: names of shops, temples and bus stops around the delivery pin, so local
    proper nouns come out right.
  * topic: one sentence telling Prisma this is a delivery call about finding a building.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from ..config import Settings


class SpeechError(RuntimeError):
    """Raised when Prisma or Timbre fails; the message is safe to show in the UI."""


@dataclass
class Transcript:
    text: str
    language: str | None
    source: str  # "prisma", "mock" or "typed"


class PrismaClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def transcribe(
        self,
        wav: bytes,
        *,
        languages: list[str] | None,
        keyterms: list[str],
        topic: str | None,
        role: str = "",
        session_id: str = "",
    ) -> Transcript:
        data = {
            "model": self.settings.prisma_model,
            "language_code": ",".join(languages[:4]) if languages else "indic-auto",
            "format": self.settings.prisma_format,
        }
        clean_terms = [t for t in keyterms if "<|" not in t and "|>" not in t][:200]
        if clean_terms:
            data["keyterms"] = json.dumps(clean_terms, ensure_ascii=False)
        if topic:
            data["topic"] = topic[:1600]
        try:
            response = await self.http.post(
                f"{self.settings.gnani_base_url}/stt/v3",
                headers={"X-API-Key-ID": self.settings.gnani_api_key},
                data=data,
                files={"audio_file": ("turn.wav", wav, "audio/wav")},
                timeout=60,
            )
        except httpx.HTTPError as exc:
            raise SpeechError(f"Could not reach Prisma ({exc.__class__.__name__}).") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise SpeechError(f"Prisma returned HTTP {response.status_code} without JSON.") from exc
        if not body.get("success"):
            error = body.get("error") or {}
            raise SpeechError(
                f"Prisma error {error.get('type', response.status_code)}: {error.get('message', 'no message')}"
            )
        return Transcript(
            text=(body.get("transcript") or "").strip(),
            language=body.get("detected_language_code"),
            source="prisma",
        )


class MockPrisma:
    """Returns the next demo-script line for the speaker, so the UI works without a key."""

    def __init__(self, script_lines: list[dict]):
        self.lines = {
            role: [line for line in script_lines if line["role"] == role]
            for role in ("rider", "customer")
        }
        self.position: dict[tuple[str, str], int] = {}

    async def transcribe(self, wav: bytes, *, role: str = "", session_id: str = "", **_: object) -> Transcript:
        lines = self.lines.get(role) or []
        if not lines:
            return Transcript(text="", language=None, source="mock")
        index = self.position.get((session_id, role), 0)
        self.position[(session_id, role)] = index + 1
        line = lines[index % len(lines)]
        return Transcript(text=line["text"], language=line["lang"], source="mock")
