"""The control-room setup: who and where the customer is, languages, and real map data."""
import json
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.osm import places_from_elements

ROOT = Path(__file__).resolve().parent.parent
ELEMENTS = [
    {"type": "node", "id": 1, "lat": 13.040, "lon": 80.220,
     "tags": {"amenity": "place_of_worship", "religion": "hindu", "name": "Sri Murugan Temple", "name:ta": "ஸ்ரீ முருகன் கோவில்"}},
    {"type": "node", "id": 2, "lat": 13.041, "lon": 80.221, "tags": {"amenity": "pharmacy", "name": "Apollo Pharmacy"}},
    {"type": "node", "id": 3, "lat": 13.042, "lon": 80.222, "tags": {"highway": "bus_stop"}},
    {"type": "way", "id": 4, "center": {"lat": 13.043, "lon": 80.223},
     "tags": {"amenity": "place_of_worship", "religion": "muslim", "name": "Big Mosque"}},
    {"type": "node", "id": 5, "lat": 13.040, "lon": 80.220,
     "tags": {"amenity": "place_of_worship", "religion": "hindu", "name": "Sri Murugan Temple"}},
    {"type": "node", "id": 6, "lat": 13.050, "lon": 80.230, "tags": {"shop": "clothes"}},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for name in ("places_demo.json", "orders_demo.json", "demo_script.json"):
        shutil.copy(ROOT / "data" / name, tmp_path / name)
    for key in ("GNANI_API_KEY", "EVON_BASE_URL", "PLACES_FILE", "ORDERS_FILE", "SCRIPT_FILE", "NOTES_FILE",
                "AUDIO_DIR", "SETUP_FILE", "PLACES_OSM_FILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATA_DATA_DIR", str(tmp_path))
    for key in ("MOCK_PRISMA", "MOCK_EVON", "MOCK_TIMBRE"):
        monkeypatch.setenv(key, "1")
    import app.main as main_module

    def overpass(request: httpx.Request) -> httpx.Response:
        assert "overpass" in str(request.url)
        return httpx.Response(200, json={"elements": ELEMENTS})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(main_module.httpx, "AsyncClient",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(overpass)))
    from app.config import load_settings

    with TestClient(main_module.create_app(load_settings())) as test_client:
        yield test_client, tmp_path


def test_openstreetmap_elements_become_places():
    places = places_from_elements(ELEMENTS, "ta-IN")
    assert [p["name"] for p in places] == ["Sri Murugan Temple", "Apollo Pharmacy", "Bus stop", "Big Mosque"]
    assert [p["kind"] for p in places] == ["temple", "pharmacy", "bus_stop", "mosque"]
    assert places[0]["local_names"] == {"ta-IN": "ஸ்ரீ முருகன் கோவில்"}


def test_setup_changes_who_and_where_the_customer_is(client):
    c, _ = client
    assert c.get("/api/setup").json()["customer_name"] == "Meenakshi"
    saved = c.post("/api/setup", json={"customer_name": "Lakshmi", "pin": {"lat": 13.0418, "lon": 80.2341},
                                       "customer_lang": "hi-IN"}).json()
    assert saved["pin"] == {"lat": 13.0418, "lon": 80.2341}
    snap = c.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL"}).json()
    assert snap["order"]["customer_name"] == "Lakshmi" and snap["order"]["pin"]["lat"] == 13.0418
    assert snap["rider_pos"]["lat"] == 13.0418
    assert snap["customer_lang"] == "hi-IN" and snap["languages"]["customer"]["auto"] is False


def test_rider_language_and_detection_come_from_the_setup(client):
    c, _ = client
    c.post("/api/setup", json={"rider_id": "R-SOURAV", "rider_lang": "bn-IN", "rider_auto": True})
    snap = c.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-SOURAV"}).json()
    assert snap["rider"]["lang"] == "bn-IN" and snap["languages"]["rider"]["auto"] is True


