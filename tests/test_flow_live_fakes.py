"""The full demo in LIVE mode, with fake Gnani and Evon servers standing in for the network.

This checks that every real request is well formed and every model-shaped reply (with
reasoning traces, code fences and so on) is handled the way a real one would be.
"""
import json
import shutil
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import prompts

ROOT = Path(__file__).resolve().parent.parent


class FakeBackends:
    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.stt_requests, self.tts_requests, self.evon_requests = [], [], []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/stt/v3"):
            self.stt_requests.append(request.content.decode("utf-8", "ignore"))
            text, lang = self.transcripts.pop(0)
            return httpx.Response(200, json={"success": True, "transcript": text, "detected_language_code": lang})
        if url.endswith("/api/v1/tts/inference"):
            self.tts_requests.append(json.loads(request.content))
            return httpx.Response(200, content=b"RIFF" + b"\0" * 400, headers={"content-type": "audio/wav"})
        if url.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.evon_requests.append(body)
            system, user = body["messages"][0]["content"], body["messages"][1]["content"]
            try:
                payload = json.loads(user)
            except ValueError:
                payload = user
            reply = self.evon_reply(system, payload)
            if body["chat_template_kwargs"]["enable_thinking"]:
                reply = "<think>Comparing names across scripts...</think>\n```json\n" + reply + "\n```"
            return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
        return httpx.Response(404)

    @staticmethod
    def evon_reply(system: str, p: dict) -> str:
        if system.startswith(prompts.RELAY):
            if p["speaker"] == "rider":
                return json.dumps({"message_for_listener": "டெலிவரி செய்பவர் கட்டிடத்தைத் தேடுகிறார்.",
                                   "gloss_en": "The rider is looking for the building.", "landmarks": [], "building": {},
                                   "speaker_language": "hi-IN"})
            if p.get("pending_question"):
                bus = next(o["id"] for o in p["pending_question"]["options"] if "bus" in o["label"])
                return json.dumps({"message_for_listener": "बस स्टॉप के पास।", "gloss_en": "Near the bus stop.",
                                   "landmarks": [], "building": {}, "answer_option_id": bus, "speaker_language": "ta-IN"})
            return json.dumps({
                "message_for_listener": "हरी बिल्डिंग, मुरुगन मंदिर के सामने, Apollo Pharmacy के बगल में।",
                "gloss_en": "Green building opposite the Murugan temple, next to Apollo Pharmacy.",
                "landmarks": [
                    {"heard": "முருகன் கோவில்", "kind": "temple", "relation": "opposite", "name_hint_en": "Murugan"},
                    {"heard": "அப்போலோ பார்மசி", "kind": "pharmacy", "relation": "next to", "name_hint_en": "Apollo"},
                ],
                "building": {"colour": "green", "entrance": "back gate", "floor": 3},
                "speaker_language": "Tamil",
            }, ensure_ascii=False)
        if system.startswith(prompts.MATCH):
            ids = [c["site_id"] for c in p["candidates"]]
            assert ids == ["S1", "S2"], ids
            return json.dumps({
                "decision": "ask", "site_id": None, "pin_is_wrong": True, "confidence": 0.5,
                "reason": "Both sites have a Murugan temple next to an Apollo Pharmacy.",
                "question_for_customer": "உங்கள் கட்டிடம் பஸ் ஸ்டாப் அருகிலா, அல்லது பெட்ரோல் பங்க் அருகிலா?",
                "question_gloss_en": "Is your building near the bus stop or the petrol bunk?",
                "options": [{"id": "S1", "label": "near the bus stop"}, {"id": "S2", "label": "near the petrol bunk"}],
            }, ensure_ascii=False)
        if system.startswith(prompts.DIRECTIONS):
            f = p["facts"]
            return json.dumps({"say": f"आपकी बिल्डिंग {f['distance_m']} मीटर सीधे आगे है।",
                               "gloss_en": f"Your building is {f['distance_m']} m straight ahead."}, ensure_ascii=False)
        if system.startswith(prompts.NOTE):
            return json.dumps({"building_description": "Green building opposite Arulmigu Murugan Temple",
                               "landmarks": ["Arulmigu Murugan Temple", "Apollo Pharmacy"], "entrance": "back gate",
                               "floor": "3", "cautions": [], "summary_en": "Green building, back gate, floor 3.",
                               "pin_fix_question_for_customer": "உங்கள் சேமித்த இடத்தை மாற்றலாமா?",
                               "pin_fix_gloss_en": "Shall we move your saved location?"}, ensure_ascii=False)
        if system.startswith(prompts.BRIEFING):
            return json.dumps({"say": f"আসল বাড়িটি পিন থেকে {p['from_saved_pin']['distance_m']} মিটার উত্তরে।",
                               "gloss_en": "The real building is north of the pin."}, ensure_ascii=False)
        raise AssertionError("unknown prompt")


