"""Fiksnih 50 razmena kroz agenta, sa lažnim alatima i odvojenom test bazom."""

import argparse
import asyncio
import hashlib
import json
import secrets
import statistics
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote, urlsplit

from anthropic.types import Message

from dexter import db, llm, memory, usage
from dexter.agent import history, loop
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.tools import registry

HERE = Path(__file__).parent


def read_prompts(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != 50 or any(
        not isinstance(r.get("poruka"), str) or not r["poruka"].strip() for r in rows
    ):
        raise ValueError("Benchmark zahteva tačno 50 nepraznih poruka.")
    return rows


class Simulation:
    """Kontrolna procena tokena i statičkog keša; ne predstavlja ponašanje pravog API-ja."""

    def __init__(self, rows):
        self.rows = {r["poruka"]: r for r in rows}
        self.cached = set()

    async def create(self, **kwargs):
        messages = kwargs["messages"]
        last = messages[-1]["content"]
        tool_result = isinstance(last, list) and any(b.get("type") == "tool_result" for b in last)
        text = (
            next((b.get("text", "") for b in reversed(last) if b.get("type") == "text"), "")
            if isinstance(last, list)
            else last
        )
        case = self.rows.get(text, {})
        content = [{"type": "text", "text": "Kontrolni odgovor: podaci su obrađeni."}]
        if case.get("alat") and not tool_result:
            content = [{"type": "tool_use", "id": "bench_tool", "name": case["alat"], "input": {}}]
        prefix = json.dumps([kwargs.get("system"), kwargs.get("tools")], sort_keys=True)
        static_tokens = len(prefix) // 4
        key = (kwargs["model"], prefix)
        enabled = "cache_control" in prefix
        read = static_tokens if enabled and key in self.cached else 0
        write = static_tokens if enabled and not read else 0
        self.cached.add(key)
        return Message.model_validate(
            {
                "id": "bench",
                "type": "message",
                "role": "assistant",
                "model": kwargs["model"],
                "content": content,
                "stop_reason": "tool_use" if content[0]["type"] == "tool_use" else "end_turn",
                "usage": {
                    "input_tokens": max(1, len(json.dumps(messages)) // 4)
                    + (0 if read or write else static_tokens),
                    "output_tokens": 30,
                    "cache_read_input_tokens": read,
                    "cache_creation_input_tokens": write,
                },
            }
        )


async def benchmark(rows: list[dict], *, simulation: bool = False) -> dict:
    database = await db.pool().fetchval("SELECT current_database()")
    if not database.endswith(("_test", "_bench")):
        raise ValueError("Benchmark koristi zasebnu bazu sa sufiksom _test ili _bench.")
    cfg = settings()
    if any(model not in usage.PRICES for model in (cfg.model_fast, cfg.model_main, cfg.model_deep)):
        raise ValueError("Dopuni usage.PRICES za modele pre merenja cene.")
    chat_id = -secrets.randbits(62) - 1
    while chat_id == cfg.telegram_owner_chat_id:
        chat_id -= 1
    times = []

    async def fake_tool(name, raw_input):
        return registry.Outcome(
            json.dumps({"alat": name, "podaci": "Kontrolni podaci za benchmark."})
        )

    try:
        with ExitStack() as stack, usage.capture() as captured:
            stack.enter_context(patch.object(memory, "recall", AsyncMock(return_value=[])))
            stack.enter_context(patch.object(memory, "extract_and_save", AsyncMock()))
            stack.enter_context(patch.object(registry, "execute", fake_tool))
            if simulation:
                provider = Simulation(rows)
                stack.enter_context(
                    patch.object(
                        llm, "client", lambda: type("Client", (), {"messages": provider})()
                    )
                )
            for row in rows:
                started = time.perf_counter()
                await loop.run(chat_id, row["poruka"])
                times.append((time.perf_counter() - started) * 1000)
                await asyncio.gather(*tuple(loop._background))
        tokens = [r["usage"] for r in captured]
        by_purpose = {}
        for row in captured:
            by_purpose[row["purpose"]] = by_purpose.get(row["purpose"], 0) + row["usage"].cost_usd
        total_input = sum(
            u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in tokens
        )
        return {
            "poruka": len(rows),
            "poziva": len(tokens),
            "prompt_cache": cfg.prompt_cache,
            "simulacija": simulation,
            "history_turns": cfg.history_turns,
            "modeli": {"fast": cfg.model_fast, "main": cfg.model_main, "deep": cfg.model_deep},
            "cost_by_purpose": {name: round(cost, 6) for name, cost in by_purpose.items()},
            "cost_usd": round(sum(u.cost_usd for u in tokens), 6),
            "cache_percent": round(
                100 * sum(u.cache_read_tokens for u in tokens) / max(total_input, 1), 2
            ),
            "ms_po_poruci": round(statistics.mean(times), 2),
            "p95_ms": round(sorted(times)[int(0.95 * (len(times) - 1))], 2),
            "skup_sha256": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False).encode()
            ).hexdigest(),
        }
    finally:
        await history.clear(chat_id)


async def main(simulation: bool = False, compare: bool = False) -> list[dict]:
    if not unquote(urlsplit(settings().database_url).path).endswith(("_test", "_bench")):
        raise ValueError("DATABASE_URL benchmarka mora imenovati izdvojenu _test ili _bench bazu.")
    rows = await asyncio.to_thread(read_prompts, HERE / "prompts.jsonl")
    try:
        await db.connect()
        result = []
        for mode in ("off", "on") if compare else (settings().prompt_cache,):
            with patch.object(settings(), "prompt_cache", mode):
                result.append(await benchmark(rows, simulation=simulation))
        print(u_latinicu(json.dumps(result, ensure_ascii=False, indent=2)))
        return result
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark 50 poruka; alati se nikada ne izvršavaju."
    )
    parser.add_argument("--simulacija", action="store_true")
    parser.add_argument("--uporedi", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.simulacija, args.uporedi))