def test_moving_the_pin_clears_that_addresss_doorstep_note(client):
    c, data = client
    (data / "doorstep_notes.json").write_text(json.dumps({"ADDR-MEENAKSHI": {"summary_en": "old spot"}}))
    c.post("/api/setup", json={"customer_name": "Meenakshi"})
    assert "ADDR-MEENAKSHI" in c.get("/api/notes").json()  # no move, note kept
    c.post("/api/setup", json={"pin": {"lat": 13.05, "lon": 80.23}})
    assert c.get("/api/notes").json() == {}


def test_bad_setup_values_are_refused_clearly(client):
    c, _ = client
    assert c.post("/api/setup", json={"customer_lang": "xx-IN"}).status_code == 422
    outside = c.post("/api/setup", json={"pin": {"lat": 51.5, "lon": -0.12}})
    assert outside.status_code == 422 and "India" in outside.json()["detail"]
    assert c.post("/api/setup", json={"rider_id": "R-NOBODY"}).status_code == 422
    early = c.post("/api/setup", json={"places_source": "osm"})
    assert early.status_code == 422 and "Load real places first" in early.json()["detail"]


def test_real_places_can_be_loaded_around_the_pin(client):
    c, _ = client
    response = c.post("/api/places/osm", json={"radius": 1500})
    assert response.status_code == 200 and response.json()["count"] == 4
    assert "1 pharmacy" in response.json()["summary"]
    assert c.get("/api/setup").json()["places_source"] == "osm"
    names = {p["name"] for p in c.get("/api/places", params={"lat": 13.04, "lon": 80.22}).json()["places"]}
    assert "Apollo Pharmacy" in names and "Lotus Apartments" not in names
    assert c.post("/api/setup", json={"places_source": "sample"}).json()["places_source"] == "sample"
    names = {p["name"] for p in c.get("/api/places", params={"lat": 13.036, "lon": 80.221}).json()["places"]}
    assert "Lotus Apartments" in names


def test_name_and_language_changes_reach_calls_already_open(client):
    c, _ = client
    sid = c.post("/api/sessions", json={"order_id": "ORD-1042", "rider_id": "R-RAHUL"}).json()["id"]
    c.post("/api/setup", json={"customer_name": "Lakshmi", "customer_lang": "te-IN", "pin": {"lat": 13.05, "lon": 80.23}})
    snap = c.get(f"/api/sessions/{sid}").json()
    assert snap["order"]["customer_name"] == "Lakshmi" and snap["customer_lang"] == "te-IN"
    assert snap["order"]["pin"] == {"lat": 13.036, "lon": 80.221}  # a moved pin waits for the next session


def test_places_added_by_hand_are_searched_and_can_be_removed(client):
    c, _ = client
    added = c.post("/api/places/custom", json={"name": "Aryabhatta Hostel", "kind": "hostel", "lat": 13.0370, "lon": 80.2215})
    assert added.status_code == 200 and added.json()["source"] == "you"
    names = {p["name"] for p in c.get("/api/places", params={"lat": 13.036, "lon": 80.221}).json()["places"]}
    assert "Aryabhatta Hostel" in names and "Lotus Apartments" in names  # added on top of the map data
    assert c.post("/api/places/custom", json={"name": "X", "kind": "castle", "lat": 13.0, "lon": 80.2}).status_code == 422
    assert c.post("/api/places/custom", json={"name": "X", "kind": "hostel", "lat": 51.5, "lon": 0.1}).status_code == 422
    assert c.delete(f"/api/places/custom/{added.json()['id']}").status_code == 200
    names = {p["name"] for p in c.get("/api/places", params={"lat": 13.036, "lon": 80.221}).json()["places"]}
    assert "Aryabhatta Hostel" not in names


def test_a_new_address_starts_a_fresh_doorstep_note(client):
    c, data = client
    (data / "doorstep_notes.json").write_text(json.dumps({"ADDR-MEENAKSHI": {"summary_en": "old address"}}))
    c.post("/api/setup", json={"customer_name": "Yashwant"})
    assert "ADDR-MEENAKSHI" in c.get("/api/notes").json()  # renaming keeps the note
    c.post("/api/setup", json={"address_text": "D-105, Aryabhatta Hostel"})
    assert c.get("/api/notes").json() == {}