@pytest.fixture()
def live(tmp_path, monkeypatch):
    for name in ("places_demo.json", "orders_demo.json", "demo_script.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    monkeypatch.setenv("PATA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GNANI_API_KEY", "test-key")
    monkeypatch.setenv("EVON_BASE_URL", "http://evon.test/v1")
    for key in ("MOCK_PRISMA", "MOCK_EVON", "MOCK_TIMBRE"):
        monkeypatch.setenv(key, "0")
    script = {l["id"]: l for l in json.loads((ROOT / "data" / "demo_script.json").read_text())["lines"]}
    fakes = FakeBackends([(script["r1"]["text"], "hi-IN"), (script["c1"]["text"], "ta-IN"), (script["c2"]["text"], "ta-IN")])
    import app.main as main_module

    real_client = httpx.AsyncClient
    monkeypatch.setattr(main_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(fakes.handle)))
    from app.config import load_settings

    with TestClient(main_module.create_app(load_settings())) as client:
        yield client, fakes


def wait_for(client, sid, predicate, timeout=5.0):
    deadline, snap = time.time() + timeout, None
    while time.time() < deadline:
        snap = client.get(f"/api/sessions/{sid}").json()
        if predicate(snap):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Timed out: {[(e['kind'], e.get('text', '')[:60]) for e in snap['log']]}")


def speak(client, sid, role):
    wav = b"RIFF" + b"\0" * 4000
    response = client.post(f"/api/sessions/{sid}/turn", data={"role": role},
                           files={"audio": ("turn.wav", wav, "audio/wav")})
    assert response.status_code == 202, response.text


def test_live_flow_uses_all_three_models(live):
    client, fakes = live
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL",
                                             "rider_auto": True, "customer_auto": True}).json()["id"]
    assert client.get("/api/config").json()["modes"] == {"prisma": "live", "evon": "live", "timbre": "live"}

    speak(client, sid, "rider")
    wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: s["pending_question"] is not None)
    assert snap["customer_lang_confirmed"] and snap["building"]["floor"] == "3"
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: s["directions"] is not None)
    assert snap["resolved_site"]["id"] == "S1" and "450" in snap["directions"]["text"]
    client.post(f"/api/sessions/{sid}/delivered")
    wait_for(client, sid, lambda s: s["pin_fix_pending"])

    sid2 = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    client.post(f"/api/sessions/{sid2}/join", json={"role": "rider"})
    snap2 = wait_for(client, sid2, lambda s: any(e["kind"] == "briefing" for e in s["log"]))
    assert "৪৫০" in snap2["directions"]["text"] or "450" in snap2["directions"]["text"]

    # Prisma: language detection on every turn for both people; keyterms and topic always sent.
    assert all("indic-auto" in body for body in fakes.stt_requests)
    assert snap["languages"]["rider"]["source"] == "detected" and snap["languages"]["customer"]["source"] == "detected"
    assert all("Apollo Pharmacy" in body and "delivery rider" in body for body in fakes.stt_requests)
    # Evon: reasoning off for relays and directions, on for matching and the note.
    flags = {(r["messages"][0]["content"][:20], r["chat_template_kwargs"]["enable_thinking"]) for r in fakes.evon_requests}
    assert (prompts.MATCH[:20], True) in flags and (prompts.NOTE[:20], False) in flags
    assert (prompts.RELAY[:20], False) in flags and (prompts.DIRECTIONS[:20], False) in flags
    # Timbre: each listener hears their own language; directions are slowed down.
    languages_spoken = {(t["language"], t["voice"]) for t in fakes.tts_requests}
    assert ("ta-IN", "Shivani") in languages_spoken and ("hi-IN", "Yashraj") in languages_spoken
    assert ("bn-IN", "Yashraj") in languages_spoken
    assert any(t["text"].startswith("<slow>") for t in fakes.tts_requests)


