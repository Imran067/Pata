"""The ten languages Prisma v3.0 and Timbre v3.0 share, and a script check for Evon's output.

Evon's model card recommends naming the target language and script in the prompt and
verifying the script of the reply downstream. `script_ok` is that downstream check.
"""
from __future__ import annotations

LANGUAGES: dict[str, tuple[str, str]] = {
    "hi-IN": ("Hindi", "Devanagari"),
    "mr-IN": ("Marathi", "Devanagari"),
    "bn-IN": ("Bengali", "Bengali"),
    "pa-IN": ("Punjabi", "Gurmukhi"),
    "gu-IN": ("Gujarati", "Gujarati"),
    "ta-IN": ("Tamil", "Tamil"),
    "te-IN": ("Telugu", "Telugu"),
    "kn-IN": ("Kannada", "Kannada"),
    "ml-IN": ("Malayalam", "Malayalam"),
    "en-IN": ("English", "Latin"),
}

_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "Devanagari": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF),
    "Gurmukhi": (0x0A00, 0x0A7F),
    "Gujarati": (0x0A80, 0x0AFF),
    "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F),
    "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
}
_INDIC = (0x0900, 0x0DFF)


_ALIASES: dict[str, str] = {}
for _code, (_name, _script) in LANGUAGES.items():
    _ALIASES[_code.lower()] = _code
    _ALIASES[_code.split("-")[0]] = _code
    _ALIASES[_name.lower()] = _code
_ALIASES["bangla"] = "bn-IN"


def normalize(value: object) -> str | None:
    """'ta', 'Tamil', 'ta-in' -> 'ta-IN'. Anything else -> None."""
    if not value:
        return None
    return _ALIASES.get(str(value).strip().lower().replace("_", "-"))


def is_supported(code: str | None) -> bool:
    return bool(code) and code in LANGUAGES


def name(code: str) -> str:
    return LANGUAGES.get(code, (code, ""))[0]


def script(code: str) -> str:
    return LANGUAGES.get(code, ("", "Latin"))[1]


def describe(code: str) -> dict[str, str]:
    return {"code": code, "name": name(code), "script": script(code)}


def script_ok(text: str, code: str, min_share: float = 0.35) -> bool:
    """True when `text` is mostly written in the script of language `code`.

    Latin letters are tolerated (shop and brand names stay in English), but text in a
    different Indian script, or text with no target-script letters at all, fails.
    """
    if not text or not text.strip():
        return False
    target = script(code)
    if target == "Latin":
        indic = sum(_INDIC[0] <= ord(ch) <= _INDIC[1] for ch in text)
        latin = sum(ch.isascii() and ch.isalpha() for ch in text)
        return latin > 0 and indic <= latin * 0.2
    lo, hi = _SCRIPT_RANGES[target]
    in_script = sum(lo <= ord(ch) <= hi for ch in text)
    other_indic = sum(
        _INDIC[0] <= ord(ch) <= _INDIC[1] and not lo <= ord(ch) <= hi for ch in text
    )
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    if in_script == 0 or other_indic > in_script * 0.2:
        return False
    return in_script / (in_script + latin) >= min_share
