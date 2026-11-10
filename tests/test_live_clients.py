"""The live clients, tested against fake Gnani and Evon servers (no network, no credits)."""
import asyncio
import json

import httpx
import pytest

from app.config import load_settings
from app.models import RelayOut, SayOut
from app.services.evon import EvonClient, EvonError, extract_json
from app.services.prisma import PrismaClient, SpeechError
from app.services.timbre import TimbreClient


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.setenv("EVON_BASE_URL", "http://evon.test/v1")
    monkeypatch.setenv("PATA_DATA_DIR", str(tmp_path))
    return load_settings()


def run(coro):
    return asyncio.run(coro)


def test_prisma_sends_auto_detect_keyterms_and_topic(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["X-API-Key-ID"]
        seen["body"] = request.content
        return httpx.Response(200, json={"success": True, "transcript": "முருகன் கோவில் எதிரே",
                                         "detected_language_code": "ta-IN"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await PrismaClient(settings, http).transcribe(
                b"RIFF....", languages=None, keyterms=["Apollo Pharmacy", "bad <|term|>"], topic="Delivery call")

    result = run(go())
    assert result.text.startswith("முருகன்") and result.language == "ta-IN"
    assert seen["url"].endswith("/stt/v3") and seen["key"] == "test-key"
    body = seen["body"].decode("utf-8", "ignore")
    assert "prisma-v3.0" in body and "indic-auto" in body and "Delivery call" in body
    assert "Apollo Pharmacy" in body and "<|term|>" not in body


def test_prisma_error_is_readable(settings):
    def handler(request):
        return httpx.Response(400, json={"success": False, "error": {"type": "INVALID_CONTEXT", "message": "too long"}})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await PrismaClient(settings, http).transcribe(b"x", languages=["hi-IN"], keyterms=[], topic=None)

    with pytest.raises(SpeechError, match="INVALID_CONTEXT"):
        run(go())


def test_timbre_writes_and_caches_audio(settings):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=b"RIFF" + b"\0" * 200, headers={"content-type": "audio/wav"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = TimbreClient(settings, http)
            first = await client.speak("<slow> सीधे जाइए", language="hi-IN", voice="Yashraj")
            second = await client.speak("<slow> सीधे जाइए", language="hi-IN", voice="Yashraj")
            return first, second

    first, second = run(go())
    assert first == second and len(calls) == 1
    assert calls[0]["model"] == "timbre-v3.0" and calls[0]["language"] == "hi-IN"
    assert calls[0]["audio_config"]["container"] == "wav"
    assert (settings.audio_dir / first).read_bytes()[:4] == b"RIFF"


def test_timbre_json_error_raises(settings):
    def handler(request):
        return httpx.Response(400, json={"detail": "voice not available for model"})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await TimbreClient(settings, http).speak("hi", language="en-IN", voice="Nope")

    with pytest.raises(SpeechError, match="voice not available"):
        run(go())


def test_extract_json_handles_thinking_and_fences():
    reply = '<think>She means the temple...</think>\nHere you go:\n```json\n{"say": "ठीक है"}\n```'
    assert extract_json(reply) == {"say": "ठीक है"}
    assert extract_json('reasoning...</think>{"say": "ok"}') == {"say": "ok"}


def test_evon_sets_thinking_flag_and_repairs_bad_json(settings):
    bodies = []
    replies = iter(["Sure! The answer is: none", '{"say": "सीधे 450 मीटर", "gloss_en": "450 m ahead"}'])

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await EvonClient(settings, http).ask_json("system", {"x": 1}, SayOut, thinking=True, max_tokens=50)

    out = run(go())
    assert out.say.startswith("सीधे")
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert bodies[1]["chat_template_kwargs"] == {"enable_thinking": False}  # the repair turn
    assert bodies[1]["messages"][-1]["role"] == "user"


def test_evon_retries_without_thinking_when_budget_runs_out(settings):
    replies = iter(["", '{"message_for_listener": "बस स्टॉप के पास", "landmarks": []}'])
    flags = []

    def handler(request):
        flags.append(json.loads(request.content)["chat_template_kwargs"]["enable_thinking"])
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies), "reasoning_content": "..."}}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await EvonClient(settings, http).ask_json("s", {}, RelayOut, thinking=True, max_tokens=10)

    assert run(go()).message_for_listener == "बस स्टॉप के पास"
    assert flags == [True, False]


def test_evon_unreachable_is_a_clear_error(settings):
    def handler(request):
        raise httpx.ConnectError("refused")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await EvonClient(settings, http).ask_json("s", {}, SayOut, thinking=False, max_tokens=10)

    with pytest.raises(EvonError, match="Could not reach Evon"):
        run(go())


def test_json_mode_is_used_for_quick_json_replies_only(settings):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"say": "ঠিক আছে", "gloss_en": "ok"}'}}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = EvonClient(settings, http)
            await client.ask_json("s", {}, SayOut, thinking=False, max_tokens=50)
            await client.ask_json("s", {}, SayOut, thinking=True, max_tokens=50)
            await client.chat([{"role": "user", "content": "translate this"}], thinking=False, max_tokens=50)

    run(go())
    assert bodies[0]["response_format"] == {"type": "json_object"} and bodies[0]["temperature"] == 0.3
    assert "response_format" not in bodies[1]  # with reasoning on, the grammar would constrain the thinking
    assert "response_format" not in bodies[2]  # plain-text translation
    assert all("repetition_penalty" not in body for body in bodies)
