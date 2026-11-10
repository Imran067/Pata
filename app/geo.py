"""Map logic. All geometry lives here, in plain code, never in the language model.

Evon decides what people meant; this module does the arithmetic: distances, compass
directions, left or right relative to the rider, and which places sit close together.
"""
from __future__ import annotations

import difflib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .models import Landmark

EARTH_RADIUS_M = 6_371_000.0
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]
# Landmark kinds too generic to anchor a map search on their own.
_UNSEARCHABLE = {"building", "other", "junction"}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(bearing: float) -> str:
    return COMPASS[int(((bearing % 360) + 22.5) // 45) % 8]


def relative(heading: float, bearing: float) -> str:
    """Where a target is relative to the way the rider is facing."""
    diff = (bearing - heading + 540) % 360 - 180  # -180..180, positive means to the right
    size = abs(diff)
    if size <= 25:
        return "ahead"
    side = "right" if diff > 0 else "left"
    if size <= 70:
        return f"ahead-{side}"
    if size <= 135:
        return side
    return "behind"


def offset(lat: float, lon: float, bearing: float, distance_m: float) -> tuple[float, float]:
    """The point `distance_m` metres from (lat, lon) along `bearing`."""
    d = distance_m / EARTH_RADIUS_M
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def round_distance(metres: float) -> int:
    if metres < 100:
        return int(round(metres / 5.0) * 5)
    if metres < 1000:
        return int(round(metres / 10.0) * 10)
    return int(round(metres / 50.0) * 50)


@dataclass
class Place:
    id: str
    name: str
    kind: str
    lat: float
    lon: float
    local_names: dict[str, str] = field(default_factory=dict)
    source: str = ""  # "you" for places added by hand in the control room

    def all_names(self) -> list[str]:
        return [self.name, *self.local_names.values()]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "local_names": self.local_names,
            "source": self.source,
        }


@dataclass
class Site:
    """A spot where places matching the customer's landmarks sit close together."""

    id: str
    lat: float
    lon: float
    members: list[Place]
    features: list[Place]
    matched_kinds: list[str]
    covers_all: bool
    distance_from_pin_m: float
    direction_from_pin: str
    score: float

    def label(self) -> str:
        return " / ".join(p.name for p in self.members)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "label": self.label(),
            "members": [p.to_dict() for p in self.members],
            "features": [p.to_dict() for p in self.features],
            "matched_kinds": self.matched_kinds,
            "covers_all": self.covers_all,
            "distance_from_pin_m": round_distance(self.distance_from_pin_m),
            "direction_from_pin": self.direction_from_pin,
        }

    def for_prompt(self) -> dict:
        """What Evon sees: names in every script we have, kinds, and what is nearby."""

        def brief(place: Place) -> dict:
            return {"name": place.name, "local_names": place.local_names, "kind": place.kind}

        return {
            "site_id": self.id,
            "distance_from_pin_m": round_distance(self.distance_from_pin_m),
            "direction_from_pin": self.direction_from_pin,
            "covers_all_landmarks": self.covers_all,
            "places": [brief(p) for p in self.members],
            "nearby_features": [brief(p) for p in self.features],
        }


def _tokens(texts: Iterable[str]) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for word in str(text or "").replace(",", " ").replace(".", " ").split():
            word = word.strip().casefold()
            if len(word) >= 3:
                words.add(word)
    return words


NAME_MATCH = 0.8
# Words that describe rather than name a place; they don't count when matching names.
_GENERIC_WORDS = {
    "hostel", "hall", "temple", "kovil", "koil", "mandir", "road", "street", "lane", "gate", "near",
    "the", "shop", "store", "stores", "pharmacy", "medical", "medicals", "hospital", "clinic", "school",
    "college", "university", "stop", "building", "apartment", "apartments", "flat", "park", "market",
    "bank", "petrol", "bunk", "pump", "office", "department", "block", "main", "shri", "opposite",
    "next", "behind", "route", "side", "area", "colony", "nagar", "front",
}


