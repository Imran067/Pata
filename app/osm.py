"""Real places around a point, from OpenStreetMap's Overpass API, in Pata's format.

Map data (c) OpenStreetMap contributors, ODbL. Overpass is a free shared service: fetch once per
demo location, not in a loop.
"""
from __future__ import annotations

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
AMENITIES = ("place_of_worship|pharmacy|hospital|clinic|school|college|university|bank|atm|fuel|"
             "restaurant|cafe|fast_food|marketplace|bus_station")
# Unnamed places of these kinds are still useful landmarks ("near the bus stop").
GENERIC = {"bus_stop": "Bus stop", "petrol_pump": "Petrol bunk", "atm": "ATM", "water_tank": "Water tank", "temple": "Temple"}
LOCAL_CODES = ("hi", "ta", "bn", "te", "kn", "ml", "mr", "gu", "pa")
_SPORTS_NAMES = {"swimming_pool": "Swimming pool", "stadium": "Stadium", "sports_centre": "Sports centre"}


def overpass_query(lat: float, lon: float, radius: int) -> str:
    around = f"(around:{radius},{lat},{lon})"
    return f"""[out:json][timeout:60];
(
  nwr{around}[amenity~"^({AMENITIES})$"];
  node{around}[highway=bus_stop];
  nwr{around}[shop][name];
  nwr{around}[leisure=park][name];
  nwr{around}[building][name];
  nwr{around}[man_made=water_tower];
  nwr{around}[tourism=hostel];
  nwr{around}[building~"^(dormitory|hostel)$"];
  nwr{around}[leisure~"^(swimming_pool|sports_centre|stadium|pitch|track)$"];
  node{around}[barrier=gate][name];
);
out center tags;"""


def kind_of(tags: dict) -> str | None:
    amenity = tags.get("amenity")
    if amenity == "place_of_worship":
        return {"muslim": "mosque", "christian": "church"}.get(tags.get("religion", ""), "temple")
    by_amenity = {
        "pharmacy": "pharmacy", "hospital": "hospital", "clinic": "hospital", "school": "school",
        "college": "college", "university": "college", "bank": "bank", "atm": "atm", "fuel": "petrol_pump",
        "restaurant": "restaurant", "cafe": "restaurant", "fast_food": "restaurant",
        "marketplace": "market", "bus_station": "bus_stop",
    }
    if amenity in by_amenity:
        return by_amenity[amenity]
    if tags.get("tourism") == "hostel" or tags.get("building") in ("dormitory", "hostel"):
        return "hostel"
    if tags.get("leisure") in ("swimming_pool", "sports_centre", "stadium", "pitch", "track"):
        return "sports"
    if tags.get("barrier") == "gate":
        return "gate"
    if tags.get("highway") == "bus_stop":
        return "bus_stop"
    if tags.get("shop") in ("chemist", "pharmacy"):
        return "pharmacy"
    if tags.get("shop"):
        return "shop"
    if tags.get("leisure") == "park":
        return "park"
    if tags.get("man_made") == "water_tower":
        return "water_tank"
    if tags.get("building"):
        return "building"
    return None


def places_from_elements(elements: list[dict], local_lang: str = "") -> list[dict]:
    short = (local_lang or "").split("-")[0]
    places, seen = [], set()
    for element in elements:
        tags = element.get("tags") or {}
        kind = kind_of(tags)
        center = element.get("center") or {}
        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))
        name = (tags.get("name:en") or tags.get("name") or GENERIC.get(kind or "")
                or (_SPORTS_NAMES.get(tags.get("leisure", "")) if kind == "sports" else None))
        if not kind or lat is None or lon is None or not name:
            continue
        key = (name.casefold(), round(float(lat), 4), round(float(lon), 4))
        if key in seen:
            continue
        seen.add(key)
        local = {}
        for code in LOCAL_CODES:
            value = tags.get(f"name:{code}")
            if value and value != name:
                local[f"{code}-IN"] = value
        if short and tags.get("name") and tags["name"] != name:
            local.setdefault(f"{short}-IN", tags["name"])
        places.append({
            "id": f"osm-{str(element.get('type', 'n'))[0]}{element.get('id')}",
            "name": name, "kind": kind, "lat": round(float(lat), 6), "lon": round(float(lon), 6),
            "local_names": local,
        })
    return places


async def fetch_places(lat: float, lon: float, radius: int, local_lang: str, http: httpx.AsyncClient) -> list[dict]:
    response = await http.post(OVERPASS_URL, data={"data": overpass_query(lat, lon, radius)},
                               headers={"User-Agent": "pata-hackathon-demo/1.0"}, timeout=90)
    response.raise_for_status()
    return places_from_elements(response.json().get("elements", []), local_lang)
