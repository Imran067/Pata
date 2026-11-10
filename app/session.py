"""Call session state, and the WebSocket hub that keeps both phones and the control room in sync."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import WebSocket

from . import languages
from .geo import Site
from .models import BuildingFacts, Landmark


@dataclass
class Session:
    id: str
    order: dict
    rider: dict
    langs: dict  # role -> LangState: each person's language, from their own speech
    modes: dict
    rider_pos: dict
    prisma_hints: bool = True
    log: list[dict] = field(default_factory=list)
    landmarks: list[Landmark] = field(default_factory=list)
    building: BuildingFacts = field(default_factory=BuildingFacts)
    searched_signature: str = ""
    sites: list[Site] = field(default_factory=list)
    pending_question: dict | None = None
    resolved_site_id: str | None = None
    destination: dict | None = None
    pin_is_wrong: bool = False
    directions: dict | None = None
    arrived: bool = False
    delivered: bool = False
    note: dict | None = None
    pin_fix_pending: bool = False
    more_asked: int = 0
    told_note_known: bool = False
    joined: set[str] = field(default_factory=set)
    status: dict = field(default_factory=lambda: {"text": "", "busy": False})
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    match_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def rider_lang(self) -> str:
        return self.langs["rider"].code

    @property
    def customer_lang(self) -> str:
        return self.langs["customer"].code

    def lang_of(self, role: str) -> str:
        return self.langs[role].code

    def site(self, site_id: str | None) -> Site | None:
        return next((s for s in self.sites if s.id == site_id), None)

    def public(self) -> dict:
        """Everything the screens need to draw themselves, as plain JSON."""
        resolved = self.site(self.resolved_site_id)
        return {
            "id": self.id,
            "modes": self.modes,
            "order": self.order,
            "rider": {**self.rider, "lang": self.rider_lang, "lang_name": languages.name(self.rider_lang)},
            "customer_lang": self.customer_lang,
            "customer_lang_name": languages.name(self.customer_lang),
            "customer_lang_confirmed": self.langs["customer"].confirmed,
            "languages": {role: state.public() for role, state in self.langs.items()},
            "rider_pos": self.rider_pos,
            "log": self.log,
            "landmarks": [lm.model_dump() for lm in self.landmarks],
            "building": self.building.model_dump(),
            "sites": [s.to_dict() for s in self.sites],
            "pending_question": self.pending_question,
            "resolved_site": resolved.to_dict() if resolved else None,
            "destination": self.destination,
            "pin_is_wrong": self.pin_is_wrong,
            "directions": self.directions,
            "arrived": self.arrived,
            "delivered": self.delivered,
            "note": self.note,
            "pin_fix_pending": self.pin_fix_pending,
            "joined": sorted(self.joined),
            "status": self.status,
        }


class Hub:
    """Pushes events to every screen watching a session."""

    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, socket: WebSocket) -> None:
        await socket.accept()
        self.sockets[session_id].add(socket)

    def disconnect(self, session_id: str, socket: WebSocket) -> None:
        self.sockets[session_id].discard(socket)

    async def broadcast(self, session_id: str, event: dict) -> None:
        for socket in list(self.sockets.get(session_id, ())):
            try:
                await socket.send_json(event)
            except Exception:  # a closed tab; forget it
                self.sockets[session_id].discard(socket)
