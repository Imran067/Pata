"""Keep the precise facts in a doorstep note true: room numbers and floors.

A small model sometimes invents these, or copies them from an example. A rider sent to the wrong
room is worse than a rider told no room at all, so the code checks them:

- A room, flat or house number must appear in the address the customer typed or in what was said
  in the call. If not, it is replaced with the address's own number, or removed if the address has
  none.
- A floor must have been said in the call or written in the address, or it is dropped.
- A specific caution (a closed gate, a dog, timings) must have been mentioned in the call.

When an old note is read out (no call text available), only replacement against the address happens.
"""
from __future__ import annotations

import re

_UNIT = re.compile(
    r"\b(room|rm|flat|apartment|apt|house|h\.?\s?no|door|unit|quarters?|qtr)\.?\s*"
    r"(?:no\.?|number)?\s*[:#-]?\s*([a-z]?\d+[a-z]?(?:[-/]\d+)?)\b",
    re.IGNORECASE,
)
_FLOOR_WORDS = {
    "ground": "ground", "basement": "basement", "first": "1", "second": "2", "third": "3", "fourth": "4",
    "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "top": "top",
}
# Words that make a caution specific. If a caution uses them, the call must have used them too.
_CAUTION_WORDS = {
    "closed", "close", "closes", "locked", "lock", "dog", "dogs", "guard", "security", "staff", "warden",
    "timing", "timings", "night", "bell", "intercom", "stairs", "lift", "elevator", "broken", "construction",
    "mud", "puddle", "water", "parking", "permission", "register", "id",
}
_TEXT_FIELDS = ("building_description", "entrance", "floor", "summary_en")
_LIST_FIELDS = ("landmarks", "cautions")


def address_unit(address: str) -> str | None:
    """The room, flat or house number written in the address, as written ("Room 214")."""
    match = _UNIT.search(address or "")
    return match.group(0).strip() if match else None


def _numbers(text: str) -> set[str]:
    return {n.lower() for n in re.findall(r"[a-z]?\d+[a-z]?(?:[-/]\d+)?", text or "", re.IGNORECASE)}


def _floor_key(text: str) -> set[str]:
    """What a floor means, as comparable keys: "ground floor" -> {ground}, "3rd" or "third" -> {3}."""
    keys = set()
    low = (text or "").lower()
    for word, key in _FLOOR_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            keys.add(key)
    keys |= {m for m in re.findall(r"\b(\d+)(?:st|nd|rd|th)?\b", low)}
    return keys


def _tidy(text: str) -> str:
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s{2,}", " ", text)
    return re.sub(r"^[,\s]+|[,\s]+$", "", text).strip()


def guard_note(note: dict, address: str, heard: str | None = None) -> tuple[dict, list[str]]:
    """Return a corrected copy of `note` and a list of what was changed, for the staff log.

    `heard` is everything said in the call (transcripts and their English meanings). Pass None
    when reading an old note out, where only the address can be checked against.
    """
    note = dict(note)
    changes: list[str] = []
    unit = address_unit(address)
    allowed = _numbers(address) | (_numbers(heard) if heard is not None else set())

    def fix_units(text: str) -> str:
        def replace(match: re.Match) -> str:
            number = match.group(2).lower()
            if unit and number not in _numbers(unit) and (heard is None or number not in allowed):
                changes.append(f"{match.group(0).strip()} -> {unit} (from the address)")
                return unit
            if not unit and heard is not None and number not in allowed:
                changes.append(f"removed {match.group(0).strip()} (not in the address or the call)")
                return ""
            return match.group(0)
        return _tidy(_UNIT.sub(replace, text)) if text else text

    for field in _TEXT_FIELDS:
        if isinstance(note.get(field), str):
            note[field] = fix_units(note[field]) or (None if field in ("entrance", "floor") else "")
    for field in _LIST_FIELDS:
        if isinstance(note.get(field), list):
            note[field] = [x for x in (fix_units(str(item)) for item in note[field]) if x]

    # A caution must come from the call: a closed gate, a dog, a timing is something someone said.
    if heard is not None and note.get("cautions"):
        said_words = set(re.findall(r"[a-z]+", heard.lower()))
        kept = []
        for caution in note["cautions"]:
            specifics = set(re.findall(r"[a-z]+", caution.lower())) & _CAUTION_WORDS
            if specifics and not specifics & said_words:
                changes.append(f"removed caution \"{caution}\" (nobody said it)")
            else:
                kept.append(caution)
        note["cautions"] = kept

    # A floor nobody said is a guess.
    if heard is not None and note.get("floor"):
        said = _floor_key(heard) | _floor_key(address)
        claimed = _floor_key(note["floor"])
        if claimed and not claimed & said:
            changes.append(f"removed floor \"{note['floor']}\" (not said in the call or the address)")
            floor_words = re.escape(note["floor"].strip())
            pattern = rf",?\s*(on\s+the\s+)?{floor_words}(\s+floor)?\b"
            note["summary_en"] = _tidy(re.sub(pattern, "", note.get("summary_en") or "", flags=re.IGNORECASE))
            note["floor"] = None

    # The address's own room number belongs in the instruction for the next rider.
    summary = note.get("summary_en") or ""
    if unit and summary and not _UNIT.search(summary):
        note["summary_en"] = f"{summary.rstrip('. ')}, {unit}."
        changes.append(f"added {unit} from the address")
    return note, changes
