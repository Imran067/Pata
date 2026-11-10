#!/usr/bin/env python3
"""Load real places around a location from OpenStreetMap, in Pata's format.

The control room does the same with its "Load real places around the pin" button. Use this
script if you'd rather prepare a places file in advance:

  python scripts/fetch_osm_places.py --lat 13.0418 --lon 80.2341 --radius 1500 \
      --lang ta-IN --area "T. Nagar, Chennai" --out data/places_mine.json

Then set PLACES_FILE=data/places_mine.json in .env.
Map data (c) OpenStreetMap contributors, ODbL. Run it once per area, not in a loop.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.osm import OVERPASS_URL, overpass_query, places_from_elements  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius", type=int, default=1500, help="metres around the point (default 1500)")
    parser.add_argument("--lang", default="ta-IN", help="local language of the area, e.g. ta-IN, kn-IN, mr-IN")
    parser.add_argument("--area", default="Demo area", help="name shown in the app")
    parser.add_argument("--out", default="data/places_mine.json")
    args = parser.parse_args()

    body = urllib.parse.urlencode({"data": overpass_query(args.lat, args.lon, args.radius)}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers={"User-Agent": "pata-hackathon-demo/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            elements = json.load(response)["elements"]
    except Exception as exc:  # network errors, Overpass busy
        print(f"Overpass request failed: {exc}. Wait a minute and try again.", file=sys.stderr)
        return 1

    places = places_from_elements(elements, args.lang)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"area_name": args.area, "source": "OpenStreetMap contributors (ODbL)", "places": places},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    counts = Counter(p["kind"] for p in places)
    print(f"Wrote {len(places)} places to {out}: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()))
    if len(places) < 30:
        print("That's thin. Add the landmarks your demo customer will name by hand.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
