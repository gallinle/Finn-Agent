"""Gemeinsamer Claude-Aufruf: messages.parse mit Pydantic-Schema und stop_reason-Prüfung."""

from __future__ import annotations

import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel

log = logging.getLogger("finn.llm")
T = TypeVar("T", bound=BaseModel)


class LLMFehler(Exception):
    """Claude hat kein verwertbares Ergebnis geliefert."""


def parse(
    client: anthropic.Anthropic,
    modell: str,
    schema: type[T],
    system: str,
    content: list[dict],
    max_tokens: int = 16000,
    zweck: str = "",
) -> T:
    resp = client.messages.parse(
        model=modell,
        max_tokens=max_tokens,
        output_config={"effort": "high"},
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    u = resp.usage
    log.info(
        "%s: stop=%s in=%s out=%s cache_read=%s cache_write=%s req=%s",
        zweck, resp.stop_reason, u.input_tokens, u.output_tokens,
        u.cache_read_input_tokens, u.cache_creation_input_tokens, resp._request_id,
    )
    if resp.stop_reason == "refusal":
        cat = resp.stop_details.category if resp.stop_details else None
        raise LLMFehler(f"{zweck}: Claude hat die Anfrage abgelehnt (Kategorie: {cat}).")
    if resp.stop_reason == "max_tokens":
        raise LLMFehler(f"{zweck}: Antwort wurde bei max_tokens={max_tokens} abgeschnitten.")
    if resp.stop_reason != "end_turn":
        raise LLMFehler(f"{zweck}: unerwarteter stop_reason '{resp.stop_reason}'.")
    if resp.parsed_output is None:
        raise LLMFehler(f"{zweck}: Antwort entspricht nicht dem Schema.")
    return resp.parsed_output
