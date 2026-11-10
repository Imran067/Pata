"""A rule-based stand-in for Evon, for building the UI before the GPU server is up.

It only understands the demo script and a handful of keywords. Its generated sentences
are English and start with "(mock)", so nobody mistakes them for Evon. Record your demo
video in live mode.
"""
from __future__ import annotations

import re

from ..models import BuildingFacts, Landmark, MatchOption, MatchOut, NoteOut, RelayOut, SayOut

KIND_WORDS: dict[str, list[str]] = {
    "temple": ["கோவில்", "கோயில்", "kovil", "koil", "temple", "mandir", "मंदिर", "মন্দির"],
    "pharmacy": ["பார்மசி", "மருந்தகம்", "மெடிக்கல்", "pharmacy", "medical", "chemist",
                 "फ़ार्मेसी", "फार्मेसी", "मेडिकल", "apollo", "அப்போலோ", "अपोलो"],
    "bus_stop": ["பஸ் ஸ்டாப்", "பேருந்து நிறுத்தம்", "bus stop", "बस स्टॉप", "বাস স্টপ"],
    "petrol_pump": ["பெட்ரோல்", "petrol", "पेट्रोल", "bunk", "পেট্রোল"],
    "school": ["பள்ளி", "school", "स्कूल"],
    "hospital": ["மருத்துவமனை", "hospital", "अस्पताल"],
    "park": ["பூங்கா", "park", "पार्क"],
    "church": ["தேவாலயம்", "church", "चर्च"],
    "mosque": ["மசூதி", "masjid", "mosque", "मस्जिद"],
    "hostel": ["hostel", "ஹாஸ்டல்", "हॉस्टल", "হোস্টেল", "హాస్టల్"],
    "sports": ["swimming pool", "stadium", "ஸ்விம்மிங் பூல்", "स्विमिंग पूल"],
}
NAME_HINTS = {
    "Murugan": ("temple", ["முருகன்", "murugan", "मुरुगन"]),
    "Apollo": ("pharmacy", ["அப்போலோ", "apollo", "अपोलो"]),
}
RELATION_WORDS = {
    "opposite": ["எதிரே", "எதிர்ல", "opposite", "सामने"],
    "next_to": ["பக்கத்துல", "பக்கத்தில்", "next to", "beside", "बगल"],
}
COLOURS = {
    "green": ["பச்சை", "green", "हरी", "हरा", "সবুজ"],
    "yellow": ["மஞ்சள்", "yellow", "पीली", "पीला"],
    "white": ["வெள்ளை", "white", "सफ़ेद", "सफेद"],
    "blue": ["நீல", "blue", "नीली", "नीला"],
}
FLOORS = {
    "3": ["மூணாவது மாடி", "மூன்றாவது மாடி", "third floor", "तीसरी"],
    "2": ["ரெண்டாவது மாடி", "இரண்டாவது மாடி", "second floor", "दूसरी"],
    "1": ["முதல் மாடி", "first floor", "पहली"],
}
ENTRANCES = {
    "back gate": ["பின்னாடி கேட்", "பின் கேட்", "back gate", "पीछे वाले गेट", "पीछे का गेट"],
    "front gate": ["முன்னாடி கேட்", "முன் கேட்", "front gate", "आगे वाले गेट"],
}
KIND_EN = {
    "bus_stop": "bus stop", "petrol_pump": "petrol bunk", "school": "school", "park": "park",
    "hospital": "hospital", "church": "church", "mosque": "mosque", "market": "market",
    "bank": "bank", "atm": "ATM", "restaurant": "restaurant", "shop": "shop",
    "temple": "temple", "pharmacy": "pharmacy", "building": "building",
}
KIND_TA = {
    "bus_stop": "பஸ் ஸ்டாப்", "petrol_pump": "பெட்ரோல் பங்க்", "school": "பள்ளி", "park": "பூங்கா",
    "hospital": "மருத்துவமனை", "church": "தேவாலயம்", "mosque": "மசூதி", "market": "மார்க்கெட்",
    "bank": "வங்கி", "atm": "ஏடிஎம்", "restaurant": "ஹோட்டல்", "shop": "கடை",
    "temple": "கோவில்", "pharmacy": "பார்மசி", "building": "கட்டிடம்",
}
# Features a customer can easily confirm, best first.
_FEATURE_PRIORITY = ["bus_stop", "petrol_pump", "school", "hospital", "park", "church", "mosque",
                     "market", "bank", "atm", "restaurant", "shop", "building"]


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "").casefold()


