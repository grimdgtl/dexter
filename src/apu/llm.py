"""Zajednički Anthropic klijent + jednostavan poziv bez alata.

Svaki poziv modela prolazi kroz `create`, pa se tokeni, cena i latencija
beleže na jednom mestu, bez obzira ko zove (chat, memorija, scheduler).
"""

import time

from anthropic import AsyncAnthropic

from apu import usage
from apu.config import settings

_client: AsyncAnthropic | None = None


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings().anthropic_api_key, max_retries=3)
    return _client


async def create(*, purpose: str, **kwargs):
    """messages.create sa merenjem. `purpose` ide u tabelu usage (chat, memory...)."""
    start = time.perf_counter()
    response = await client().messages.create(**kwargs)
    latency = int((time.perf_counter() - start) * 1000)
    await usage.record(usage.from_response(kwargs["model"], response.usage), purpose, latency)
    return response


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


async def complete(prompt: str, *, system: str = "", model: str | None = None,
                   purpose: str = "misc", max_tokens: int = 1024) -> str:  # fmt: skip
    """Jednokratan poziv bez alata. Podrazumevano brzi (jeftini) model."""
    kwargs = dict(
        model=model or settings().model_fast,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    return text_of(await create(purpose=purpose, **kwargs))