def test_set_languages_tell_prisma_what_to_expect(live):
    client, fakes = live
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL"}).json()["id"]
    speak(client, sid, "rider")
    wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    speak(client, sid, "customer")
    wait_for(client, sid, lambda s: sum(1 for e in s["log"] if e["kind"] == "turn" and e.get("relayed")) >= 2)
    rider_body, customer_body = fakes.stt_requests[0], fakes.stt_requests[1]
    assert "hi-IN,en-IN" in rider_body and "indic-auto" not in rider_body
    assert "ta-IN,en-IN" in customer_body and "indic-auto" not in customer_body

    def has_tamil(body):
        return any("\u0b80" <= ch <= "\u0bff" for ch in body)

    # Place-name hints only in English and the speaker's own script.
    assert not has_tamil(rider_body) and has_tamil(customer_body)
    snap = client.get(f"/api/sessions/{sid}").json()
    assert snap["languages"]["rider"]["auto"] is False and snap["languages"]["customer"]["auto"] is False


def _english_for_bengali(translation):
    """A fake Evon that answers in English when asked for Bengali, as in the field report."""
    original = FakeBackends.evon_reply
    calls = {"translate": 0}

    def reply(system, p):
        if system.startswith("You translate"):
            calls["translate"] += 1
            return translation
        if system.startswith(prompts.RELAY) and p["listener_language"] == "bn-IN":
            assert "Bengali script" in system  # the language is named in the instructions themselves
            return json.dumps({"message_for_listener": "I am near the swimming pool. Where are you?",
                               "gloss_en": "I am near the swimming pool. Where are you?",
                               "landmarks": [], "building": {}, "speaker_language": "te-IN"})
        return original(system, p)

    return reply, calls


def test_english_from_evon_is_translated_before_anyone_hears_it(live):
    client, fakes = live
    fakes.evon_reply, calls = _english_for_bengali("আমি সুইমিং পুলের কাছে আছি। আপনি কোথায়?")
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    turn = next(e for e in snap["log"] if e["kind"] == "turn")
    assert calls["translate"] == 1 and turn["script_ok"] is True and "সুইমিং" in turn["relayed"]
    wait_for(client, sid, lambda s: any("সুইমিং" in t["text"] for t in fakes.tts_requests))
    spoken = next(t for t in fakes.tts_requests if "সুইমিং" in t["text"])
    assert spoken["language"] == "bn-IN"


def test_if_bengali_never_arrives_it_is_flagged_and_read_as_english(live):
    client, fakes = live
    fakes.evon_reply, calls = _english_for_bengali("I am near the swimming pool.")
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    turn = next(e for e in snap["log"] if e["kind"] == "turn")
    assert calls["translate"] == 1 and turn["script_ok"] is False
    wait_for(client, sid, lambda s: any(t["text"].startswith("I am near") for t in fakes.tts_requests))
    spoken = next(t for t in fakes.tts_requests if t["text"].startswith("I am near"))
    assert spoken["language"] == "en-IN"


