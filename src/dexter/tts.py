"""Tekst ostaje glavni odgovor; dodatni glas ne sme da prekine njegovu isporuku."""

import re
from collections.abc import AsyncIterator

import httpx

from dexter.config import settings
from dexter.pismo import u_latinicu

INSTRUCTIONS = (
    "Govori jasno i prirodno na srpskom. Pročitaj dostavljeni tekst, bez dodatnih rečenica."
)


def requested(content, *, voice_input=False) -> bool:
    text = (
        content
        if isinstance(content, str)
        else " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    )
    text = u_latinicu(text).casefold()
    if re.search(r"\b(?:ne (?:odgovori|odgovaraj)(?: mi)? glasom|bez glasa|samo tekst)\b", text):
        return False
    return bool(re.search(r"\b(?:odgovori|odgovaraj)(?: mi)? glasom\b", text)) or (
        voice_input and settings().glas_odgovor == "on"
    )


def parts(text: str, byte_limit: int = 1500) -> list[str]:
    text = u_latinicu(text).strip()
    out = []
    while text:
        size = end = boundary = 0
        for i, char in enumerate(text):
            size += len(char.encode("utf-8"))
            if size > byte_limit:
                break
            end = i + 1
            if char.isspace() and size > byte_limit // 2:
                boundary = end
        if end == len(text):
            cut = end
        else:
            cut = boundary or end
        if not cut:
            raise ValueError("Granica govornog dela je premala.")
        out.append(text[:cut].strip())
        text = text[cut:].lstrip()
    return [p for p in out if p]


async def synthesize(text: str) -> AsyncIterator[bytes]:
    cfg = settings()
    if not cfg.openai_api_key:
        raise ValueError("Glasovni odgovor traži OPENAI_API_KEY.")
    # Granica UTF-8 bajtova ostavlja prostor i za uputstvo unutar 2000 ulaznih tokena.
    async with httpx.AsyncClient(timeout=120) as client:
        for part in parts(text):
            body = {
                "model": cfg.tts_model,
                "voice": cfg.tts_voice,
                "input": part,
                "response_format": "opus",
            }
            if cfg.tts_model.startswith("gpt-4o-mini-tts"):
                body["instructions"] = INSTRUCTIONS
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
                json=body,
            )
            response.raise_for_status()
            if not response.content.startswith(b"OggS"):
                raise ValueError("TTS nije vratio OGG/Opus audio za Telegram.")
            yield response.content
