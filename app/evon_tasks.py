"""Evon's five jobs, each with its prompt, reasoning setting and token budget, plus a plain
translation fallback.

Every prompt also gets one line naming the exact language and script for this request, with a
sample sentence in that script. A 4-bit model on a small GPU follows that much more reliably than
a language code inside the JSON it is given.
"""
from __future__ import annotations

from . import languages, prompts
from .models import MatchOut, NoteOut, RelayOut, SayOut
from .phrases import disclosure
from .services.evon import EvonClient, strip_reasoning

TRANSLATE = ("You translate short messages in a phone call between a delivery rider and a customer in India. "
             "Translate the user's message into {name}, written in {script} script. Keep the names of shops, "
             "temples, roads and brands as they are. Reply with only the translation: no quotes, no notes.")


GENDER_RULE = (" Don't assume the gender of the rider or the customer: where verbs or pronouns change with "
               "gender, use the respectful form that doesn't mark it (in Hindi, for example, aap with plural verbs).")


def language_rule(field: str, code: str) -> str:
    if code == "en-IN":
        return f"\n\nFor this request, write {field} in English." + GENDER_RULE
    name, script = languages.name(code), languages.script(code)
    return (f"\n\nFor this request, write {field} in {name}, in {script} script: not in English and not in any "
            f"other Indian language. For reference, this is {name} in {script} script: {disclosure(code)}" + GENDER_RULE)


class LiveEvonTasks:
    def __init__(self, client: EvonClient, reasoning: bool = True, reasoning_tokens: int = 3000):
        self.client = client
        # On a slow GPU, cap the reasoning budget or switch it off (EVON_REASONING_TOKENS, EVON_REASONING).
        self.reasoning = reasoning
        self.reasoning_tokens = reasoning_tokens if reasoning else 1500

    @staticmethod
    def _system(base: str, field: str, code: str, payload: dict) -> tuple[str, dict]:
        system = base + language_rule(field, code)
        if payload.get("correction"):
            system += "\n\nImportant: " + payload["correction"]
        return system, {k: v for k, v in payload.items() if k != "correction"}

    async def relay(self, payload: dict) -> RelayOut:
        system, body = self._system(prompts.RELAY, "message_for_listener", payload["listener_language"], payload)
        return await self.client.ask_json(system, body, RelayOut, thinking=False, max_tokens=900)

    async def match(self, payload: dict) -> MatchOut:
        system, body = self._system(prompts.MATCH, "question_for_customer", payload["customer_language"], payload)
        return await self.client.ask_json(system, body, MatchOut, thinking=self.reasoning,
                                          max_tokens=self.reasoning_tokens)

    async def directions(self, payload: dict) -> SayOut:
        system, body = self._system(prompts.DIRECTIONS, "say", payload["rider_language"], payload)
        return await self.client.ask_json(system, body, SayOut, thinking=False, max_tokens=400)

    async def note(self, payload: dict) -> NoteOut:
        # A summary, not a search: no reasoning, so marking delivered never hangs.
        system = prompts.NOTE + ("\n\nImportant: " + payload["correction"] if payload.get("correction") else "")
        body = {k: v for k, v in payload.items() if k != "correction"}
        return await self.client.ask_json(system, body, NoteOut, thinking=False, max_tokens=800)

    async def briefing(self, payload: dict) -> SayOut:
        system, body = self._system(prompts.BRIEFING, "say", payload["rider_language"], payload)
        return await self.client.ask_json(system, body, SayOut, thinking=False, max_tokens=500)

    async def translate(self, text: str, code: str) -> str:
        """Plain-text translation, used when a JSON reply came back in the wrong language twice."""
        name, script = languages.name(code), languages.script(code)
        system = TRANSLATE.format(name=name, script=script)
        if code != "en-IN":
            system += f" For reference, this is {name} in {script} script: {disclosure(code)}"
        content = await self.client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": text}],
            thinking=False, max_tokens=400)
        return strip_reasoning(content).strip().strip('"“”').strip()