def test_a_relay_that_repeats_an_earlier_line_is_translated_again(live):
    """Field report: the customer spoke Telugu, but the rider heard his own earlier Bengali line."""
    client, fakes = live
    rider_line = "দাদা, আমি সুইমিং পুলের সামনের গেটে দাঁড়িয়ে আছি। নিচে চলে এসো।"
    fakes.transcripts = [(rider_line, "bn-IN"),
                         ("swimming pool route కెళ్ళి వెళ్ళకండి, విశ్వేశ్వరయ్య hostel route కి రండి.", "te-IN")]
    original = FakeBackends.evon_reply
    seen = {}

    def reply(system, p):
        if system.startswith("You translate"):
            seen["source"] = p
            return "সুইমিং পুলের রাস্তা দিয়ে যাবেন না, বিশ্বেশ্বরায়া হোস্টেলের রাস্তা দিয়ে আসুন।"
        if system.startswith(prompts.RELAY) and p["speaker"] == "customer":
            seen["payload_clean"] = rider_line not in json.dumps(p, ensure_ascii=False) and list(p)[-1] == "transcript"
            return json.dumps({"message_for_listener": rider_line,
                               "gloss_en": "Don't take the swimming pool route; come by the Visvesvaraya hostel route.",
                               "landmarks": [], "building": {}, "speaker_language": "te-IN"}, ensure_ascii=False)
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "rider")
    wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: sum(1 for e in s["log"] if e["kind"] == "turn" and e.get("relayed")) >= 2)
    turn = [e for e in snap["log"] if e["kind"] == "turn"][-1]
    assert seen["payload_clean"]  # earlier lines go to Evon only as English meanings, new words last
    assert "বিশ্বেশ্বরায়া" in turn["relayed"] and seen["source"].startswith("Don't take")
    assert any(e["kind"] == "system" and "repeated an earlier line" in e["text"] for e in snap["log"])


def test_a_missing_comma_in_evons_reply_is_repaired_in_place(live):
    client, fakes = live
    original = FakeBackends.evon_reply

    def reply(system, p):
        if system.startswith(prompts.RELAY) and p["speaker"] == "customer":
            return ('{"message_for_listener": "বাস স্টপের কাছে।"\n  "gloss_en": "Near the bus stop.",\n'
                    '  "landmarks": [{"heard": "bus stop", "kind": "bus_stop", "relation": "near", "name_hint_en": null}]}')
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    turn = next(e for e in snap["log"] if e["kind"] == "turn")
    assert turn["relayed"] == "বাস স্টপের কাছে।" and turn["gloss_en"] == "Near the bus stop."
    assert not any(e["kind"] == "error" for e in snap["log"])
    # Repaired, not replaced: no fallback was needed, so the landmark was kept.
    assert not any(e["kind"] == "system" and "plain translation" in e["text"] for e in snap["log"])
    assert any(lm.get("kind") == "bus_stop" for lm in snap["landmarks"])


def test_when_evon_json_keeps_failing_the_call_continues_with_a_plain_translation(live):
    client, fakes = live
    original = FakeBackends.evon_reply

    def reply(system, p):
        if system.startswith("You translate"):
            return "Near the bus stop." if "into English" in system else "বাস স্টপের কাছে।"
        if system.startswith(prompts.RELAY) and p["speaker"] == "customer":
            return "Sorry, I can only answer in plain text."  # nothing to repair or salvage
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    turn = next(e for e in snap["log"] if e["kind"] == "turn")
    assert turn["relayed"] == "বাস স্টপের কাছে।" and turn["gloss_en"] == "Near the bus stop."
    assert not any(e["kind"] == "error" for e in snap["log"])
    assert any(e["kind"] == "system" and "plain translation" in e["text"] for e in snap["log"])


def test_if_evon_cannot_write_the_note_delivery_still_completes(live):
    client, fakes = live
    original = FakeBackends.evon_reply

    def reply(system, p):
        if system.startswith(prompts.NOTE):
            return "{not json"
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL"}).json()["id"]
    speak(client, sid, "rider")
    speak(client, sid, "customer")
    wait_for(client, sid, lambda s: s["pending_question"] is not None)
    speak(client, sid, "customer")
    wait_for(client, sid, lambda s: s["destination"] is not None)
    client.post(f"/api/sessions/{sid}/delivered")
    snap = wait_for(client, sid, lambda s: s["note"] is not None and s["pin_fix_pending"])
    assert "Arulmigu Murugan Temple" in snap["note"]["building_description"]
    assert any(e["kind"] == "system" and "saved the facts it had" in e["text"] for e in snap["log"])
    assert not any(e["kind"] == "error" for e in snap["log"])


