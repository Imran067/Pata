"""Working out which language each person speaks, from their own speech.

Nobody has to pick a language. Each person starts with a guess (their profile, or what the
control room picked) only so Pata can greet them, and then their own words decide:

  * Prisma detects the language of every spoken turn (indic-auto).
  * Evon names the language of the same words while it relays them, as a second opinion.
  * The transcript must actually be written in that language's script.
  * Replies shorter than three words ("haan", "ok", "sari") never change anything.
  * Once a language is confirmed, switching needs two turns in a row in the new language,
    so one English sentence from a Hindi speaker doesn't flip the call to English.

Code-mixed speech (Hinglish, Tanglish, Benglish) counts as its Indian language.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import languages

MIN_WORDS = 3
MIN_SCRIPT_SHARE = 0.15  # low on purpose: code-mixed transcripts keep English words in English letters


@dataclass
class LangState:
    code: str
    source: str  # "profile", "picked" or "detected"
    auto: bool = True  # False: set in the control room, never switched by detection
    confirmed: bool = False
    candidate: str | None = None  # a different language heard once, waiting for a second turn
    disclosed_in: str | None = None  # language the AI disclosure was last spoken in

    def public(self) -> dict:
        return {"code": self.code, "name": languages.name(self.code), "source": self.source,
                "confirmed": self.confirmed, "candidate": self.candidate, "auto": self.auto}


@dataclass
class Verdict:
    switched: bool
    previous: str
    note: str  # plain English, shown in the control room


def update(state: LangState, *, prisma_lang: str | None, evon_lang: str | None, transcript: str, typed: bool) -> Verdict:
    """Fold one turn's evidence into a person's language state."""
    previous = state.code
    if not state.auto:
        return Verdict(False, previous, f"{languages.name(previous)} is set in the control room, so Pata doesn't switch.")
    heard = evon_lang if typed else prisma_lang
    if not languages.is_supported(heard):
        return Verdict(False, previous, "No usable language was detected in this turn.")
    name = languages.name(heard)
    if not typed and languages.is_supported(evon_lang) and evon_lang != prisma_lang:
        return Verdict(False, previous, f"Prisma heard {name} but Evon read {languages.name(evon_lang)}, "
                                        f"so Pata keeps {languages.name(previous)}.")
    if not languages.script_ok(transcript, heard, min_share=MIN_SCRIPT_SHARE):
        return Verdict(False, previous, f"The transcript isn't written in {languages.script(heard)} script, "
                                        f"so the {name} detection was ignored.")
    if len(transcript.split()) < MIN_WORDS:
        return Verdict(False, previous, "Too short to judge the language.")
    if heard == state.code:
        state.confirmed, state.source, state.candidate = True, "detected", None
        return Verdict(False, previous, f"Confirmed {name}.")
    how = "Evon read" if typed else "Prisma and Evon both heard"
    if not state.confirmed:
        state.code, state.source, state.confirmed, state.candidate = heard, "detected", True, None
        return Verdict(True, previous, f"{how} {name}, not {languages.name(previous)}.")
    if state.candidate == heard:
        state.code, state.source, state.candidate = heard, "detected", None
        return Verdict(True, previous, f"{how} {name} two turns in a row, so Pata switched from {languages.name(previous)}.")
    state.candidate = heard
    return Verdict(False, previous, f"Heard {name} once. One more turn in {name} will switch from {languages.name(previous)}.")
