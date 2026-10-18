"""Praćenje tokena, cene i latencije svakog poziva modela.

Bez ovoga nema odgovora na pitanje "koliko me košta Dexter i da li je optimizacija
pomogla". Svaki poziv modela upisuje jedan red u tabelu `usage`.

Cene su po milion tokena (USD). Proveri aktuelne na
https://platform.claude.com/docs/en/about-claude/pricing i ažuriraj tabelu.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID, uuid4

from dexter.db import pool

log = logging.getLogger(__name__)
_capture: ContextVar[list | None] = ContextVar("usage_capture", default=None)
_turn: ContextVar[tuple[int, UUID] | None] = ContextVar("usage_turn", default=None)


@contextmanager
def turn(chat_id: int):
    token = _turn.set((chat_id, uuid4()))
    try:
        yield
    finally:
        _turn.reset(token)


def turn_id(chat_id: int | None = None) -> UUID | None:
    current = _turn.get()
    return current[1] if current and (chat_id is None or chat_id == current[0]) else None


@contextmanager
def capture():
    rows = []
    token = _capture.set(rows)
    try:
        yield rows
    finally:
        _capture.reset(token)


# model: (input, output, faktor za čitanje iz keša)
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.10),
    "claude-sonnet-5-5": (2.00, 10.00, 0.05),
    "claude-opus-5-5": (4.00, 20.00, 0.05),
}
CACHE_WRITE_FACTOR = 1.25  # 5-minutni keš


@dataclass
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        inp, out, read_factor = PRICES.get(self.model, (0.0, 0.0, 0.1))
        return (
            self.input_tokens * inp
            + self.cache_write_tokens * inp * CACHE_WRITE_FACTOR
            + self.cache_read_tokens * inp * read_factor
            + self.output_tokens * out
        ) / 1_000_000


def from_response(model: str, u) -> Usage:
    """Pretvara `response.usage` iz Anthropic SDK-a u naš Usage."""
    return Usage(
        model=model,
        input_tokens=u.input_tokens or 0,
        output_tokens=u.output_tokens or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


async def record(u: Usage, purpose: str, latency_ms: int) -> None:
    captured = _capture.get()
    if captured is not None:
        captured.append({"usage": u, "purpose": purpose, "latency_ms": latency_ms})
    try:
        await pool().execute(
            """INSERT INTO usage (model, purpose, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, turn_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
            u.model, purpose, u.input_tokens, u.output_tokens,
            u.cache_read_tokens, u.cache_write_tokens, u.cost_usd, latency_ms,
            turn_id(),
        )  # fmt: skip
        from dexter import budget

        await budget.model_for()
    except Exception:  # merenje nikad ne sme da obori odgovor
        log.exception("Ne mogu da upišem usage.")


async def report(days: int = 7) -> str:
    """Kratak izveštaj za komandu /troskovi."""
    rows = await pool().fetch(
        """SELECT model, count(*) AS n, sum(cost_usd) AS cost,
                  sum(input_tokens + cache_read_tokens + cache_write_tokens) AS inp,
                  sum(cache_read_tokens) AS cached,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50
           FROM usage WHERE created_at > now() - make_interval(days => $1)
           GROUP BY model ORDER BY cost DESC""",
        days,
    )
    if not rows:
        return f"Nema poziva u poslednjih {days} dana."

    lines = [f"💰 Troškovi, poslednjih {days} dana:"]
    total = 0.0
    for r in rows:
        total += float(r["cost"])
        hit = 100 * (r["cached"] or 0) / max(r["inp"] or 1, 1)
        lines.append(
            f"- {r['model']}: {r['n']} poziva, ${float(r['cost']):.3f}, "
            f"keš {hit:.0f}%, medijana {int(r['p50'])} ms"
        )
    lines.append(f"Ukupno: ${total:.3f}")
    return "\n".join(lines)
