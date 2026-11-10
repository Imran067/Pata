#!/usr/bin/env python3
"""Check your Gnani key and Evon server before the demo.

Spends a few credits: Timbre says one Tamil sentence, Prisma transcribes it back,
then Evon translates it to Hindi and pulls out the landmarks.

  python scripts/smoke_test_gnani.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import prompts  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.models import RelayOut  # noqa: E402
from app.services.evon import EvonClient, EvonError  # noqa: E402
from app.services.prisma import PrismaClient, SpeechError  # noqa: E402
from app.services.timbre import TimbreClient  # noqa: E402

LINE = "முருகன் கோவில் எதிரே, அப்போலோ பார்மசி பக்கத்துல, பச்சை கலர் பில்டிங்."


async def check_speech(settings, http) -> bool:
    if not settings.gnani_api_key:
        print("Prisma and Timbre: skipped, GNANI_API_KEY is empty in .env.")
        return False
    started = time.time()
    name = await TimbreClient(settings, http).speak(LINE, language="ta-IN", voice=settings.timbre_voice_customer)
    path = settings.audio_dir / name
    print(f"Timbre: {path.stat().st_size} bytes of Tamil speech in {time.time() - started:.1f}s, saved to {path}")
    started = time.time()
    heard = await PrismaClient(settings, http).transcribe(
        path.read_bytes(), languages=None, keyterms=["Apollo Pharmacy", "Murugan"],
        topic="A delivery rider and a customer talking about finding her building.")
    print(f"Prisma: detected {heard.language} in {time.time() - started:.1f}s and heard: {heard.text}")
    return True


async def check_evon(settings, http) -> bool:
    if not settings.evon_base_url:
        print("Evon: skipped, EVON_BASE_URL is empty in .env.")
        return False
    payload = {
        "speaker": "customer", "listener": "rider",
        "listener_language": "hi-IN", "listener_language_name": "Hindi", "listener_script": "Devanagari",
        "transcript": LINE, "recent_turns": [], "pending_question": None,
    }
    started = time.time()
    out = await EvonClient(settings, http).ask_json(prompts.RELAY, payload, RelayOut, thinking=False, max_tokens=900)
    print(f"Evon ({time.time() - started:.1f}s): {out.message_for_listener}")
    print(f"  in English: {out.gloss_en}")
    print(f"  Evon says she spoke: {out.speaker_language}")
    print(f"  landmarks: {[(lm.kind, lm.relation, lm.name_hint_en) for lm in out.landmarks]}")
    print(f"  building: {out.building.model_dump()}")
    return True


async def main() -> int:
    settings = load_settings()
    ok, checked = True, []
    async with httpx.AsyncClient() as http:
        try:
            checked.append(await check_speech(settings, http))
        except SpeechError as exc:
            ok = False
            print(f"Speech check failed: {exc}")
        try:
            checked.append(await check_evon(settings, http))
        except EvonError as exc:
            ok = False
            print(f"Evon check failed: {exc}")
    if ok and not any(checked):
        print("Nothing was checked: add GNANI_API_KEY and EVON_BASE_URL to .env first.")
        return 1
    print("All set." if ok else "Fix the errors above, then run this again.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
