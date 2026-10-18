"""Glas → tekst. Whisper preko API-ja ili lokalno (faster-whisper na Hetzneru).

Rezultat uvek prolazi kroz u_latinicu — Whisper srpski piše ćirilicom.
"""

import asyncio
import io
import logging
import threading
from functools import lru_cache

import httpx

from dexter.config import settings
from dexter.pismo import u_latinicu

log = logging.getLogger(__name__)

# Primer latinice u promptu gura Whisper ka latinici (ali ne garantuje — zato u_latinicu).
HINT = "Zdravo, zakaži mi sastanak sa Markom u utorak i proveri mejlove."
_local_lock = threading.Lock()


async def _openai(audio: bytes, filename: str) -> str:
    key = settings().openai_api_key
    if not key:
        raise RuntimeError("TRANSCRIBE_PROVIDER=openai traži OPENAI_API_KEY.")
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (filename, audio)},
            data={"model": "whisper-1", "language": "sr", "prompt": HINT},
        )
        r.raise_for_status()
        return r.json()["text"]


@lru_cache(maxsize=1)
def _local_model(name: str):
    from faster_whisper import WhisperModel

    log.info("Učitavam lokalni Whisper (%s)…", name)
    return WhisperModel(name, device="cpu", compute_type="int8")


def _local_sync(audio: bytes) -> str:
    with _local_lock:
        segments, _ = _local_model(settings().whisper_local_model).transcribe(
            io.BytesIO(audio), language="sr", initial_prompt=HINT
        )
        return " ".join(s.text.strip() for s in segments)


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    if settings().transcribe_provider == "local":
        text = await asyncio.to_thread(_local_sync, audio)
    else:
        text = await _openai(audio, filename)
    return u_latinicu(text.strip())
