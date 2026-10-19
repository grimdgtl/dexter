"""Offline poređenje izbora modela; ne meri kvalitet generisanih odgovora."""

import json
import time
from collections import Counter
from pathlib import Path

from dexter.agent.router import pick_economy_model, pick_model
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.usage import Usage


def evaluate(rows: list[dict] | None = None) -> list[dict]:
    if rows is None:
        rows = [
            json.loads(line)
            for line in Path(__file__).with_name("router.jsonl").read_text().splitlines()
            if line.strip()
        ]
    cfg = settings()
    reports = []
    for mode, choose in (("rule", pick_model), ("economy", pick_economy_model)):
        started = time.perf_counter()
        models = [choose(row["poruka"])[0] for row in rows]
        counts = Counter(models)
        # Isti zamišljeni tokeni razdvajaju promenu cene modela od ponašanja samog LLM-a.
        hypothetical = sum(
            Usage(model, 1000, 250, cache_read_tokens=4000, cache_write_tokens=1000).cost_usd
            for model in models
        )
        reports.append(
            {
                "rezim": mode,
                "poruka": len(rows),
                "modeli": dict(counts),
                "lako_na_brzom": sum(
                    row["nivo"] == "lako" and model == cfg.model_fast
                    for row, model in zip(rows, models, strict=True)
                ),
                "srednje_ili_tesko_na_brzom": sum(
                    row["nivo"] != "lako" and model == cfg.model_fast
                    for row, model in zip(rows, models, strict=True)
                ),
                "ms_po_poruci": round(1000 * (time.perf_counter() - started) / len(rows), 4),
                "hipoteticki_usd": round(hypothetical, 6),
                "placeni_pozivi_izbora": 0,
                "napomena": "Sintetičke poruke, identični zamišljeni tokeni. "
                "Kvalitet odgovora, stvarni tokeni i produkciona ušteda nisu mereni.",
            }
        )
    return reports


if __name__ == "__main__":
    print(u_latinicu(json.dumps(evaluate(), ensure_ascii=False, indent=2)))
