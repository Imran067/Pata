"""The whole demo, end to end, with mock Prisma, Evon and Timbre."""
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for name in ("places_demo.json", "orders_demo.json", "demo_script.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    for key in ("GNANI_API_KEY", "EVON_BASE_URL", "PLACES_FILE", "ORDERS_FILE", "SCRIPT_FILE", "NOTES_FILE", "AUDIO_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATA_DATA_DIR", str(tmp_path))
    for key in ("MOCK_PRISMA", "MOCK_EVON", "MOCK_TIMBRE"):
        monkeypatch.setenv(key, "1")
    from app.config import load_settings
    from app.main import create_app

    with TestClient(create_app(load_settings())) as test_client:
        yield test_client


def wait_for(client, session_id, predicate, timeout=5.0):
    deadline, snap = time.time() + timeout, None
    while time.time() < deadline:
        snap = client.get(f"/api/sessions/{session_id}").json()
        if predicate(snap):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Timed out. Status: {snap['status']}; log: {[e['kind'] for e in snap['log']]}")


def say(client, session_id, role, text):
    response = client.post(f"/api/sessions/{session_id}/turn", data={"role": role, "text": text})
    assert response.status_code == 202, response.text


def start(client, rider_id="R-RAHUL"):
    response = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": rider_id})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_full_demo_flow(client):
    lines = {line["id"]: line["text"] for line in client.get("/api/script").json()["lines"]}
    sid = start(client)
    client.post(f"/api/sessions/{sid}/join", json={"role": "rider"})
    client.post(f"/api/sessions/{sid}/join", json={"role": "customer"})
    wait_for(client, sid, lambda s: set(s["joined"]) == {"rider", "customer"})

    say(client, sid, "rider", lines["r1"])
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "turn" and e.get("relayed") for e in s["log"]))
    assert "கட்டிடம்" in next(e for e in snap["log"] if e["kind"] == "turn")["relayed"]

    say(client, sid, "customer", lines["c1"])
    snap = wait_for(client, sid, lambda s: s["pending_question"] is not None)
    assert [site["id"] for site in snap["sites"]] == ["S1", "S2"]
    assert "பஸ் ஸ்டாப்" in snap["pending_question"]["text"]
    assert snap["building"]["colour"] == "green" and snap["building"]["floor"] == "3"
    assert snap["building"]["entrance"] == "back gate"

    say(client, sid, "customer", lines["c2"])
    snap = wait_for(client, sid, lambda s: s["directions"] is not None)
    assert snap["resolved_site"]["id"] == "S1" and snap["pin_is_wrong"] is True
    assert snap["directions"]["facts"]["relative"] == "ahead"
    assert snap["directions"]["facts"]["distance_m"] == 450

    client.post(f"/api/sessions/{sid}/delivered")
    snap = wait_for(client, sid, lambda s: s["note"] is not None and s["pin_fix_pending"])
    client.post(f"/api/sessions/{sid}/pin-fix", json={"accept": True})
    wait_for(client, sid, lambda s: not s["pin_fix_pending"])
    note = client.get("/api/notes").json()["ADDR-MEENAKSHI"]
    assert note["confirmed_by_customer"] is True and note["pin_correction"] is None  # the pin itself was fixed
    assert note["entrance"] == "back gate" and note["floor"] == "3"
    moved_pin = client.get("/api/setup").json()["pin"]
    assert abs(moved_pin["lat"] - snap["destination"]["lat"]) < 1e-5 and moved_pin["lat"] > 13.039

    # Next day: the saved pin already points at the right building, and the note briefs the new rider.
    sid2 = start(client, "R-SOURAV")
    snap2 = client.get(f"/api/sessions/{sid2}").json()
    assert snap2["order"]["pin"] == moved_pin and snap2["destination"] is None
    client.post(f"/api/sessions/{sid2}/join", json={"role": "rider"})
    snap2 = wait_for(client, sid2, lambda s: any(e["kind"] == "briefing" for e in s["log"]))
    assert "back gate" in snap2["directions"]["text"]


def test_rider_arrival_gives_entrance_and_floor(client):
    lines = {line["id"]: line["text"] for line in client.get("/api/script").json()["lines"]}
    sid = start(client)
    say(client, sid, "customer", lines["c1"])
    wait_for(client, sid, lambda s: s["pending_question"] is not None)
    say(client, sid, "customer", lines["c2"])
    snap = wait_for(client, sid, lambda s: s["destination"] is not None and s["directions"] is not None)
    dest = snap["destination"]
    client.post(f"/api/sessions/{sid}/position", json={"lat": dest["lat"] - 0.0001, "lon": dest["lon"], "heading": 0})
    snap = wait_for(client, sid, lambda s: s["arrived"] and s["directions"]["facts"]["arrived"])
    assert "back gate" in snap["directions"]["text"]


