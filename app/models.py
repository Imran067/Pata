"""Shapes of Evon's JSON replies. Every reply is validated before the app acts on it."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .languages import normalize as _normalize_language

KINDS = [
    "temple", "mosque", "church", "pharmacy", "hospital", "school", "college",
    "bus_stop", "petrol_pump", "bank", "atm", "shop", "restaurant", "hotel", "park",
    "market", "building", "hostel", "gate", "sports", "junction", "water_tank", "other",
]
RELATIONS = [
    "opposite", "next_to", "behind", "in_front_of", "near", "inside", "above",
    "after", "before", "corner", "unknown",
]
_KIND_ALIASES = {
    "kovil": "temple", "koil": "temple", "mandir": "temple", "chemist": "pharmacy",
    "medical": "pharmacy", "medical_shop": "pharmacy", "bus_station": "bus_stop",
    "busstop": "bus_stop", "fuel": "petrol_pump", "petrol_bunk": "petrol_pump",
    "gas_station": "petrol_pump", "apartment": "building", "flat": "building",
    "dormitory": "hostel", "hall_of_residence": "hostel", "swimming_pool": "sports", "pool": "sports",
    "stadium": "sports", "ground": "sports", "playground": "sports", "entrance": "gate",
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Landmark(_Model):
    heard: str = ""
    kind: str = "other"
    relation: str = "unknown"
    name_hint_en: Optional[str] = None

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> str:
        text = str(value or "other").strip().lower().replace(" ", "_").replace("-", "_")
        text = _KIND_ALIASES.get(text, text)
        return text if text in KINDS else "other"

    @field_validator("relation", mode="before")
    @classmethod
    def _relation(cls, value: Any) -> str:
        text = str(value or "unknown").strip().lower().replace(" ", "_").replace("-", "_")
        return text if text in RELATIONS else "unknown"

    @field_validator("heard", mode="before")
    @classmethod
    def _heard(cls, value: Any) -> str:
        return str(value or "").strip()


class BuildingFacts(_Model):
    colour: Optional[str] = None
    entrance: Optional[str] = None
    floor: Optional[str] = None
    name: Optional[str] = None
    other: Optional[str] = None

    @field_validator("colour", "entrance", "floor", "name", "other", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def merged_with(self, newer: "BuildingFacts") -> "BuildingFacts":
        """Newer non-empty facts win, older ones are kept otherwise."""
        data = self.model_dump()
        for key, value in newer.model_dump().items():
            if value:
                data[key] = value
        return BuildingFacts(**data)


def _list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class RelayOut(_Model):
    message_for_listener: str
    gloss_en: str = ""
    landmarks: list[Landmark] = Field(default_factory=list)
    building: BuildingFacts = Field(default_factory=BuildingFacts)
    answer_option_id: Optional[str] = None
    speaker_language: Optional[str] = None

    _lists = field_validator("landmarks", mode="before")(classmethod(lambda cls, v: _list(v)))

    @field_validator("speaker_language", mode="before")
    @classmethod
    def _speaker_language(cls, value: Any) -> Optional[str]:
        return _normalize_language(value)

    @field_validator("building", mode="before")
    @classmethod
    def _building(cls, value: Any) -> Any:
        return value or {}

    @field_validator("answer_option_id", mode="before")
    @classmethod
    def _option(cls, value: Any) -> Optional[str]:
        if value in (None, "", "null", "none"):
            return None
        return str(value).strip()


class MatchOption(_Model):
    id: str
    label: str = ""
    feature_kind: Optional[str] = None


class MatchOut(_Model):
    decision: str
    site_id: Optional[str] = None
    pin_is_wrong: bool = False
    confidence: float = 0.5
    reason: str = ""
    question_for_customer: Optional[str] = None
    question_gloss_en: Optional[str] = None
    options: list[MatchOption] = Field(default_factory=list)

    _lists = field_validator("options", mode="before")(classmethod(lambda cls, v: _list(v)))

    @field_validator("decision", mode="before")
    @classmethod
    def _decision(cls, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"resolved", "match", "matched", "found"}:
            return "resolved"
        if text in {"ask", "clarify", "question", "ambiguous"}:
            return "ask"
        return "not_found"

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.5


class SayOut(_Model):
    say: str
    gloss_en: str = ""


class NoteOut(_Model):
    building_description: str = ""
    landmarks: list[str] = Field(default_factory=list)
    entrance: Optional[str] = None
    floor: Optional[str] = None
    cautions: list[str] = Field(default_factory=list)
    summary_en: str = ""
    pin_fix_question_for_customer: Optional[str] = None
    pin_fix_gloss_en: Optional[str] = None

    _lists = field_validator("landmarks", "cautions", mode="before")(
        classmethod(lambda cls, v: [str(x) for x in _list(v) if str(x).strip()])
    )

    @field_validator("entrance", "floor", mode="before")
    @classmethod
    def _text(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
