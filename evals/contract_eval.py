"""Offline regresija verifikatora; ne ocenjuje stvarni OCR ili tumačenje modela."""

import copy
import json
from collections import Counter
from datetime import date

from dexter.contracts.evidence import checked, proposals
from dexter.contracts.models import Extraction
from evals.contract_cases import PAGES, extraction


def evaluate():
    cases = []
    for name, expected in [
        ("uredan", 2),
        ("izmisljen_citat", 1),
        ("pogresan_datum", 1),
        ("uslovni_istek", 1),
        ("bez_podataka", 0),
    ]:
        data = extraction()
        pages = copy.deepcopy(PAGES)
        if name == "izmisljen_citat":
            data.obaveze[0].do_kada.dokaz.citat = "Ovaj citat ne postoji u ugovoru."
        elif name == "pogresan_datum":
            data.obaveze[0].do_kada.vrednost = "2030-03-16"
        elif name == "uslovni_istek":
            pages[1].append("Ugovor se automatski produžava.")
        elif name == "bez_podataka":
            data = Extraction()
        verified = checked(data, pages)
        fields = [f for party in verified["strane"] for f in party.values()]
        fields += list(verified["datumi"].values())
        fields += [f for item in verified["obaveze"] for f in item.values()]
        actual = len(proposals(data, pages, date(2026, 10, 19)))
        cases.append(
            {
                "primer": name,
                "statusi": dict(Counter(f["status"] for f in fields)),
                "predlozi": actual,
                "ocekivano_predloga": expected,
                "uspeh": actual == expected,
            }
        )
    return {
        "primeri": cases,
        "uspesno": sum(c["uspeh"] for c in cases),
        "ukupno": len(cases),
        "placeni_pozivi": 0,
        "napomena": "Kontrolni izlazi modela. Ne meri kvalitet stvarnog OCR-a ili LLM-a.",
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