def _first(text: str, words: list[str]) -> str | None:
    low = text.casefold()
    for word in words:
        if word.casefold() in low:
            return word
    return None


class MockEvonTasks:
    def __init__(self, script_lines: list[dict]):
        self.lines = script_lines

    def _scripted(self, text: str) -> dict | None:
        key = _norm(text)
        return next((line for line in self.lines if _norm(line["text"]) == key), None)

    def _extract(self, text: str) -> tuple[list[Landmark], BuildingFacts]:
        landmarks: list[Landmark] = []
        for kind, words in KIND_WORDS.items():
            heard = _first(text, words)
            if not heard:
                continue
            hint = next((name for name, (k, ws) in NAME_HINTS.items() if k == kind and _first(text, ws)), None)
            relation = "unknown"
            if kind == "temple" and _first(text, RELATION_WORDS["opposite"]):
                relation = "opposite"
            elif kind == "pharmacy" and _first(text, RELATION_WORDS["next_to"]):
                relation = "next_to"
            landmarks.append(Landmark(heard=heard, kind=kind, relation=relation, name_hint_en=hint))
        building = BuildingFacts(
            colour=next((c for c, ws in COLOURS.items() if _first(text, ws)), None),
            floor=next((f for f, ws in FLOORS.items() if _first(text, ws)), None),
            entrance=next((e for e, ws in ENTRANCES.items() if _first(text, ws)), None),
        )
        return landmarks, building

    async def relay(self, payload: dict) -> RelayOut:
        transcript = payload["transcript"]
        line = self._scripted(transcript)
        listener_lang = payload["listener_language"]
        if line and listener_lang in line.get("translations", {}):
            message, gloss = line["translations"][listener_lang], line.get("gloss_en", "")
        else:
            message = f"(mock) {transcript}"
            gloss = "(mock) Evon writes the real translation in live mode."
        landmarks, building = ([], BuildingFacts())
        answer = None
        if payload["speaker"] == "customer":
            landmarks, building = self._extract(transcript)
            pending = payload.get("pending_question") or {}
            for option in pending.get("options", []):
                words = KIND_WORDS.get(option.get("feature_kind") or "", [])
                if words and _first(transcript, words):
                    answer = option["id"]
                    break
            if answer:
                # An answer to Pata's question is not a new description of the building.
                landmarks = [lm for lm in landmarks if lm.kind not in {"bus_stop", "petrol_pump"}]
        return RelayOut(message_for_listener=message, gloss_en=gloss, landmarks=landmarks,
                        building=building, answer_option_id=answer,
                        speaker_language=line["lang"] if line else None)

    async def match(self, payload: dict) -> MatchOut:
        candidates = payload.get("candidates") or []
        tamil = payload.get("customer_language") == "ta-IN"
        if not candidates:
            return MatchOut(
                decision="not_found",
                reason="(mock) No place on the map matches these landmarks yet.",
                question_for_customer=(
                    "உங்கள் கட்டிடத்திற்கு அருகில் இருக்கும் இன்னொரு அடையாளம் சொல்ல முடியுமா?"
                    if tamil else "Can you tell me one more landmark near your building?"
                ),
                question_gloss_en="Can you tell me one more landmark near your building?",
            )
        pool = [c for c in candidates if c.get("covers_all_landmarks")] or candidates
        if len(pool) == 1:
            site = pool[0]
            return MatchOut(
                decision="resolved", site_id=site["site_id"],
                pin_is_wrong=site["distance_from_pin_m"] > 150, confidence=0.8,
                reason=f"(mock) Only {site['site_id']} has all the places the customer mentioned.",
            )
        kinds = [{f["kind"] for f in c.get("nearby_features", [])} for c in pool]
        picks: list[tuple[dict, str]] = []
        for index, site in enumerate(pool):
            others = set().union(*(k for j, k in enumerate(kinds) if j != index))
            unique = [k for k in _FEATURE_PRIORITY if k in kinds[index] - others]
            if unique:
                picks.append((site, unique[0]))
            if len(picks) == 2:
                break
        if len(picks) < 2:
            site = pool[0]
            return MatchOut(decision="resolved", site_id=site["site_id"], confidence=0.4,
                            pin_is_wrong=site["distance_from_pin_m"] > 150,
                            reason="(mock) Several sites fit and nothing separates them; picked the nearest.")
        (site_a, kind_a), (site_b, kind_b) = picks
        en_a, en_b = KIND_EN.get(kind_a, kind_a), KIND_EN.get(kind_b, kind_b)
        question_en = f"Is your building near the {en_a}, or near the {en_b}?"
        question = (
            f"உங்கள் கட்டிடம் {KIND_TA.get(kind_a, en_a)} அருகிலா, அல்லது {KIND_TA.get(kind_b, en_b)} அருகிலா?"
            if tamil else question_en
        )
        return MatchOut(
            decision="ask", confidence=0.5,
            reason=f"(mock) {site_a['site_id']} and {site_b['site_id']} both fit. Only {site_a['site_id']} has a {en_a}; only {site_b['site_id']} has a {en_b}.",
            question_for_customer=question, question_gloss_en=question_en,
            options=[
                MatchOption(id=site_a["site_id"], label=f"near the {en_a}", feature_kind=kind_a),
                MatchOption(id=site_b["site_id"], label=f"near the {en_b}", feature_kind=kind_b),
            ],
        )

    async def directions(self, payload: dict) -> SayOut:
        f = payload["facts"]
        building = f.get("building") or {}
        door = ", ".join(x for x in [building.get("entrance"), f"floor {building['floor']}" if building.get("floor") else None] if x)
        if f.get("arrived"):
            text = f"(mock) You have reached the place. {door}." if door else "(mock) You have reached the place."
        else:
            places = ", ".join(f.get("landmarks_at_destination") or [])
            text = f"(mock) The building is {f['distance_m']} m {f['relative'].replace('-', ' ')} of you, to the {f['compass']}, near {places}."
        return SayOut(say=text, gloss_en=text)

    async def note(self, payload: dict) -> NoteOut:
        b = payload.get("building") or {}
        site = payload.get("matched_place") or {}
        places = [p["name"] for p in site.get("places", [])]
        colour = f"{b['colour']} building" if b.get("colour") else "The building"
        tamil = payload.get("customer_language") == "ta-IN"
        wrong = payload.get("pin_was_wrong")
        return NoteOut(
            building_description=f"{colour} next to {', '.join(places)}" if places else colour,
            landmarks=places,
            entrance=b.get("entrance"),
            floor=b.get("floor"),
            cautions=[],
            summary_en=f"(mock) {colour} by {', '.join(places)}; {b.get('entrance') or 'main entrance'}, floor {b.get('floor') or '?'}.",
            pin_fix_question_for_customer=(
                ("உங்கள் சேமித்த இடத்தை சரியான கட்டிடத்திற்கு மாற்றலாமா?" if tamil
                 else "Shall we move your saved location to the correct building?") if wrong else None
            ),
            pin_fix_gloss_en="Shall we move your saved location to the correct building?" if wrong else None,
        )

    async def translate(self, text: str, code: str) -> str:
        return f"(mock) {text}"

    async def briefing(self, payload: dict) -> SayOut:
        note = payload.get("note") or {}
        move = payload.get("from_saved_pin")
        where = f"The real building is {move['distance_m']} m {move['compass']} of the saved pin. " if move else ""
        text = f"(mock) {where}{note.get('summary_en', '')}"
        return SayOut(say=text, gloss_en=text)
