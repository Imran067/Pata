"""The call flow.

    rider or customer speaks
        -> Prisma transcribes (language detection, nearby place names as keyterms)
        -> Evon rewrites it for the listener and pulls out landmarks      [reasoning off]
        -> Timbre speaks it to the listener in their language
    customer named landmarks
        -> map code finds sites where those kinds of places sit together
        -> Evon decides which site the customer means, or writes a question [reasoning on]
        -> Timbre asks the customer, or map code computes the route
        -> Evon phrases the directions, Timbre reads them to the rider (slowly)
    delivered
        -> Evon merges the call into the doorstep note                   [reasoning on]
    next rider at the same address
        -> Evon turns the note into a briefing, Timbre reads it out
"""
from __future__ import annotations

import asyncio
import difflib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from . import geo, language_tracking, languages, phrases
from .note_guard import guard_note
from .config import Settings
from .geo import PlaceStore, Site
from .language_tracking import LangState
from .models import Landmark, MatchOut, NoteOut, RelayOut, SayOut
from .notes import NotesStore
from .services.evon import EvonError
from .services.prisma import SpeechError, Transcript
from .session import Hub, Session

OTHER = {"rider": "customer", "customer": "rider"}
_UNSEARCHABLE = {"building", "other", "junction"}

MORE_LANDMARK = {
    "ta-IN": "உங்கள் கட்டிடத்திற்கு அருகில் இருக்கும் இன்னொரு அடையாளம் சொல்ல முடியுமா?",
    "hi-IN": "क्या आप अपनी बिल्डिंग के पास की कोई और निशानी बता सकते हैं?",
    "bn-IN": "আপনার বিল্ডিংয়ের কাছে আর একটা চিহ্ন বলতে পারবেন?",
    "te-IN": "మీ బిల్డింగ్ దగ్గర ఉన్న ఇంకో గుర్తు చెప్పగలరా?",
    "kn-IN": "ನಿಮ್ಮ ಕಟ್ಟಡದ ಹತ್ತಿರ ಇರುವ ಇನ್ನೊಂದು ಗುರುತು ಹೇಳಬಹುದೇ?",
    "ml-IN": "നിങ്ങളുടെ കെട്ടിടത്തിനടുത്തുള്ള മറ്റൊരു അടയാളം പറയാമോ?",
    "mr-IN": "तुमच्या इमारतीजवळची आणखी एखादी खूण सांगू शकाल का?",
    "gu-IN": "તમારી બિલ્ડિંગ પાસેની બીજી કોઈ ઓળખ કહી શકશો?",
    "pa-IN": "ਕੀ ਤੁਸੀਂ ਆਪਣੀ ਬਿਲਡਿੰਗ ਦੇ ਨੇੜੇ ਦੀ ਕੋਈ ਹੋਰ ਨਿਸ਼ਾਨੀ ਦੱਸ ਸਕਦੇ ਹੋ?",
    "en-IN": "Can you tell me one more landmark near your building?",
}


