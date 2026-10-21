"""CI ne traži API ključ: promenjen prompt zahteva već sačuvan stvarni pre/posle eval."""

import argparse
import asyncio
import json

from dexter.agent.prompts import SYSTEM_PROMPT
from evals.persona_eval import Judgment
from evals.persona_support import HERE, corpus_hash, digest, git_prompt, read_cases


def verify_report(report, before, after, rows, rubric) -> bool:
    if (
        report.get("simulacija") is not False
        or report.get("skup_sha256") != corpus_hash(rows)
        or report.get("rubrika_sha256") != corpus_hash(rubric)
    ):
        return False
    if not report.get("kandidat") or not report.get("sudija"):
        return False
    for key, prompt in (("pre", before), ("posle", after)):
        run = report.get(key, {})
        cases = run.get("slučajevi", [])
        if (
            run.get("prompt_sha256") != digest(prompt)
            or run.get("n") != 20
            or len(cases) != 20
            or {r.get("id") for r in cases} != {r["id"] for r in rows}
        ):
            return False
        try:
            for case in cases:
                Judgment.model_validate(
                    {"ocene": case["ocene"], "obrazlozenje": case["obrazlozenje"]}
                )
        except (ValueError, KeyError):
            return False
    return True


async def check(base="HEAD", directory=HERE / "results") -> bool:
    before = SYSTEM_PROMPT if set(base) == {"0"} else await git_prompt(base)
    if before == SYSTEM_PROMPT:
        return True
    rows = await asyncio.to_thread(read_cases)
    rubric = json.loads(await asyncio.to_thread((HERE / "rubric.json").read_text))
    for path in await asyncio.to_thread(lambda: list(directory.glob("*.json"))):
        try:
            report = json.loads(await asyncio.to_thread(path.read_text))
            if verify_report(report, before, SYSTEM_PROMPT, rows, rubric):
                return True
        except (ValueError, KeyError, TypeError):
            continue
    raise ValueError(
        "SYSTEM_PROMPT je promenjen bez stvarnog persona pre/posle izveštaja za istih 20 scenarija i rubriku. Pokreni evals.persona_eval --prethodni-ref sa odgovarajućim baznim ref-om i sačuvaj izveštaj."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Provera persona evaluacije pri promeni sistemskog prompta."
    )
    parser.add_argument("--base", default="HEAD")
    args = parser.parse_args()
    asyncio.run(check(args.base))
    print("Persona provera prolazi: pravila nisu menjana ili postoji stvarno pre/posle merenje.")
