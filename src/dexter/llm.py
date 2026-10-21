"""Zajednički Anthropic klijent + jednostavan poziv bez alata.

Svaki poziv modela prolazi kroz `create`, pa se tokeni, cena i latencija
beleže na jednom mestu, bez obzira ko zove (chat, memorija, scheduler).
"""

import logging
import time

from anthropic import AsyncAnthropic

from dexter import budget, usage
from dexter.config import settings

_client: AsyncAnthropic | None = None
log = logging.getLogger(__name__)
BACKGROUND_TEXT = {"scheduler", "conversation_summary", "history_summary"}


def background_options(purpose: str, kwargs: dict) -> dict:
    # Ovi nezavisni pozivi samo pišu kratak tekst. Podrazumevano razmišljanje
    # modela 5.5 može potrošiti ceo mali limit pre prvog slova odgovora.
    modes = {"claude-haiku-5-5": "disabled", "claude-sonnet-5-5": "between_tools"}
    mode = modes.get(kwargs["model"])
    if (
        purpose not in BACKGROUND_TEXT
        or not mode
        or kwargs.get("tools")
        or "thinking" in kwargs
        or "effort" in kwargs.get("output_config", {})
    ):
        return kwargs
    return {
        **kwargs,
        "thinking": {"type": mode},
        "output_config": {**kwargs.get("output_config", {}), "effort": "low"},
    }


def request_options(kwargs: dict) -> dict:
    if settings().prompt_cache == "on":
        return kwargs

    def without_cache(value):
        if isinstance(value, dict):
            return {k: without_cache(v) for k, v in value.items() if k != "cache_control"}
        if isinstance(value, list):
            return [without_cache(v) for v in value]
        return value

    return without_cache(kwargs)


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings().anthropic_api_key, max_retries=3)
    return _client


async def create(*, purpose: str, **kwargs):
    """messages.create sa merenjem. `purpose` ide u tabelu usage (chat, memory...)."""
    start = time.perf_counter()
    kwargs["model"] = await budget.model_for(kwargs["model"])
    kwargs = background_options(purpose, kwargs)
    response = await client().messages.create(**request_options(kwargs))
    latency = int((time.perf_counter() - start) * 1000)
    await usage.record(usage.from_response(kwargs["model"], response.usage), purpose, latency)
    return response


async def stream(*, purpose: str, on_text, **kwargs):
    """Prikaz teksta ne menja konačnu SDK poruku potrebnu za alate i istoriju."""
    started = time.perf_counter()
    kwargs["model"] = await budget.model_for(kwargs["model"])
    response = active = None
    try:
        async with client().messages.stream(**request_options(kwargs)) as active:
            text = ""
            async for part in active.text_stream:
                text += part
                await on_text(text)
            response = await active.get_final_message()
        return response
    finally:
        # I prekinut stream može već imati naplaćene ulazne/izlazne tokene.
        if response is None and active is not None:
            try:
                response = active.current_message_snapshot
            except (AssertionError, RuntimeError, AttributeError):
                pass
        if response is not None:
            await usage.record(
                usage.from_response(kwargs["model"], response.usage),
                purpose,
                int(1000 * (time.perf_counter() - started)),
            )


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


class IncompleteText(ValueError):
    """Nepotpun izlaz se nikada ne šalje niti čuva kao završen sažetak."""


async def create_text(
    *, purpose: str, max_tokens: int, retry_tokens: int, max_chars: int, **kwargs
) -> str:
    for cap in (max_tokens, retry_tokens):
        response = await create(purpose=purpose, max_tokens=cap, **kwargs)
        text = text_of(response)
        if response.stop_reason == "end_turn" and text and len(text) <= max_chars:
            return text
        # Dijagnostika ne sadrži privatne izvore, generisan tekst ni thinking blokove.
        detail = (
            f"namena={purpose}, prekid={response.stop_reason}, znakova={len(text)}, budžet={cap}"
        )
        log.warning("Nepotpun pozadinski tekst (%s).", detail)
        if response.stop_reason != "max_tokens":
            break
    raise IncompleteText(f"Generisanje nije završeno ({detail}).")


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