class Pata:
    def __init__(self, settings: Settings, places: PlaceStore, orders: dict, notes: NotesStore,
                 prisma, timbre, evon, hub: Hub, setup=None):
        self.settings = settings
        self.setup = setup  # the control room's demo setup (SetupStore), optional
        self.places = places
        self.orders = orders
        self.notes = notes
        self.prisma = prisma
        self.timbre = timbre
        self.evon = evon
        self.hub = hub
        self.sessions: dict[str, Session] = {}
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ plumbing

    def get(self, session_id: str) -> Session:
        return self.sessions[session_id]

    def set_places(self, places: PlaceStore) -> None:
        """Switch map data (sample places, or real ones from OpenStreetMap) for new searches."""
        self.places = places

    def spawn(self, coro: Awaitable) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def publish(self, s: Session) -> None:
        await self.hub.broadcast(s.id, {"type": "snapshot", "session": s.public()})

    async def set_status(self, s: Session, text: str, busy: bool = True) -> None:
        s.status = {"text": text, "busy": busy}
        await self.publish(s)

    async def fail(self, s: Session, text: str, role: str | None = None) -> None:
        """Log a failure. `role` is whose turn failed: their phone shows a short "say it again" in their
        own language, and the control room shows the full message."""
        self.add_log(s, kind="error", text=text, role=role)
        s.status = {"text": "", "busy": False}
        await self.publish(s)

    @staticmethod
    def add_log(s: Session, **entry) -> dict:
        entry.setdefault("ts", time.time())
        s.log.append(entry)
        return entry

    async def say(self, s: Session, role: str, text: str, *, kind: str, gloss: str = "", slow: bool = False,
                  language: str | None = None) -> None:
        """Timbre speaks `text` to `role` in that person's language; the screen plays it."""
        voice = self.settings.timbre_voice_rider if role == "rider" else self.settings.timbre_voice_customer
        spoken = f"<slow> {text}" if slow and self.settings.timbre_model.startswith("timbre-v3") else text
        try:
            name = await self.timbre.speak(spoken, language=language or s.lang_of(role), voice=voice)
        except SpeechError as exc:
            await self.fail(s, f"Timbre could not speak this line, so it is shown as text only. {exc}")
            return
        await self.hub.broadcast(s.id, {
            "type": "audio", "for": role, "url": f"/api/audio/{name}",
            "kind": kind, "text": text, "gloss_en": gloss,
        })

    async def _checked(self, call: Callable, payload: dict, lang: str, field: str):
        """Run an Evon task and make sure its spoken text (`field`) is really in `lang`.

        1. Evon's reply.  2. Wrong script: ask once more, firmly.  3. Still wrong: a plain
        translation call, which a small model handles more reliably than a JSON reply.
        Returns (reply, ok); ok is False only if all three failed."""
        out = await call(payload)
        if self.settings.mock_evon or languages.script_ok(getattr(out, field), lang):
            return out, True
        retry = {**payload, "correction": (
            f"Your previous reply was not written in {languages.name(lang)} ({languages.script(lang)} script). "
            f"Write {field} in {languages.name(lang)}."
        )}
        out = await call(retry)
        if languages.script_ok(getattr(out, field), lang):
            return out, True
        translated = await self._translate(out.gloss_en or getattr(out, field), lang)
        if translated:
            setattr(out, field, translated)
            return out, True
        return out, False

    async def _translate(self, text: str, lang: str) -> str:
        """Plain translation into `lang`; returns "" unless the result really is in that script."""
        if not text or self.settings.mock_evon:
            return ""
        try:
            result = await self.evon.translate(text, lang)
        except EvonError:
            return ""
        return result if languages.script_ok(result, lang) else ""

    @staticmethod
    def _voice_language(text: str, lang: str, ok: bool) -> str:
        """Timbre reads in the listener's language. If Evon only managed English, read it as English
        rather than mangling it with another language's voice rules."""
        if ok or not languages.script_ok(text, "en-IN"):
            return lang
        return "en-IN"

    @staticmethod
    def _looks_copied(text: str, earlier: list[str]) -> bool:
        """True when a relay is (nearly) an earlier line of the call instead of the new words."""
        def norm(value: str) -> str:
            return re.sub(r"[\W_]+", "", (value or "").casefold())
        mine = norm(text)
        if len(mine) < 12:
            return False
        return any(difflib.SequenceMatcher(None, mine, norm(old)).ratio() >= 0.6 for old in earlier if norm(old))

    async def _plain_relay(self, text: str, listener_lang: str) -> tuple[RelayOut | None, bool]:
        """Evon's structured reply failed twice: keep the call going with a plain translation."""
        message = await self._translate(text, listener_lang)
        if not message:
            return None, False
        gloss = message if listener_lang == "en-IN" else await self._translate(text, "en-IN")
        return RelayOut(message_for_listener=message, gloss_en=gloss), True

    async def _ask_for_landmark(self, s: Session, reason: str) -> None:
        """Ask the customer, in their language, for one more landmark. At most twice per call."""
        if s.more_asked >= 2:
            self.add_log(s, kind="system", for_role="staff", text=f"{reason} Pata has already asked twice, so it is waiting.")
            await self.set_status(s, "", busy=False)
            return
        s.more_asked += 1
        question, gloss = await self._more_landmark_question(s.customer_lang), MORE_LANDMARK["en-IN"]
        s.pending_question = None
        s.searched_signature = ""
        self.add_log(s, kind="question", text=question, gloss_en=gloss, reason=reason, options=[])
        await self.set_status(s, "", busy=False)
        await self.say(s, "customer", question, kind="question", gloss=gloss)

    @staticmethod
    def _tokens(text: str | None) -> list[str]:
        return [t for t in (w.strip(".,!?;:'\"()[]{}।|-").casefold() for w in (text or "").split()) if len(t) >= 3]

    @staticmethod
    def _from_earlier_turns(landmark: Landmark, transcript: str, earlier: list[dict]) -> bool:
        """True when Evon took a landmark from earlier in the call (say, the rider's own location)
        rather than from the words the customer just said."""
        words = Pata._tokens(landmark.heard) + Pata._tokens(landmark.name_hint_en)
        distinctive = [w for w in words if w not in geo._GENERIC_WORDS]
        if not distinctive:
            return False
        now = transcript.casefold()
        if any(w in now for w in distinctive):
            return False
        before = " ".join(f"{e.get('text', '')} {e.get('gloss_en', '')} {e.get('relayed') or ''}" for e in earlier).casefold()
        return any(w in before for w in distinctive)

    @staticmethod
    def _basic_note(s: Session, existing: dict | None) -> NoteOut:
        """The doorstep note from facts the app already has, for when Evon can't write one."""
        site = s.site(s.resolved_site_id)
        b = s.building
        places = [p.name for p in site.members] if site else list((existing or {}).get("landmarks", []))
        looks = f"{b.colour} building" if b.colour else "The building"
        description = f"{looks} near {', '.join(places)}" if places else looks
        return NoteOut(building_description=description, landmarks=places, entrance=b.entrance, floor=b.floor,
                       summary_en=f"{description}. Entrance: {b.entrance or 'not noted'}. Floor: {b.floor or 'not noted'}.")

    async def _more_landmark_question(self, lang: str) -> str:
        return MORE_LANDMARK.get(lang) or await self._translate(MORE_LANDMARK["en-IN"], lang) or MORE_LANDMARK["en-IN"]

    async def apply_setup_to_open_calls(self, before: dict, after: dict) -> None:
        """Name, address, order and languages changed in the control room also reach calls that
        are already open. A moved pin only applies to the next call session."""
        for s in list(self.sessions.values()):
            s.order.update(customer_name=after["customer_name"], address_text=after["address_text"],
                           items=after["items"])
            s.prisma_hints = after["prisma_hints"]
            changes = [("customer", after["customer_lang"], after["customer_auto"],
                        (before["customer_lang"], before["customer_auto"]))]
            if s.rider["id"] == after["rider_id"]:
                changes.append(("rider", after["rider_lang"], after["rider_auto"],
                                (before["rider_lang"], before["rider_auto"])))
            for role, code, auto, old in changes:
                if (code, auto) != old:
                    state = s.langs[role]
                    state.code, state.auto, state.source, state.confirmed, state.candidate = code, auto, "picked", False, None
            await self.publish(s)

    # ------------------------------------------------------------------ sessions

    def start_session(self, order_id: str, rider_id: str, customer_lang: str | None = None,
                      customer_auto: bool | None = None, rider_lang: str | None = None,
                      rider_auto: bool | None = None) -> Session:
        """Who, where and which languages: explicit arguments win, then the control-room setup,
        then the profiles in orders_demo.json. A language with auto off is fixed for the call;
        with auto on, Prisma detects it on every turn and Evon double-checks."""
        order = dict(next(o for o in self.orders["orders"] if o["id"] == order_id))
        rider = dict(next(r for r in self.orders["riders"] if r["id"] == rider_id))
        setup = self.setup.get() if self.setup else {}
        if setup:
            order.update(customer_name=setup["customer_name"], address_text=setup["address_text"],
                         items=setup["items"], pin=dict(setup["pin"]))
        same_rider = setup.get("rider_id") == rider_id
        c_lang = customer_lang or setup.get("customer_lang") or order.get("customer_lang_hint") or "hi-IN"
        c_auto = customer_auto if customer_auto is not None else setup.get("customer_auto", False)
        r_lang = rider_lang or (setup.get("rider_lang") if same_rider else None) or rider["lang"]
        r_auto = rider_auto if rider_auto is not None else (setup.get("rider_auto", False) if same_rider else False)
        pin = order["pin"]
        note = self.notes.get(order["address_id"])
        s = Session(
            id=uuid.uuid4().hex[:8],
            order=order,
            rider=rider,
            langs={
                "rider": LangState(r_lang, "profile" if r_lang == rider["lang"] else "picked", auto=r_auto),
                "customer": LangState(c_lang, "profile" if c_lang == order.get("customer_lang_hint") else "picked",
                                      auto=c_auto),
            },
            modes=self.settings.modes(),
            rider_pos={"lat": pin["lat"], "lon": pin["lon"], "heading": 0.0},
            prisma_hints=setup.get("prisma_hints", True),
        )
        if note:
            s.note = note
            fix = note.get("pin_correction")
            if fix:
                s.destination = {"lat": fix["lat"], "lon": fix["lon"], "source": "doorstep note",
                                 "label": note.get("building_description") or "Customer's building"}
                s.pin_is_wrong = True
        self.sessions[s.id] = s
        return s

    async def join(self, session_id: str, role: str) -> None:
        s = self.get(session_id)
        if role in s.joined:
            await self.publish(s)
            return
        s.joined.add(role)
        s.langs[role].disclosed_in = s.lang_of(role)
        line, line_en = phrases.disclosure(s.lang_of(role)), phrases.disclosure("en-IN")
        self.add_log(s, kind="system", for_role=role, text=line, gloss_en=line_en)
        await self.publish(s)
        await self.say(s, role, line, kind="disclosure", gloss=line_en)
        if role == "rider" and s.note:
            await self.brief(s)

    # ------------------------------------------------------------------ a turn of speech

    def prisma_languages(self, s: Session, role: str) -> list[str] | None:
        """Language set in the control room: Prisma is told to expect it, plus English so
        code-mixed speech (Hinglish, Tanglish, Benglish) still works. Detect automatically:
        indic-auto, so Prisma reports the language it actually heard."""
        state = s.langs[role]
        if state.auto and not (self.settings.prisma_lock_language and state.confirmed):
            return None
        return [state.code] if state.code == "en-IN" else [state.code, "en-IN"]

    def keyterms_for(self, s: Session, role: str) -> list[str]:
        """Nearby place names as hints for Prisma, in English plus the speaker's own script only."""
        if not s.prisma_hints:
            return []
        state = s.langs[role]
        pin = s.order["pin"]
        return self.places.keyterms(pin["lat"], pin["lon"], self.settings.search_radius_m,
                                    limit=self.settings.prisma_keyterms_max,
                                    local_langs=set() if state.auto else {state.code})

    def topic(self, s: Session) -> str:
        # No city or region here: naming a place could nudge Prisma towards that region's language.
        return ("A phone call between a delivery rider and a customer. They are trying to find the "
                "customer's building using landmarks such as temples, shops, pharmacies, bus stops, "
                "gates and floor numbers.")

    async def handle_turn(self, session_id: str, role: str, *, audio: bytes | None = None, text: str | None = None) -> None:
        s = self.get(session_id)
        listener = OTHER[role]
        action: tuple[str, str | None] | None = None
        async with s.turn_lock:
            await self.set_status(s, "Transcribing…" if audio else "Reading the message…")
            try:
                if text and text.strip():
                    heard = Transcript(text=text.strip(), language=None, source="typed")
                else:
                    heard = await self.prisma.transcribe(
                        audio or b"", languages=self.prisma_languages(s, role), keyterms=self.keyterms_for(s, role),
                        topic=self.topic(s), role=role, session_id=s.id,
                    )
            except SpeechError as exc:
                await self.fail(s, f"{exc} Try again, or type the message.", role)
                return
            if not heard.text:
                await self.fail(s, "Prisma heard nothing. Hold the phone closer and try again.", role)
                return

            listener_lang = s.lang_of(listener)
            entry = self.add_log(
                s, kind="turn", speaker=role, text=heard.text, language=heard.language or s.lang_of(role),
                source=heard.source, relayed=None, relayed_lang=listener_lang, gloss_en="", script_ok=True,
            )
            await self.set_status(s, "Evon is working out what was meant…")
            earlier = [e for e in s.log if e.get("kind") == "turn" and e is not entry]
            payload = {
                "speaker": role,
                "listener": listener,
                "listener_language": listener_lang,
                "listener_language_name": languages.name(listener_lang),
                "listener_script": languages.script(listener_lang),
                # Background in English only, so there's no earlier line in the listener's language to copy.
                "earlier_turns_in_english": [{"speaker": e["speaker"], "meaning": e["gloss_en"]}
                                             for e in earlier[-4:] if e.get("gloss_en")],
                "pending_question": s.pending_question if role == "customer" else None,
                "transcript": heard.text,  # last, so it's the freshest thing the model reads
            }
            try:
                relay, ok = await self._checked(self.evon.relay, payload, listener_lang, "message_for_listener")
            except EvonError as exc:
                relay, ok = await self._plain_relay(heard.text, listener_lang)
                if relay is None:
                    await self.fail(s, f"Evon could not relay this turn, so nothing was sent. Say it again, or type it. "
                                       f"(Details: {exc})", role)
                    return
                self.add_log(s, kind="system", for_role="staff",
                             text=f"Evon's structured reply failed ({str(exc)[:120]}), so Pata used a plain "
                                  "translation. Landmarks in this turn were skipped.")
            earlier_lines = [t for e in earlier for t in (e.get("text"), e.get("relayed")) if t]
            if not self.settings.mock_evon and self._looks_copied(relay.message_for_listener, earlier_lines):
                gloss_copied = self._looks_copied(relay.gloss_en, [e.get("gloss_en") or "" for e in earlier])
                source = heard.text if gloss_copied else (relay.gloss_en or heard.text)
                fixed = await self._translate(source, listener_lang)
                if fixed:
                    relay.message_for_listener, ok = fixed, True
                    self.add_log(s, kind="system", for_role="staff",
                                 text="Evon repeated an earlier line of the call instead of relaying this one, "
                                      "so Pata translated it again.")
            entry.update(relayed=relay.message_for_listener, gloss_en=relay.gloss_en, script_ok=ok)

            # Whose language is it? Prisma's detection, checked against Evon's reading of the same words.
            typed = heard.source == "typed"
            verdict = language_tracking.update(s.langs[role], prisma_lang=heard.language,
                                               evon_lang=relay.speaker_language, transcript=heard.text, typed=typed)
            if typed and languages.is_supported(relay.speaker_language):
                entry["language"] = relay.speaker_language
            entry["language_note"] = verdict.note
            if verdict.switched:
                person = s.rider["name"] if role == "rider" else s.order["customer_name"]
                self.add_log(s, kind="language", role=role, typed=typed,
                             text=f"{person} speaks {languages.name(s.lang_of(role))}. {verdict.note}")

            if role == "customer":
                # Only what the customer just said counts, never the rider's earlier words.
                borrowed = [lm for lm in relay.landmarks if self._from_earlier_turns(lm, heard.text, earlier)]
                if borrowed:
                    relay.landmarks = [lm for lm in relay.landmarks if lm not in borrowed]
                    self.add_log(s, kind="system", for_role="staff",
                                 text="Ignored " + ", ".join(lm.name_hint_en or lm.heard for lm in borrowed)
                                      + ": that came from earlier in the call, not from what the customer just said.")
                # Evon may list no landmarks (a small model often skips them when the customer gives an
                # instruction, and a plain-translation fallback has none at all). Look for place names in
                # her words too, so a named place is never ignored.
                spotted = self._spot_landmarks(s, [heard.text, relay.gloss_en], relay.landmarks)
                if spotted:
                    relay.landmarks.extend(spotted)
                    heard_names = ", ".join(f'"{lm.heard}"' for lm in spotted)
                    lead = "Evon listed no landmarks" if len(spotted) == len(relay.landmarks) else f"Evon missed {heard_names}"
                    self.add_log(s, kind="system", for_role="staff", text=(
                        f"{lead}, but Pata spotted {heard_names} in what {s.order['customer_name']} said and "
                        f"searched the map for {', '.join(lm.name_hint_en for lm in spotted)}."))
                action = self.absorb(s, relay)
                if action is None and not s.destination and not relay.landmarks and not s.pending_question:
                    self.add_log(s, kind="system", for_role="staff",
                                 text=f"Nothing {s.order['customer_name']} said names a place on the map, so Pata "
                                      f"didn't search. If {s.order['customer_name']} named one, add it with "
                                      "\"Add a missing place\".")
            await self.set_status(s, "", busy=False)
            await self.say(s, listener, relay.message_for_listener, kind="relay", gloss=relay.gloss_en,
                           language=self._voice_language(relay.message_for_listener, listener_lang, ok))
            state = s.langs[role]
            if verdict.switched and state.disclosed_in and state.disclosed_in != state.code:
                # Tell them again, in the language they actually speak, that an AI is translating.
                line, line_en = phrases.disclosure(state.code), phrases.disclosure("en-IN")
                state.disclosed_in = state.code
                self.add_log(s, kind="system", for_role=role, text=line, gloss_en=line_en)
                await self.publish(s)
                await self.say(s, role, line, kind="disclosure", gloss=line_en)

        if action and action[0] == "resolve":
            site = s.site(action[1])
            option = next((o for o in (s.pending_question or {}).get("options", []) if o["id"] == action[1]), {})
            await self.resolve(s, site, f"The customer answered Pata's question: {option.get('label') or action[1]}.", 0.9)
        elif action and action[0] == "match":
            await self.match(s)
        elif action and action[0] == "ask_more":
            await self._ask_for_landmark(s, "The customer described the place but named nothing Pata can look up on the map.")

    def _spot_landmarks(self, s: Session, texts: list[str], listed: list[Landmark]) -> list[Landmark]:
        """Places near the pin named in the customer's words that no landmark covers yet."""
        pin = s.order["pin"]
        nearby = [place for place, _ in self.places.near(pin["lat"], pin["lon"], self.settings.search_radius_m)]
        known = [*s.landmarks, *listed]
        spotted: list[Landmark] = []
        for place, said in geo.spot_places(" ".join(t for t in texts if t), nearby):
            covered = any(geo.name_score(lm.name_hint_en or geo.heard_name(lm.heard), place) >= geo.NAME_MATCH
                          for lm in [*known, *spotted] if lm.name_hint_en or geo.heard_name(lm.heard))
            if not covered:
                spotted.append(Landmark(heard=said, kind=place.kind, relation="unknown", name_hint_en=place.name))
        return spotted

    @staticmethod
    def _same(a: Landmark, b: Landmark) -> bool:
        return a.kind == b.kind and ((a.name_hint_en or "").lower() == (b.name_hint_en or "").lower() or a.heard == b.heard)

    def absorb(self, s: Session, relay: RelayOut) -> tuple[str, str | None] | None:
        """Fold the customer's facts into the session and decide what happens next."""
        s.building = s.building.merged_with(relay.building)
        if s.pending_question and relay.answer_option_id:
            if relay.answer_option_id in {o["id"] for o in s.pending_question.get("options", [])}:
                return ("resolve", relay.answer_option_id)
        for landmark in relay.landmarks:
            if not any(self._same(landmark, known) for known in s.landmarks):
                s.landmarks.append(landmark)
        if s.destination:
            if relay.landmarks and s.destination.get("source") == "doorstep note" and not s.told_note_known:
                s.told_note_known = True
                self.add_log(s, kind="system", for_role="staff",
                             text="Pata already knows this address from its doorstep note, so it didn't search the "
                                  "map again. Clear doorstep notes to test the search.")
            return None
        def name(lm: Landmark) -> str:
            return (lm.name_hint_en or "").strip() or geo.heard_name(lm.heard)

        searchable = [lm for lm in s.landmarks if lm.kind not in _UNSEARCHABLE or name(lm)]
        signature = "|".join(sorted(f"{lm.kind}:{name(lm).lower()}" for lm in searchable))
        if signature and signature != s.searched_signature:
            s.searched_signature = signature
            return ("match", None)
        described = bool(relay.landmarks) or any(relay.building.model_dump().values())
        if not searchable and described:
            return ("ask_more", None)
        return None

    # ------------------------------------------------------------------ finding the place

    async def match(self, s: Session) -> None:
        async with s.match_lock:
            pin = s.order["pin"]
            await self.set_status(s, "Checking the map for the places the customer mentioned…")
            unknown: list[str] = []
            s.sites = self.places.candidate_sites(
                pin["lat"], pin["lon"], s.landmarks,
                search_radius_m=self.settings.search_radius_m,
                cluster_radius_m=self.settings.cluster_radius_m,
                feature_radius_m=self.settings.feature_radius_m,
                unknown=unknown,
            )
            if unknown:
                self.add_log(s, kind="system", for_role="staff",
                             text=f"Not on the map: {', '.join(unknown)}. Add it in the control room with "
                                  "\"Add a missing place\" so Pata can find it.")
            if not s.sites:
                heard = ", ".join(lm.name_hint_en or lm.heard or lm.kind for lm in s.landmarks)
                self.add_log(s, kind="system", for_role="staff",
                             text=f"No place on the map matches what the customer said ({heard}). Add missing places in the "
                                  "control room with \"Add a missing place\", or load real places.")
                await self.publish(s)
                await self._ask_for_landmark(s, "No place on the map matches what the customer described.")
                return
            await self.set_status(s, "Evon is comparing the landmarks with the map…")
            payload = {
                "customer_language": s.customer_lang,
                "customer_language_name": languages.name(s.customer_lang),
                "customer_script": languages.script(s.customer_lang),
                "heard_landmarks": [lm.model_dump() for lm in s.landmarks],
                "building": s.building.model_dump(),
                "customer_words": [e["text"] for e in s.log if e.get("kind") == "turn" and e["speaker"] == "customer"][-4:],
                "candidates": [site.for_prompt() for site in s.sites],
            }
            try:
                result = await self.evon.match(payload)
            except EvonError as exc:
                if len(s.sites) == 1:
                    await self.resolve(s, s.sites[0], "Only one place on the map fits what the customer said.", 0.6)
                else:
                    self.add_log(s, kind="system", for_role="staff",
                                 text=f"Evon couldn't compare the places ({str(exc)[:100]}).")
                    await self._ask_for_landmark(s, "Evon couldn't decide between the places on the map.")
                return
            await self.act_on_match(s, result)

    async def act_on_match(self, s: Session, m: MatchOut) -> None:
        ids = {site.id for site in s.sites}
        if m.decision == "resolved" and (m.site_id in ids or len(s.sites) == 1):
            await self.resolve(s, s.site(m.site_id) or s.sites[0], m.reason, m.confidence)
            return
        options = [o.model_dump() for o in m.options if o.id in ids]
        question = (m.question_for_customer or "").strip()
        lang_ok = self.settings.mock_evon or languages.script_ok(question, s.customer_lang)
        if question and not lang_ok:
            translated = await self._translate(m.question_gloss_en or question, s.customer_lang)
            if translated:
                question, lang_ok = translated, True
        if m.decision == "ask" and len(options) >= 2 and question and lang_ok:
            gloss = m.question_gloss_en or " or ".join(o["label"] for o in options)
            s.pending_question = {"text": question, "gloss_en": gloss, "options": options, "reason": m.reason}
            self.add_log(s, kind="question", text=question, gloss_en=gloss, reason=m.reason, options=options)
        else:
            if question and lang_ok and m.decision == "not_found":
                gloss = m.question_gloss_en or MORE_LANDMARK["en-IN"]
            else:  # Evon's own question was unusable: ask the fixed one, and caption it with its real meaning
                question, gloss = await self._more_landmark_question(s.customer_lang), MORE_LANDMARK["en-IN"]
            s.pending_question = None
            s.searched_signature = ""  # search again when she names another place
            s.more_asked += 1
            self.add_log(s, kind="question", text=question, gloss_en=gloss,
                         reason=m.reason or "No place on the map fits yet.", options=[])
        await self.set_status(s, "", busy=False)
        await self.say(s, "customer", question, kind="question", gloss=gloss)

    async def resolve(self, s: Session, site: Site | None, reason: str, confidence: float) -> None:
        if site is None:
            await self.fail(s, "That place is no longer on the candidate list. Ask the customer for one more landmark.")
            return
        s.resolved_site_id = site.id
        s.pending_question = None
        s.pin_is_wrong = site.distance_from_pin_m > self.settings.near_pin_m
        s.destination = {"lat": site.lat, "lon": site.lon, "label": site.label(), "source": "matched"}
        self.add_log(
            s, kind="resolved", site_id=site.id, label=site.label(), reason=reason,
            confidence=round(confidence, 2), pin_is_wrong=s.pin_is_wrong,
            distance_from_pin_m=geo.round_distance(site.distance_from_pin_m),
            direction_from_pin=site.direction_from_pin,
        )
        await self.publish(s)
        await self.give_directions(s)

    # ------------------------------------------------------------------ guiding the rider

    async def give_directions(self, s: Session) -> None:
        if not s.destination:
            return
        dest = s.destination
        facts = geo.directions(s.rider_pos, dest["lat"], dest["lon"], self.settings.arrive_radius_m)
        site = s.site(s.resolved_site_id)
        note = s.note or {}
        building = s.building.model_dump()
        if not any(building.values()):
            building = {"entrance": note.get("entrance"), "floor": note.get("floor")}
        facts.update({
            "landmarks_at_destination": [p.name for p in site.members] if site else note.get("landmarks", []),
            "nearby_features": [p.name for p in site.features[:3]] if site else [],
            "building": building,
            "pin_is_wrong": s.pin_is_wrong,
        })
        payload = {
            "rider_language": s.rider_lang,
            "rider_language_name": languages.name(s.rider_lang),
            "rider_script": languages.script(s.rider_lang),
            "facts": facts,
        }
        await self.set_status(s, "Writing directions for the rider…")
        try:
            out, ok = await self._checked(self.evon.directions, payload, s.rider_lang, "say")
        except EvonError as exc:
            await self.fail(s, f"Evon could not write the directions. {exc}")
            return
        s.directions = {"kind": "directions", "text": out.say, "gloss_en": out.gloss_en, "facts": facts}
        self.add_log(s, kind="directions", for_role="rider", text=out.say, gloss_en=out.gloss_en,
                     facts=facts, script_ok=ok)
        await self.set_status(s, "", busy=False)
        await self.say(s, "rider", out.say, kind="directions", gloss=out.gloss_en, slow=True,
                       language=self._voice_language(out.say, s.rider_lang, ok))

    async def update_position(self, session_id: str, lat: float, lon: float, heading: float) -> None:
        s = self.get(session_id)
        s.rider_pos = {"lat": lat, "lon": lon, "heading": heading % 360}
        if s.destination and not s.arrived:
            gap = geo.haversine_m(lat, lon, s.destination["lat"], s.destination["lon"])
            if gap <= self.settings.arrive_radius_m:
                s.arrived = True
                await self.publish(s)
                await self.give_directions(s)  # facts say arrived: entrance and floor only
                return
        await self.publish(s)

    async def repeat_directions(self, session_id: str) -> None:
        s = self.get(session_id)
        if s.destination:
            await self.give_directions(s)

    async def replay_note(self, session_id: str) -> None:
        """Read the doorstep note to the rider again, in the rider's language. Picks up a note
        written after this session started, so a rider is never stuck without it."""
        s = self.get(session_id)
        s.note = self.notes.get(s.order["address_id"]) or s.note
        if s.note:
            await self.brief(s)
        else:
            await self.fail(s, "There is no doorstep note for this address yet. One is written when a "
                               "rider marks an order delivered.")

    # ------------------------------------------------------------------ remembering the doorstep

    async def mark_delivered(self, session_id: str) -> None:
        s = self.get(session_id)
        if s.delivered:
            return
        s.delivered = True  # the rider's screen changes at once; the note is written afterwards
        address_id = s.order["address_id"]
        existing = self.notes.get(address_id)
        site = s.site(s.resolved_site_id)
        saved = s.order["pin"]
        # Where was it really? The matched building, or else where the rider was when he delivered.
        spot = s.destination or s.rider_pos
        pin_wrong = geo.haversine_m(saved["lat"], saved["lon"], spot["lat"], spot["lon"]) > self.settings.near_pin_m
        await self.set_status(s, "Evon is writing the doorstep note for the next rider…")
        payload = {
            "existing_note": {k: v for k, v in (existing or {}).items()
                              if k not in {"saved_pin", "pin_correction", "address_id"}} or None,
            "customer_name": s.order["customer_name"],
            "address_text": s.order["address_text"],
            "customer_language": s.customer_lang,
            "customer_language_name": languages.name(s.customer_lang),
            "transcript": [{"speaker": e["speaker"], "meaning": e.get("gloss_en") or e["text"]}
                           for e in s.log if e.get("kind") == "turn"],
            "matched_place": site.for_prompt() if site else None,
            "pin_was_wrong": pin_wrong,
            "building": s.building.model_dump(),
        }
        try:
            out = await self.evon.note(payload)
        except EvonError as exc:
            out = self._basic_note(s, existing)
            self.add_log(s, kind="system", for_role="staff",
                         text=f"Evon couldn't write the doorstep note ({str(exc)[:100]}), so Pata saved the facts it had.")
        if pin_wrong:
            fix = {"lat": round(spot["lat"], 6), "lon": round(spot["lon"], 6)}  # from the map or GPS, never from Evon
        else:
            fix = (existing or {}).get("pin_correction")
        heard = " ".join(str(e.get(k) or "") for e in s.log if e.get("kind") == "turn"
                         for k in ("text", "gloss_en", "relayed"))
        written, changes = guard_note(out.model_dump(exclude={"pin_fix_question_for_customer", "pin_fix_gloss_en"}),
                                      s.order["address_text"], heard)
        if changes:
            self.add_log(s, kind="system", for_role="staff",
                         text="Pata corrected the doorstep note so it only says what the address and the call said: "
                              + "; ".join(changes) + ".")
        note = {
            **written,
            "address_id": address_id,
            "customer_name": s.order["customer_name"],
            "address_text": s.order["address_text"],
            "customer_language": s.customer_lang,
            "saved_pin": saved,
            "pin_correction": fix,
            "confirmed_by_customer": (existing or {}).get("confirmed_by_customer", False),
            "deliveries_learned_from": (existing or {}).get("deliveries_learned_from", 0) + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.notes.put(address_id, note)
        s.note = note
        self.add_log(s, kind="note", text=out.summary_en or "Doorstep note saved.", note=note)
        await self.set_status(s, "", busy=False)
        if pin_wrong and not note["confirmed_by_customer"]:
            question, gloss = phrases.pin_fix(s.customer_lang), phrases.pin_fix("en-IN")
            s.pin_fix_pending = True
            self.add_log(s, kind="pin_fix", for_role="customer", text=question, gloss_en=gloss)
            await self.publish(s)
            await self.say(s, "customer", question, kind="pin_fix", gloss=gloss)

    async def answer_pin_fix(self, session_id: str, accept: bool) -> None:
        """Yes: move the customer's saved pin itself to the right building, so the next order starts
        there. No: keep the pin, and let the doorstep note keep guiding riders to the right place."""
        s = self.get(session_id)
        note = self.notes.get(s.order["address_id"])
        moved = False
        if note:
            note["confirmed_by_customer"] = accept
            fix = note.get("pin_correction")
            if accept and fix:
                if self.setup:
                    self.setup.update({"pin": fix})
                note["saved_pin"], note["pin_correction"] = fix, None
                moved = True
            self.notes.put(s.order["address_id"], note)
            s.note = note
        s.pin_fix_pending = False
        if accept:
            text = ("The customer agreed, so the saved pin now points at the right building."
                    if moved else "The customer agreed.")
        else:
            text = "The customer kept the saved location. The doorstep note still guides riders to the right building."
        self.add_log(s, kind="system", for_role="staff", text=text, gloss_en=text)
        await self.publish(s)

    async def brief(self, s: Session) -> None:
        note = s.note or {}
        move = None
        if note.get("pin_correction"):
            saved, fix = note.get("saved_pin") or s.order["pin"], note["pin_correction"]
            move = {
                "distance_m": geo.round_distance(geo.haversine_m(saved["lat"], saved["lon"], fix["lat"], fix["lon"])),
                "compass": geo.compass(geo.bearing_deg(saved["lat"], saved["lon"], fix["lat"], fix["lon"])),
            }
        checked, _ = guard_note(note, s.order["address_text"])  # old notes: the address's room number wins
        payload = {
            "rider_name": s.rider["name"],
            "customer_name": s.order["customer_name"],
            "address_text": s.order["address_text"],
            "rider_language": s.rider_lang,
            "rider_language_name": languages.name(s.rider_lang),
            "rider_script": languages.script(s.rider_lang),
            "customer_language_name": languages.name(note.get("customer_language") or s.customer_lang),
            "note": {k: v for k, v in checked.items()
                     if k not in {"saved_pin", "pin_correction", "address_id", "customer_name", "address_text",
                                  "updated_at", "deliveries_learned_from", "confirmed_by_customer"}},
            "from_saved_pin": move,
        }
        await self.set_status(s, "Evon is reading the doorstep note…")
        try:
            out, ok = await self._checked(self.evon.briefing, payload, s.rider_lang, "say")
        except EvonError as exc:
            await self.fail(s, f"Evon could not read the doorstep note. {exc}")
            return
        s.directions = {"kind": "briefing", "text": out.say, "gloss_en": out.gloss_en, "facts": move}
        self.add_log(s, kind="briefing", for_role="rider", text=out.say, gloss_en=out.gloss_en, script_ok=ok)
        await self.set_status(s, "", busy=False)
        await self.say(s, "rider", out.say, kind="briefing", gloss=out.gloss_en, slow=True,
                       language=self._voice_language(out.say, s.rider_lang, ok))
