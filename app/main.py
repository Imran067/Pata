"""Pata web server. Run with:  python -m uvicorn app.main:app --port 8080"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import languages, osm
from .config import BASE_DIR, Settings, load_settings
from .evon_tasks import LiveEvonTasks
from .geo import PlaceStore, haversine_m
from .models import KINDS
from .notes import NotesStore
from .pipeline import Pata
from .services.evon import EvonClient
from .services.mock_evon import MockEvonTasks
from .services.prisma import MockPrisma, PrismaClient
from .services.timbre import MockTimbre, TimbreClient
from .session import Hub
from .setup_store import SetupStore

# Pata's own warnings (for example "Evon's reply was not valid JSON") appear in the server's terminal.
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
_pata_log = logging.getLogger("pata")
if not _pata_log.handlers:
    _pata_log.addHandler(_handler)
    _pata_log.setLevel(logging.INFO)
    _pata_log.propagate = False

STATIC_DIR = BASE_DIR / "static"
AUDIO_NAME = re.compile(r"^[0-9a-f]{40}\.wav$")
MAX_AUDIO_BYTES = 6 * 1024 * 1024


class StartBody(BaseModel):
    order_id: str
    rider_id: str
    customer_lang: str | None = None
    customer_auto: bool | None = None
    rider_lang: str | None = None
    rider_auto: bool | None = None


class JoinBody(BaseModel):
    role: str


class PositionBody(BaseModel):
    lat: float
    lon: float
    heading: float = 0.0


class PinFixBody(BaseModel):
    accept: bool


class PinBody(BaseModel):
    lat: float
    lon: float


class SetupBody(BaseModel):
    customer_name: str | None = None
    address_text: str | None = None
    items: str | None = None
    pin: PinBody | None = None
    customer_lang: str | None = None
    customer_auto: bool | None = None
    rider_id: str | None = None
    rider_lang: str | None = None
    rider_auto: bool | None = None
    places_source: str | None = None
    prisma_hints: bool | None = None


class OsmBody(BaseModel):
    radius: int = 1500


class CustomPlaceBody(BaseModel):
    name: str
    kind: str
    lat: float
    lon: float


def load_custom_places(settings: Settings) -> list[dict]:
    """Places added by hand in the control room (hostels, gates, anything the map is missing)."""
    path = settings.places_custom_file
    if not path.exists():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("places", []))
    except (ValueError, AttributeError):
        return []


def save_custom_places(settings: Settings, places: list[dict]) -> None:
    path = settings.places_custom_file
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"places": places}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_places(settings: Settings, source: str) -> PlaceStore:
    base = settings.places_osm_file if source == "osm" and settings.places_osm_file.exists() else settings.places_file
    return PlaceStore(base, extra=load_custom_places(settings))


_KIND_WORDS = {"petrol_pump": "petrol bunk", "atm": "ATM", "bus_stop": "bus stop", "water_tank": "water tank"}


def _count_words(kind: str, count: int) -> str:
    word = _KIND_WORDS.get(kind, kind.replace("_", " "))
    if count != 1:
        if word.endswith("y") and not word.endswith(("ay", "ey", "oy")):
            word = word[:-1] + "ies"
        elif word.endswith(("ch", "sh", "s")):
            word += "es"
        else:
            word += "s"
    return f"{count} {word}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    script = json.loads(settings.script_file.read_text(encoding="utf-8"))["lines"]
    orders = json.loads(settings.orders_file.read_text(encoding="utf-8"))
    notes = NotesStore(settings.notes_file)
    setup = SetupStore(settings.setup_file, orders)
    hub = Hub()
    state: dict = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        http = httpx.AsyncClient()
        prisma = MockPrisma(script) if settings.mock_prisma else PrismaClient(settings, http)
        timbre = MockTimbre(settings) if settings.mock_timbre else TimbreClient(settings, http)
        evon = MockEvonTasks(script) if settings.mock_evon else LiveEvonTasks(
            EvonClient(settings, http), settings.evon_reasoning, settings.evon_reasoning_tokens)
        places = load_places(settings, setup.get()["places_source"])
        state["http"] = http
        state["pata"] = Pata(settings, places, orders, notes, prisma, timbre, evon, hub, setup)
        yield
        await http.aclose()

    app = FastAPI(title="Pata", summary="Doorstep call copilot on Gnani Prisma, Evon and Timbre", lifespan=lifespan)

    def pata() -> Pata:
        return state["pata"]

    def session_or_404(session_id: str):
        try:
            return pata().get(session_id)
        except KeyError:
            raise HTTPException(404, "No call session with that id. Start a new one from the control room.")

    def check_role(role: str) -> None:
        if role not in ("rider", "customer"):
            raise HTTPException(422, "role must be 'rider' or 'customer'.")

    # ---------------------------------------------------------------- pages

    @app.get("/", include_in_schema=False)
    def control_room():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/rider", include_in_schema=False)
    def rider_page():
        return FileResponse(STATIC_DIR / "rider.html")

    @app.get("/customer", include_in_schema=False)
    def customer_page():
        return FileResponse(STATIC_DIR / "customer.html")

    # ---------------------------------------------------------------- reference data

    @app.get("/api/config")
    def config():
        return {
            "modes": settings.modes(),
            "area_name": pata().places.area_name,
            "languages": {code: languages.describe(code) for code in languages.LANGUAGES},
            "voices": {"rider": settings.timbre_voice_rider, "customer": settings.timbre_voice_customer},
            "kinds": KINDS,
        }

    @app.get("/api/orders")
    def list_orders():
        saved = notes.all()
        return {
            "orders": [{**o, "has_note": o["address_id"] in saved} for o in orders["orders"]],
            "riders": [{**r, "lang_name": languages.name(r["lang"])} for r in orders["riders"]],
        }

    @app.get("/api/script")
    def demo_script():
        return {"lines": [{k: line[k] for k in ("id", "role", "lang", "text", "gloss_en")} for line in script]}

    @app.get("/api/places")
    def nearby_places(lat: float, lon: float, radius: float = 900):
        found = pata().places.near(lat, lon, min(radius, 2000))
        return {"places": [p.to_dict() | {"distance_m": round(d)} for p, d in found[:300]]}

    # ---------------------------------------------------------------- demo setup

    @app.get("/api/setup")
    def get_setup():
        return setup.get()

    @app.post("/api/setup")
    async def save_setup(body: SetupBody):
        changes = body.model_dump(exclude_none=True)
        if changes.get("places_source") == "osm" and not settings.places_osm_file.exists():
            raise HTTPException(422, "Load real places first, with the button under the map.")
        before = setup.get()
        try:
            after = setup.update(changes)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(422, str(exc))
        if after["pin"] != before["pin"] or after["address_text"] != before["address_text"]:
            notes.delete(orders["orders"][0]["address_id"])  # the old note describes another place
        if after["places_source"] != before["places_source"]:
            pata().set_places(load_places(settings, after["places_source"]))
        await pata().apply_setup_to_open_calls(before, after)
        return after

    @app.post("/api/places/osm")
    async def load_real_places(body: OsmBody):
        current = setup.get()
        radius = max(300, min(body.radius, 3000))
        pin = current["pin"]
        try:
            found = await osm.fetch_places(pin["lat"], pin["lon"], radius, current["customer_lang"], state["http"])
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"OpenStreetMap didn't answer ({exc.__class__.__name__}). Wait a minute and try again.")
        if not found:
            raise HTTPException(404, "OpenStreetMap has no named places around this pin. Try another spot.")
        settings.places_osm_file.write_text(json.dumps({
            "area_name": "Real places around the customer's pin (OpenStreetMap)",
            "source": "OpenStreetMap contributors (ODbL)",
            "center": pin, "radius_m": radius, "places": found,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        pata().set_places(load_places(settings, "osm"))
        setup.update({"places_source": "osm"})
        counts = Counter(p["kind"] for p in found)
        return {"count": len(found), "summary": ", ".join(_count_words(k, n) for k, n in counts.most_common(5))}

    @app.get("/api/places/custom")
    def custom_places():
        return {"places": load_custom_places(settings)}

    @app.post("/api/places/custom")
    def add_custom_place(body: CustomPlaceBody):
        name = " ".join(body.name.split())[:80]
        if not name:
            raise HTTPException(422, "Give the place a name.")
        if body.kind not in KINDS:
            raise HTTPException(422, f"Unknown kind. Use one of: {', '.join(KINDS)}.")
        if not (6.0 <= body.lat <= 37.5 and 68.0 <= body.lon <= 97.5):
            raise HTTPException(422, "That spot is outside India.")
        place = {"id": f"my-{uuid.uuid4().hex[:8]}", "name": name, "kind": body.kind,
                 "lat": round(body.lat, 6), "lon": round(body.lon, 6), "local_names": {}, "source": "you"}
        save_custom_places(settings, [*load_custom_places(settings), place])
        pata().set_places(load_places(settings, setup.get()["places_source"]))
        return place

    @app.delete("/api/places/custom/{place_id}")
    def remove_custom_place(place_id: str):
        places = load_custom_places(settings)
        kept = [p for p in places if p.get("id") != place_id]
        if len(kept) == len(places):
            raise HTTPException(404, "No such place.")
        save_custom_places(settings, kept)
        pata().set_places(load_places(settings, setup.get()["places_source"]))
        return {"removed": True}

    # ---------------------------------------------------------------- sessions

    @app.post("/api/sessions")
    def start(body: StartBody):
        for code in (body.customer_lang, body.rider_lang):
            if code and not languages.is_supported(code):
                raise HTTPException(422, f"Unsupported language. Use one of: {', '.join(languages.LANGUAGES)}.")
        try:
            s = pata().start_session(body.order_id, body.rider_id, customer_lang=body.customer_lang,
                                     customer_auto=body.customer_auto, rider_lang=body.rider_lang,
                                     rider_auto=body.rider_auto)
        except StopIteration:
            raise HTTPException(404, "Unknown order or rider id.")
        return s.public()

    @app.get("/api/sessions/{session_id}")
    def snapshot(session_id: str):
        return session_or_404(session_id).public()

    @app.post("/api/sessions/{session_id}/join")
    async def join(session_id: str, body: JoinBody):
        session_or_404(session_id)
        check_role(body.role)
        pata().spawn(pata().join(session_id, body.role))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/turn", status_code=202)
    async def turn(
        session_id: str,
        role: str = Form(...),
        text: str | None = Form(None),
        audio: UploadFile | None = File(None),
    ):
        session_or_404(session_id)
        check_role(role)
        data = None
        if not (text and text.strip()):
            if audio is None:
                raise HTTPException(422, "Send a recording or a typed message.")
            data = await audio.read()
            if len(data) > MAX_AUDIO_BYTES:
                raise HTTPException(413, "Recording is too long. Keep each turn under 30 seconds.")
            if len(data) < 1000:
                raise HTTPException(422, "Recording is empty. Hold the button a little longer.")
        pata().spawn(pata().handle_turn(session_id, role, audio=data, text=text))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/position")
    async def position(session_id: str, body: PositionBody):
        s = session_or_404(session_id)
        pin = s.order["pin"]
        if haversine_m(pin["lat"], pin["lon"], body.lat, body.lon) > 20_000:
            raise HTTPException(422, "That position is more than 20 km from the order. Check the coordinates.")
        pata().spawn(pata().update_position(session_id, body.lat, body.lon, body.heading))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/directions")
    async def repeat_directions(session_id: str):
        session_or_404(session_id)
        pata().spawn(pata().repeat_directions(session_id))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/briefing")
    async def replay_note(session_id: str):
        session_or_404(session_id)
        pata().spawn(pata().replay_note(session_id))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/delivered")
    async def delivered(session_id: str):
        session_or_404(session_id)
        pata().spawn(pata().mark_delivered(session_id))
        return {"accepted": True}

    @app.post("/api/sessions/{session_id}/pin-fix")
    async def pin_fix(session_id: str, body: PinFixBody):
        session_or_404(session_id)
        pata().spawn(pata().answer_pin_fix(session_id, body.accept))
        return {"accepted": True}

    # ---------------------------------------------------------------- doorstep notes

    @app.get("/api/notes")
    def all_notes():
        return notes.all()

    @app.delete("/api/notes")
    def clear_notes():
        notes.delete()
        return {"cleared": True}

    # ---------------------------------------------------------------- audio and live updates

    @app.get("/api/audio/{name}")
    def audio_file(name: str):
        path = settings.audio_dir / name
        if not AUDIO_NAME.match(name) or not path.exists():
            raise HTTPException(404, "No such audio file.")
        return FileResponse(path, media_type="audio/wav")

    @app.websocket("/ws/{session_id}")
    async def live(socket: WebSocket, session_id: str):
        try:
            s = pata().get(session_id)
        except KeyError:
            await socket.close(code=4404)
            return
        await hub.connect(session_id, socket)
        await socket.send_json({"type": "snapshot", "session": s.public()})
        try:
            while True:
                await socket.receive_text()  # only used to notice when the tab closes
        except WebSocketDisconnect:
            hub.disconnect(session_id, socket)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