def _words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", (text or "").casefold()).split()


def name_score(hint: str, place: "Place") -> float:
    """How well a heard name fits a place, 0..1. Tolerant of spelling (Vishveshvaraya fits
    Visvesvaraya) and of generic words ("hostel", "temple") that don't identify anything."""
    hint_words = _words(hint)
    if not hint_words:
        return 0.0
    distinctive = [w for w in hint_words if len(w) >= 4 and w not in _GENERIC_WORDS]
    joined_hint = " ".join(hint_words)
    best = 0.0
    for name in place.all_names():
        name_words = _words(name)
        if not name_words:
            continue
        if distinctive:
            for heard in distinctive:
                for word in name_words:
                    if len(word) >= 3:
                        best = max(best, difflib.SequenceMatcher(None, heard, word).ratio())
        else:
            joined_name = " ".join(name_words)
            if joined_hint in joined_name:
                best = max(best, 0.9)
            best = max(best, difflib.SequenceMatcher(None, joined_hint, joined_name).ratio())
    return best


def is_real_name(hint: str) -> bool:
    """'SN Bose Hostel' or 'Apollo' is a name; 'the hostel' or 'swimming pool' only describes."""
    return any(len(w) >= 4 and w not in _GENERIC_WORDS for w in _words(hint)) and not set(_words(hint)) <= _DESCRIPTIVE


# Descriptions that identify a place well enough on a campus, but aren't names.
_DESCRIPTIVE = {"swimming", "pool", "the", "stadium", "ground", "playground", "canteen", "library", "mess"}


# Words common in place names that are also ordinary speech, so hearing one alone doesn't mean a place.
_COMMON_WORDS = {
    "central", "public", "national", "government", "general", "service", "services", "centre", "center",
    "international", "limited", "private", "india", "indian", "state", "city", "district", "new", "old",
    "sri", "shree", "saint", "bharat", "first", "second", "third", "upper", "lower", "north", "south",
    "east", "west", "big", "small", "little", "great", "good", "sweet", "sweets", "store", "corner",
}
_INDIC = re.compile(r"[\u0900-\u0DFF]")


def name_words(text: str) -> list[str]:
    """Words of a name, with initials joined: "S. N. Bose", "S N Bose" and "SN Bose" all give sn, bose."""
    merged: list[str] = []
    run = ""
    for word in _words(text):
        if len(word) == 1 and word.isalpha() and not _INDIC.search(word):
            run += word
            continue
        if run:
            merged.append(run)
            run = ""
        merged.append(word)
    if run:
        merged.append(run)
    return merged


def _key_words(words: list[str]) -> list[str]:
    """The words that identify a place: not generic, descriptive or everyday, and long enough to trust."""
    return [w for w in words if w not in _GENERIC_WORDS and w not in _DESCRIPTIVE and w not in _COMMON_WORDS
            and (len(w) >= 4 or (_INDIC.search(w) and len(w) >= 3))]


def spot_places(text: str, places: Iterable["Place"]) -> list[tuple["Place", str]]:
    """Places whose names appear in `text`, with the words that matched.

    A safety net for when the language model lists no landmarks: if the customer said "SN Bose" and
    "S. N. Bose Hostel" is on the map nearby, that is the place she means. Every identifying word
    of the name must be heard (spelling may differ a little), or one long, unusual word of it."""
    said = name_words(text)
    if not said:
        return []
    said_set = set(said)
    found: list[tuple[Place, str]] = []
    for place in places:
        best: tuple[int, str] | None = None
        for name in place.all_names():
            words = name_words(name)
            keys = _key_words(words)
            if not keys:
                continue
            hits = []
            for key in keys:
                if key in said_set:
                    hits.append(key)
                    continue
                if len(key) < 5:
                    continue  # short words must be heard exactly
                # A respelling (Vishvakarma, Vishwakarma) starts the same and is about as long.
                near = [w for w in said if w[0] == key[0] and abs(len(w) - len(key)) <= 3]
                scored = [(difflib.SequenceMatcher(None, key, w).ratio(), w) for w in near]
                if scored and max(scored)[0] >= 0.85:
                    hits.append(max(scored)[1])
            whole = len(hits) == len(keys)
            strong = any(len(h) >= 6 for h in hits)
            if hits and (whole or strong):
                # Show the words as said, with any initials heard just before them ("sn bose").
                first = said.index(hits[0])
                start = first - 1 if first > 0 and said[first - 1] in words and said[first - 1] not in keys else first
                phrase = " ".join(said[start : said.index(hits[-1]) + 1]) if said.index(hits[-1]) >= start else hits[0]
                score = (2 if whole else 1, phrase)
                if best is None or score[0] > best[0]:
                    best = score
        if best:
            found.append((place, _as_said(text, best[1])))
    return found


