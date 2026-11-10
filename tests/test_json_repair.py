"""Evon's replies when the server isn't enforcing JSON mode: repaired locally, salvaged if hopeless."""
import asyncio
import json

import httpx
import pytest

from app.config import load_settings
from app.models import RelayOut
from app.services.evon import EvonClient, EvonError, extract_json, repair_json, salvage

# The reply behind "Expecting ',' delimiter: line 3 column 3": a comma missing after the first field.
MISSING_COMMA = (
    '{\n  "message_for_listener": "দাদা, আপনি SN Bose-এর সামনে আসুন।"\n'
    '  "gloss_en": "Brother, please come in front of SN Bose.",\n'
    '  "landmarks": [{"heard": "SN Bose", "kind": "hostel", "relation": "in_front_of", "name_hint_en": "SN Bose"}],\n'
    '  "building": {"colour": null, "entrance": null, "floor": null, "name": null, "other": null},\n'
    '  "answer_option_id": null,\n  "speaker_language": "hi-IN"\n}'
)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.setenv("EVON_BASE_URL", "http://evon.test/v1")
    monkeypatch.setenv("PATA_DATA_DIR", str(tmp_path))
    return load_settings()


def ask(settings, replies):
    """Run one RelayOut request against a fake Evon that gives these replies in turn."""
    calls = []
    replies = iter(replies)

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await EvonClient(settings, http).ask_json("s", {}, RelayOut, thinking=False, max_tokens=50)

    return asyncio.run(go()), calls


def test_reported_missing_comma_is_repaired_without_asking_again(settings):
    out, calls = ask(settings, [MISSING_COMMA])
    assert out.message_for_listener == "দাদা, আপনি SN Bose-এর সামনে আসুন।"
    assert out.landmarks[0].name_hint_en == "SN Bose"
    assert len(calls) == 1  # fixed locally: no second, slower model call


@pytest.mark.parametrize("raw, expected", [
    ('{"a": "x" "b": "y"}', {"a": "x", "b": "y"}),
    ('{"a": [{"k": 1}\n {"k": 2}]}', {"a": [{"k": 1}, {"k": 2}]}),
    ('{"a": [1, 2,], "b": {"c": 3,},}', {"a": [1, 2], "b": {"c": 3}}),
    ('{"a": "line one\nline two"}', {"a": "line one\nline two"}),
    ('{"a": "come to "SN Bose" hostel", "b": 1}', {"a": 'come to "SN Bose" hostel', "b": 1}),
    ('{"a": None, "b": True, "c": False}', {"a": None, "b": True, "c": False}),
    ('{"a": "cut off mid-sen', {"a": "cut off mid-sen"}),
    ('{"a": "x", "b":', {"a": "x", "b": None}),
    ('Here you go:\n```json\n{"a": 1}\n```', {"a": 1}),
])
def test_common_slips_are_repaired(raw, expected):
    assert extract_json(raw) == expected


def test_valid_json_is_left_alone():
    valid = '{"a": "a \\"quoted\\" word", "n": [1, 2.5, -3], "o": {"k": true, "z": null}}'
    assert repair_json(valid) == valid


def test_hopeless_replies_still_keep_the_message(settings):
    broken = '{"message_for_listener": "আসুন", gloss_en: the rest is not JSON at all ]]'
    out, calls = ask(settings, [broken, broken])
    assert out.message_for_listener == "আসুন"
    assert len(calls) == 2


def test_a_reply_with_nothing_usable_is_still_an_error(settings):
    with pytest.raises(EvonError):
        ask(settings, ["I cannot help with that.", "Still no JSON here."])


def test_salvage_only_takes_text_fields():
    assert salvage('{"message_for_listener": "a \\"b\\"", "landmarks": [broken', RelayOut) == {
        "message_for_listener": 'a "b"'}
