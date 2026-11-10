"""Gnani Evon (gnani-evon-v3.3-30B-A3B) behind an OpenAI-compatible endpoint.

Evon is not hosted by Gnani's speech API or by Hugging Face inference providers, so you
serve it yourself (see scripts/serve_evon.sh) and point EVON_BASE_URL at it.

Every task asks Evon for one JSON object. Reasoning ("thinking") is switched per call:
off for quick turn-by-turn rewriting, on for map matching and doorstep notes, using the
`chat_template_kwargs.enable_thinking` flag from Evon's model card.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings

log = logging.getLogger("pata.evon")
T = TypeVar("T", bound=BaseModel)
_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


class EvonError(RuntimeError):
    """Raised when Evon cannot be reached or keeps replying with unusable output."""


def strip_reasoning(text: str) -> str:
    text = _THINK.sub("", text or "")
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


_KEY_AHEAD = re.compile(r'"[A-Za-z_][A-Za-z0-9_]*"\s*:')
_VALUE_END = set('"}]0123456789el')  # last character of a string, object, array, number, true/false/null
_PY_LITERALS = {"None": "null", "True": "true", "False": "false"}


def repair_json(text: str) -> str:
    """Fix the slips a language model makes when the server isn't enforcing JSON mode.

    Handles: a missing comma between fields or list items, trailing commas, raw line breaks
    and tabs inside text, stray double quotes inside a sentence, Python's None/True/False,
    and a reply cut off part-way (open text and brackets are closed). Valid JSON passes
    through unchanged.
    """
    out: list[str] = []
    stack: list[str] = []
    in_str = escaped = False
    last = ""  # last significant character outside text
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                # A closing quote is followed by , : } ] or a line break, or by the next key
                # when a comma is missing. Anything else is a quote inside the sentence.
                j = i + 1
                while j < n and text[j] in " \t\r":
                    j += 1
                ahead = text[j] if j < n else ""
                if ahead in ("", ",", ":", "}", "]", "\n") or (ahead == '"' and _KEY_AHEAD.match(text, j)):
                    out.append(ch)
                    in_str = False
                    last = '"'
                else:
                    out.append('\\"')
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\t":
                out.append("\\t")
            elif ch != "\r":
                out.append(ch)
            i += 1
            continue

        if ch in "\"{[" and last in _VALUE_END:
            out.append(",")  # a value just ended and another begins: the comma is missing
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
            out.append(ch)
            last = ch
        elif ch in "}]":
            while out and out[-1] in " \t\r\n":
                out.pop()
            if out and out[-1] == ",":
                out.pop()  # trailing comma
            if stack:
                stack.pop()
            out.append(ch)
            last = ch
        elif ch.isspace():
            out.append(ch)
        else:
            word = next((w for w in _PY_LITERALS if text.startswith(w, i)), None)
            if word:
                out.append(_PY_LITERALS[word])
                last = _PY_LITERALS[word][-1]
                i += len(word)
                continue
            out.append(ch)
            last = ch
        i += 1

    # The reply was cut off: close what is still open.
    if in_str:
        if escaped:
            out.pop()
        out.append('"')
        last = '"'
    while out and out[-1] in " \t\r\n,":
        out.pop()
    if out and out[-1] == ":":
        out.append(" null")
    out.extend(reversed(stack))
    return "".join(out)


def extract_json(text: str) -> dict:
    text = strip_reasoning(text)
    fenced = _FENCE.search(text)
    if fenced:
        candidate = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1:
            raise ValueError("the reply contains no JSON object")
        candidate = text[start : end + 1] if end > start else text[start:]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        try:
            value = json.loads(repair_json(candidate))
        except json.JSONDecodeError:
            raise error from None
        log.warning("Evon's reply was not valid JSON (%s); repaired it. Is JSON mode on in the server? Reply: %r",
                    error, candidate[:500])
    if not isinstance(value, dict):
        raise ValueError("the reply's JSON is not an object")
    return value


def salvage(text: str, schema: type[BaseModel]) -> dict:
    """Last resort: pull the schema's plain text fields out of a reply too broken to parse."""
    text = strip_reasoning(text)
    found: dict = {}
    for name, field in schema.model_fields.items():
        if field.annotation not in (str, "str"):
            continue
        match = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.S)
        if match:
            try:
                found[name] = json.loads(f'"{match.group(1)}"')
            except json.JSONDecodeError:
                found[name] = match.group(1)
    return found


class EvonClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings = settings
        self.http = http

    async def chat(self, messages: list[dict], *, thinking: bool, max_tokens: int, json_mode: bool = False) -> str:
        s = self.settings
        body: dict = {
            "model": s.evon_model,
            "messages": messages,
            # Quick relays and translations should be faithful, not creative.
            "temperature": 0.6 if thinking else 0.3,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        if json_mode and s.evon_json_mode and not thinking:
            # llama.cpp and vLLM then constrain decoding so the reply is always valid JSON.
            # (Not with reasoning on: the grammar would also constrain the thinking.)
            body["response_format"] = {"type": "json_object"}
        try:
            response = await self.http.post(
                f"{s.evon_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {s.evon_api_key}"},
                json=body,
                timeout=s.evon_timeout_s,
            )
        except httpx.HTTPError as exc:
            raise EvonError(f"Could not reach Evon at {s.evon_base_url} ({exc.__class__.__name__}).") from exc
        if response.status_code >= 400:
            raise EvonError(f"Evon returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            message = response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise EvonError("Evon's reply was not in the OpenAI chat format.") from exc
        return message.get("content") or ""

    async def ask_json(self, system: str, payload: dict, schema: type[T], *, thinking: bool, max_tokens: int) -> T:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
        ]
        content = await self.chat(messages, thinking=thinking, max_tokens=max_tokens, json_mode=True)
        if not strip_reasoning(content):
            # Usually means the token budget ran out while thinking. Answer directly instead.
            content = await self.chat(messages, thinking=False, max_tokens=max_tokens, json_mode=True)
        try:
            return schema.model_validate(extract_json(content))
        except (ValueError, ValidationError) as first_error:
            repair = messages + [
                {"role": "assistant", "content": strip_reasoning(content)[-4000:] or "(empty)"},
                {
                    "role": "user",
                    "content": (
                        f"That reply could not be used ({str(first_error)[:200]}). "
                        "Reply again with only the JSON object described in the instructions."
                    ),
                },
            ]
            second = await self.chat(repair, thinking=False, max_tokens=max_tokens, json_mode=True)
            try:
                return schema.model_validate(extract_json(second))
            except (ValueError, ValidationError) as exc:
                # Keep whatever text fields can be read, so the call can go on.
                # Only for replies built around required text (the message to relay, the line to say);
                # a schema with nothing required would "succeed" with an empty object.
                required = [name for name, field in schema.model_fields.items() if field.is_required()]
                for reply in (second, content):
                    fields = salvage(reply, schema)
                    if not required or not all(fields.get(name) for name in required):
                        continue
                    try:
                        result = schema.model_validate(fields)
                    except ValidationError:
                        continue
                    log.warning("Evon's reply for %s could not be parsed; salvaged %s. Reply: %r",
                                schema.__name__, sorted(fields), strip_reasoning(reply)[:500])
                    return result
                log.error("Evon did not return valid JSON for %s: %s. Replies: %r / %r", schema.__name__, exc,
                          strip_reasoning(content)[:500], strip_reasoning(second)[:500])
                raise EvonError(f"Evon did not return valid JSON for {schema.__name__}: {exc}") from exc