def test_borrowed_landmarks_are_dropped_and_logged(live):
    client, fakes = live
    fakes.transcripts = [("मैं सतीश धवन हॉस्टल के पास हूँ", "hi-IN"), ("SN Bose hostel gate ముందుకు రండి", "te-IN")]
    original = FakeBackends.evon_reply

    def reply(system, p):
        if system.startswith(prompts.RELAY) and p["speaker"] == "rider":
            return json.dumps({"message_for_listener": "నేను సతీష్ ధావన్ హాస్టల్ దగ్గర ఉన్నాను.",
                               "gloss_en": "I'm at Satish Dhawan Hostel.", "landmarks": [], "building": {}}, ensure_ascii=False)
        if system.startswith(prompts.RELAY) and p["speaker"] == "customer":
            return json.dumps({"message_for_listener": "SN Bose हॉस्टल के गेट के सामने आइए।",
                               "gloss_en": "Come to the front of the SN Bose hostel gate.",
                               "landmarks": [{"heard": "Satish Dhawan Hostel", "kind": "hostel", "name_hint_en": "Satish Dhawan Hostel"},
                                             {"heard": "SN Bose hostel", "kind": "hostel", "name_hint_en": "SN Bose Hostel"}],
                               "building": {"entrance": "front gate"}}, ensure_ascii=False)
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL",
                                             "customer_lang": "te-IN"}).json()["id"]
    speak(client, sid, "rider")
    wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "question" for e in s["log"]))
    assert [lm["name_hint_en"] for lm in snap["landmarks"]] == ["SN Bose Hostel"]
    staff = " ".join(e["text"] for e in snap["log"] if e["kind"] == "system")
    assert "Ignored Satish Dhawan Hostel" in staff and "Not on the map: SN Bose Hostel" in staff
    assert snap["destination"] is None  # no confident wrong match


def _sn_bose_call(client, fakes, relay_landmarks):
    """The reported call: the customer, in Hindi, tells the rider to come in front of SN Bose."""
    added = client.post("/api/places/custom", json={"name": "S. N. Bose Hostel", "kind": "hostel",
                                                    "lat": 13.0396, "lon": 80.2212}).json()
    # Another hostel elsewhere, so searching for "any hostel" would not find the right one by luck.
    client.post("/api/places/custom", json={"name": "Aryabhatta Hostel", "kind": "hostel", "lat": 13.0330, "lon": 80.2250})
    fakes.transcripts = [("भैया, आप गलत रास्ते पे हो। आप SN Bose के सामने आ जाइए।", "hi-IN")]
    original = FakeBackends.evon_reply
    seen = {}

    def reply(system, p):
        if system.startswith(prompts.RELAY):
            return json.dumps({"message_for_listener": "SN Bose-এর সামনে আসুন, আপনি ভুল পথে আছেন।",
                               "gloss_en": "Brother, you are on the wrong path. Come in front of SN Bose.",
                               "landmarks": relay_landmarks, "building": {}, "speaker_language": "hi-IN"},
                              ensure_ascii=False)
        if system.startswith(prompts.MATCH):
            seen["candidates"] = p["candidates"]
            return json.dumps({"decision": "resolved", "site_id": p["candidates"][0]["site_id"], "pin_is_wrong": True,
                               "confidence": 0.9, "reason": "SN Bose Hostel is the only place that fits.",
                               "question_for_customer": None, "question_gloss_en": None, "options": []})
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    return sid, added, seen


