"""The demo setup chosen in the control room: who the customer is, where their saved pin is, which
language each person speaks (set, or detected automatically), and which map data to use.

Saved in data/demo_setup.json, so it survives restarts and updates of the code.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from . import languages

PLACES_SOURCES = ("sample", "osm")


class SetupStore:
    def __init__(self, path: Path, orders: dict):
        self.path = Path(path)
        self._lock = threading.Lock()
        order, rider = orders["orders"][0], orders["riders"][0]
        self.rider_ids = {r["id"] for r in orders["riders"]}
        self.defaults = {
            "customer_name": order["customer_name"],
            "address_text": order["address_text"],
            "items": order["items"],
            "pin": dict(order["pin"]),
            "customer_lang": order.get("customer_lang_hint") or "hi-IN",
            "customer_auto": False,
            "rider_id": rider["id"],
            "rider_lang": rider["lang"],
            "rider_auto": False,
            "places_source": "sample",
            "prisma_hints": True,
        }

    def get(self) -> dict:
        with self._lock:
            saved = {}
            if self.path.exists():
                try:
                    saved = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                except json.JSONDecodeError:
                    saved = {}
            return {**self.defaults, **{k: v for k, v in saved.items() if k in self.defaults}}

    def update(self, changes: dict) -> dict:
        clean = self._clean(changes)
        merged = {**self.get(), **clean}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        return merged

    def _clean(self, changes: dict) -> dict:
        out: dict = {}
        for key in ("customer_name", "address_text", "items"):
            if key in changes:
                value = " ".join(str(changes[key]).split())[:120]
                if key == "customer_name" and not value:
                    raise ValueError("The customer needs a name.")
                out[key] = value
        if "pin" in changes:
            lat, lon = float(changes["pin"]["lat"]), float(changes["pin"]["lon"])
            if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
                raise ValueError("That pin is outside India. Move it back onto an Indian street.")
            out["pin"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
        for key in ("customer_lang", "rider_lang"):
            if key in changes:
                if not languages.is_supported(changes[key]):
                    raise ValueError(f"Unsupported language {changes[key]!r}. Use one of: {', '.join(languages.LANGUAGES)}.")
                out[key] = changes[key]
        for key in ("customer_auto", "rider_auto", "prisma_hints"):
            if key in changes:
                out[key] = bool(changes[key])
        if "rider_id" in changes:
            if changes["rider_id"] not in self.rider_ids:
                raise ValueError("Unknown rider.")
            out["rider_id"] = changes["rider_id"]
        if "places_source" in changes:
            if changes["places_source"] not in PLACES_SOURCES:
                raise ValueError("Places must be 'sample' or 'osm'.")
            out["places_source"] = changes["places_source"]
        return out