def test_websocket_streams_audio_for_the_right_person(client):
    sid = start(client)
    with client.websocket_connect(f"/ws/{sid}") as socket:
        assert socket.receive_json()["type"] == "snapshot"
        client.post(f"/api/sessions/{sid}/join", json={"role": "rider"})
        for _ in range(20):
            event = socket.receive_json()
            if event["type"] == "audio":
                break
        else:
            raise AssertionError("no audio event arrived")
        assert event["for"] == "rider" and event["kind"] == "disclosure"
        audio = client.get(event["url"])
        assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_bad_requests_get_clear_errors(client):
    assert client.get("/api/sessions/nope").status_code == 404
    sid = start(client)
    assert client.post(f"/api/sessions/{sid}/turn", data={"role": "cook", "text": "hi"}).status_code == 422
    empty = client.post(f"/api/sessions/{sid}/turn", data={"role": "rider"},
                        files={"audio": ("turn.wav", b"RIFF", "audio/wav")})
    assert empty.status_code == 422
    assert client.get("/api/audio/../../etc/passwd").status_code == 404
    far = client.post(f"/api/sessions/{sid}/position", json={"lat": 28.6, "lon": 77.2, "heading": 0})
    assert far.status_code == 422


def test_customer_language_can_be_picked_per_session(client):
    response = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL", "customer_lang": "kn-IN"})
    assert response.status_code == 200 and response.json()["customer_lang"] == "kn-IN"
    sid = response.json()["id"]
    client.post(f"/api/sessions/{sid}/join", json={"role": "customer"})
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "system" for e in s["log"]))
    assert "ಅನುವಾದ" in next(e for e in snap["log"] if e["kind"] == "system")["text"]  # Kannada disclosure
    unknown = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL", "customer_lang": "xx-IN"})
    assert unknown.status_code == 422


def test_language_follows_what_she_actually_says(client):
    lines = {line["id"]: line["text"] for line in client.get("/api/script").json()["lines"]}
    sid = client.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL",
                                             "customer_lang": "kn-IN", "customer_auto": True}).json()["id"]
    client.post(f"/api/sessions/{sid}/join", json={"role": "customer"})
    wait_for(client, sid, lambda s: any(e["kind"] == "system" for e in s["log"]))
    say(client, sid, "customer", lines["c1"])  # picked Kannada, but she speaks Tamil
    snap = wait_for(client, sid, lambda s: s["customer_lang"] == "ta-IN"
                    and sum(e["kind"] == "system" for e in s["log"]) >= 2)
    assert snap["languages"]["customer"]["source"] == "detected"
    assert any(e["kind"] == "language" for e in snap["log"])
    assert "மொழிபெயர்க்கப்படுகிறது" in [e for e in snap["log"] if e["kind"] == "system"][-1]["text"]


def test_delivered_works_without_a_match_and_uses_where_the_rider_was(client):
    sid = start(client)
    client.post(f"/api/sessions/{sid}/join", json={"role": "rider"})
    client.post(f"/api/sessions/{sid}/position", json={"lat": 13.0387, "lon": 80.2210, "heading": 0})  # 300 m north
    wait_for(client, sid, lambda s: abs(s["rider_pos"]["lat"] - 13.0387) < 1e-6)
    assert client.post(f"/api/sessions/{sid}/delivered").status_code == 200
    snap = wait_for(client, sid, lambda s: s["note"] is not None and s["pin_fix_pending"])
    assert snap["delivered"] is True and snap["destination"] is None
    note = client.get("/api/notes").json()["ADDR-MEENAKSHI"]
    assert abs(note["pin_correction"]["lat"] - 13.0387) < 1e-6  # where he actually handed it over
    client.post(f"/api/sessions/{sid}/delivered")  # a second tap changes nothing
    assert client.get("/api/notes").json()["ADDR-MEENAKSHI"]["deliveries_learned_from"] == 1


def test_naming_an_unknown_place_gets_a_question_not_silence(client):
    sid = start(client)
    say(client, sid, "customer", "Vishveshvaraya hostel pakkathula, swimming pool")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "question" for e in s["log"]))
    assert any(e["kind"] == "system" and "No place on the map matches" in e["text"] for e in snap["log"])
    question = next(e for e in snap["log"] if e["kind"] == "question")
    assert question["text"] == "உங்கள் கட்டிடத்திற்கு அருகில் இருக்கும் இன்னொரு அடையாளம் சொல்ல முடியுமா?"


def test_the_doorstep_note_can_be_heard_again_and_a_missing_one_is_explained(client):
    lines = {line["id"]: line["text"] for line in client.get("/api/script").json()["lines"]}
    sid = start(client)
    client.post(f"/api/sessions/{sid}/join", json={"role": "rider"})
    client.post(f"/api/sessions/{sid}/briefing")
    snap = wait_for(client, sid, lambda s: any(e["kind"] == "error" for e in s["log"]))
    assert any("no doorstep note" in e["text"] for e in snap["log"] if e["kind"] == "error")

    say(client, sid, "customer", lines["c1"])
    wait_for(client, sid, lambda s: s["pending_question"] is not None)
    say(client, sid, "customer", lines["c2"])
    wait_for(client, sid, lambda s: s["directions"] is not None)
    client.post(f"/api/sessions/{sid}/delivered")
    wait_for(client, sid, lambda s: s["note"] is not None)

    # Next day, in Tamil: the note is read on Start Pata, and again on request.
    sid2 = start(client, "R-KARTHIK")
    client.post(f"/api/sessions/{sid2}/join", json={"role": "rider"})
    wait_for(client, sid2, lambda s: sum(e["kind"] == "briefing" for e in s["log"]) == 1)
    client.post(f"/api/sessions/{sid2}/briefing")
    snap2 = wait_for(client, sid2, lambda s: sum(e["kind"] == "briefing" for e in s["log"]) == 2)
    assert snap2["rider"]["lang"] == "ta-IN"
