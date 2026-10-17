"""Poređenje pravila i klasifikatora na 40 unapred označenih sintetičkih poruka."""

import argparse
import asyncio
import json
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apu import db, llm, usage
from apu.agent.router import select_model
from apu.config import settings
from apu.pismo import u_latinicu

HERE = Path(__file__).parent


async def evaluate(*, simulation: bool = False, rows: list[dict] | None = None) -> list[dict]:
    if rows is None:
        rows = [
            json.loads(line)
            for line in (await asyncio.to_thread((HERE / "router.jsonl").read_text)).splitlines()
            if line.strip()
        ]
        if len(rows) != 40:
            raise ValueError("Podrazumevani router eval zahteva 40 označenih poruka.")
    if not rows or any(
        r.get("nivo") not in {"lako", "srednje", "teško"} or not r.get("poruka") for r in rows
    ):
        raise ValueError("Router eval zahteva označene poruke.")
    gold = {r["poruka"]: r["nivo"] for r in rows}

    async def create(**kwargs):
        text = json.loads(kwargs["messages"][0]["content"])["poruka"]
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps({"nivo": gold[text]}))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=120, output_tokens=10),
        )

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    reports = []
    with patch.object(llm, "client", lambda: fake) if simulation else nullcontext():
        for mode in ("rule", "classifier"):
            correct = 0
            confusion = {}
            start = time.perf_counter()
            with patch.object(settings(), "router_mode", mode), usage.capture() as captured:
                for row in rows:
                    model, _ = await select_model(row["poruka"])
                    levels = {
                        settings().model_fast: "lako",
                        settings().model_main: "srednje",
                        settings().model_deep: "teško",
                    }
                    predicted = levels[model]
                    correct += predicted == row["nivo"]
                    pair = f"{row['nivo']} → {predicted}"
                    confusion[pair] = confusion.get(pair, 0) + 1
            reports.append(
                {
                    "režim": mode,
                    "n": len(rows),
                    "tačnost": round(correct / len(rows), 3),
                    "ms_po_poruci": round(1000 * (time.perf_counter() - start) / len(rows), 2),
                    "trošak_izbora_usd": round(sum(r["usage"].cost_usd for r in captured), 6),
                    "matrica": confusion,
                    "simulacija": simulation,
                }
            )
    return reports


async def main(simulation=False):
    try:
        await db.connect()
        print(
            u_latinicu(
                json.dumps(await evaluate(simulation=simulation), ensure_ascii=False, indent=2)
            )
        )
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poređenje izbora modela na 40 poruka.")
    parser.add_argument("--simulacija", action="store_true")
    asyncio.run(main(parser.parse_args().simulacija))