def _as_said(text: str, phrase: str) -> str:
    """The phrase as it appears in the original text, capitals and dots included ("SN Bose")."""
    letters = phrase.replace(" ", "")
    pattern = r"[\W_]*".join(re.escape(ch) for ch in letters)
    match = re.search(pattern, text, re.IGNORECASE) if letters else None
    return match.group(0) if match else phrase


def heard_name(heard: str) -> str:
    """What Evon heard, when it is a proper name in English letters ("SN Bose", "Apollo"); otherwise "".

    Lets a landmark be searched by name even when Evon left name_hint_en empty."""
    heard = (heard or "").strip()
    if not heard or _INDIC.search(heard) or not any(ch.isupper() for ch in heard):
        return ""
    return heard if is_real_name(heard) else ""


class PlaceStore:
    def __init__(self, path: Path, extra: list[dict] | None = None):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.area_name: str = raw.get("area_name", "")
        self.places: list[Place] = [self._place(p) for p in [*raw["places"], *(extra or [])]]

    @staticmethod
    def _place(p: dict) -> Place:
        return Place(id=str(p["id"]), name=p["name"], kind=p["kind"], lat=float(p["lat"]), lon=float(p["lon"]),
                     local_names=p.get("local_names", {}) or {}, source=p.get("source", ""))

    def near(self, lat: float, lon: float, radius_m: float, kinds: set[str] | None = None) -> list[tuple[Place, float]]:
        found = []
        for place in self.places:
            if kinds and place.kind not in kinds:
                continue
            dist = haversine_m(lat, lon, place.lat, place.lon)
            if dist <= radius_m:
                found.append((place, dist))
        found.sort(key=lambda item: item[1])
        return found

    def keyterms(self, lat: float, lon: float, radius_m: float = 1500, limit: int = 200,
                 local_langs: set[str] | None = None) -> list[str]:
        """Names of nearby places, nearest first, as hints for Prisma (max 200 allowed).

        Only English names, plus names written in the scripts of `local_langs`. Hints in another
        script can pull a transcript into that script (Bengali speech written in Tamil letters)."""
        if limit <= 0:
            return []
        terms: list[str] = []
        seen: set[str] = set()
        for place, _ in self.near(lat, lon, radius_m):
            names = [place.name] + [place.local_names[c] for c in (local_langs or ()) if c in place.local_names]
            for name in names:
                clean = " ".join(str(name).split())
                if not clean or "<|" in clean or "|>" in clean or len(clean) > 60:
                    continue
                key = clean.casefold()
                if key not in seen:
                    seen.add(key)
                    terms.append(clean)
                if len(terms) >= limit:
                    return terms
        return terms

    def candidate_sites(
        self,
        pin_lat: float,
        pin_lon: float,
        landmarks: list[Landmark],
        *,
        search_radius_m: float = 1500,
        cluster_radius_m: float = 120,
        feature_radius_m: float = 150,
        max_sites: int = 4,
        unknown: list[str] | None = None,
    ) -> list[Site]:
        """Spots where places matching the heard landmarks sit close together.

        A landmark is looked up by its name when that name fits a nearby place, otherwise by its
        kind. A real name that fits nothing ("SN Bose Hostel" when it isn't on the map) is reported in
        `unknown` instead of being swapped for "any hostel". An unnamed generic thing ("a building")
        can't be searched on its own."""
        nearby = [place for place, _ in self.near(pin_lat, pin_lon, search_radius_m)]
        requirements: list[tuple[str, list[Place], dict[str, float]]] = []
        keys: set[str] = set()
        for landmark in landmarks:
            hint = (landmark.name_hint_en or "").strip() or heard_name(landmark.heard)
            named = [(p, score) for p in nearby if (score := name_score(hint, p)) >= NAME_MATCH] if hint else []
            if named:
                key = "name:" + " ".join(_words(hint))
                pool, scores = [p for p, _ in named], {p.id: score for p, score in named}
            elif is_real_name(hint):
                if unknown is not None and hint not in unknown:
                    unknown.append(hint)
                continue
            elif landmark.kind not in _UNSEARCHABLE:
                key = "kind:" + landmark.kind
                pool, scores = [p for p in nearby if p.kind == landmark.kind], {}
            else:
                continue
            if key not in keys:
                keys.add(key)
                requirements.append((key, pool, scores))
        searchable = [r for r in requirements if r[1]]
        if not searchable:
            return []
        anchor_key, anchor_pool, _ = min(searchable, key=lambda r: len(r[1]))

        sites: list[Site] = []
        for anchor in anchor_pool:
            members, matched = [anchor], [anchor_key]
            for key, pool, _ in requirements:
                if key == anchor_key:
                    continue
                close = [(p, haversine_m(anchor.lat, anchor.lon, p.lat, p.lon)) for p in pool if p.id != anchor.id]
                close = [item for item in close if item[1] <= cluster_radius_m]
                if close:
                    members.append(min(close, key=lambda item: item[1])[0])
                    matched.append(key)
            lat = sum(p.lat for p in members) / len(members)
            lon = sum(p.lon for p in members) / len(members)
            member_ids = {p.id for p in members}
            name_bonus = sum(max((scores.get(p.id, 0.0) for _, _, scores in requirements), default=0.0) for p in members)
            dist = haversine_m(pin_lat, pin_lon, lat, lon)
            features = [place for place, _ in self.near(lat, lon, feature_radius_m) if place.id not in member_ids][:6]
            sites.append(
                Site(
                    id="",
                    lat=lat,
                    lon=lon,
                    members=members,
                    features=features,
                    matched_kinds=[p.kind for p in members],
                    covers_all=len(matched) == len(requirements),
                    distance_from_pin_m=dist,
                    direction_from_pin=compass(bearing_deg(pin_lat, pin_lon, lat, lon)),
                    score=len(matched) * 10 + name_bonus * 3 - dist / 500,
                )
            )

        sites.sort(key=lambda site: site.score, reverse=True)
        unique: list[Site] = []
        for site in sites:
            if all(haversine_m(site.lat, site.lon, other.lat, other.lon) >= 60 for other in unique):
                unique.append(site)
        complete = [site for site in unique if site.covers_all]
        chosen = (complete or unique)[:max_sites]
        for index, site in enumerate(chosen, start=1):
            site.id = f"S{index}"
        return chosen


def directions(rider: dict, dest_lat: float, dest_lon: float, arrive_radius_m: float) -> dict:
    """Facts the app hands to Evon to phrase. Evon must not change these numbers."""
    dist = haversine_m(rider["lat"], rider["lon"], dest_lat, dest_lon)
    bearing = bearing_deg(rider["lat"], rider["lon"], dest_lat, dest_lon)
    return {
        "arrived": dist <= arrive_radius_m,
        "distance_m": round_distance(dist),
        "relative": relative(float(rider.get("heading", 0.0)), bearing),
        "compass": compass(bearing),
    }