def test_a_place_the_customer_names_is_found_even_when_evon_lists_no_landmarks(live):
    client, fakes = live
    sid, added, seen = _sn_bose_call(client, fakes, relay_landmarks=[])
    snap = wait_for(client, sid, lambda s: s["destination"] is not None)
    assert any("Bose" in m["name"] for c in seen["candidates"] for m in c["places"])
    assert abs(snap["destination"]["lat"] - added["lat"]) < 0.0005
    assert any(e["kind"] == "system" and "SN Bose" in e["text"] and "spotted" in e["text"] for e in snap["log"])


def test_a_landmark_heard_in_english_letters_is_searched_by_that_name(live):
    client, fakes = live
    # Evon kept the words it heard but left name_hint_en empty: search by "SN Bose", not by "any hostel".
    sid, added, seen = _sn_bose_call(client, fakes, relay_landmarks=[
        {"heard": "SN Bose", "kind": "hostel", "relation": "in_front_of", "name_hint_en": None}])
    snap = wait_for(client, sid, lambda s: s["destination"] is not None)
    assert abs(snap["destination"]["lat"] - added["lat"]) < 0.0005
    assert len(seen["candidates"]) == 1  # SN Bose only, not every hostel


def test_the_control_room_hears_why_the_map_was_not_searched(live):
    client, fakes = live
    fakes.transcripts = [("हाँ भैया, मैं नीचे आ रही हूँ।", "hi-IN")]
    original = FakeBackends.evon_reply

    def reply(system, p):
        if system.startswith(prompts.RELAY):
            return json.dumps({"message_for_listener": "হ্যাঁ দাদা, আমি নিচে আসছি।", "gloss_en": "Yes, I'm coming down.",
                               "landmarks": [], "building": {}, "speaker_language": "hi-IN"}, ensure_ascii=False)
        return original(system, p)

    fakes.evon_reply = reply
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    speak(client, sid, "customer")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "system" and "didn't search" in e["text"] for e in s["log"]))
    assert snap["destination"] is None


def test_an_invented_room_never_reaches_the_next_rider(live):
    client, fakes = live
    original = FakeBackends.evon_reply
    seen = {}

    def reply(system, p):
        if system.startswith(prompts.NOTE):
            seen["note_payload"] = p
            return json.dumps({"building_description": "green building", "landmarks": [], "entrance": "front gate",
                               "floor": "ground", "cautions": ["The gate may be closed, check with hostel staff"],
                               "summary_en": "Front gate of the green building, room 105, ground floor."})
        if system.startswith(prompts.BRIEFING):
            seen["brief_payload"] = p
            return json.dumps({"say": "பச்சை கட்டிடத்தின் முன் வாயில், அறை 214.",
                               "gloss_en": "Front gate of the green building, Room 214."}, ensure_ascii=False)
        return original(system, p)

    fakes.evon_reply = reply
    client.post("/api/setup", json={"address_text": "Room 214, IIT (BHU) campus"})
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()["id"]
    client.post(f"/api/sessions/{sid}/join", json={"role": "rider"})
    client.post(f"/api/sessions/{sid}/delivered")
    snap = wait_for(client, sid, lambda s: s["note"] is not None)
    assert seen["note_payload"]["address_text"] == "Room 214, IIT (BHU) campus"
    note = client.get("/api/notes").json()["ADDR-MEENAKSHI"]
    assert note["summary_en"] == "Front gate of the green building, Room 214."
    assert note["floor"] is None and note["cautions"] == []
    assert any(e["kind"] == "system" and "corrected the doorstep note" in e["text"] for e in snap["log"])

    sid2 = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-KARTHIK"}).json()["id"]
    client.post(f"/api/sessions/{sid2}/join", json={"role": "rider"})
    wait_for(client, sid2, lambda s: any(e["kind"] == "briefing" for e in s["log"]))
    brief = seen["brief_payload"]
    assert brief["rider_name"] == "Karthik" and brief["customer_name"] == client.get("/api/setup").json()["customer_name"]
    assert "customer_name" not in brief["note"] and "105" not in json.dumps(brief)
