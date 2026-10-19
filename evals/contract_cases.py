"""Javni, potpuno izmišljeni primer ugovora za kontrolne provere."""

import copy
from datetime import date

from dexter.contracts import evidence
from dexter.contracts.models import Extraction, Review

PAGES = [
    [
        "IZMIŠLJEN TEST UGOVOR. Nije za potpisivanje niti pravnu upotrebu.",
        "Studio Primer, PIB: 000000001, uloga: Izvršilac.",
        "Firma Primer, PIB: 000000002, uloga: Naručilac.",
        "Ugovor je zaključen 01.02.2030.",
    ],
    [
        "Ugovor počinje 01.03.2030.",
        "Ugovor važi do 31.12.2030.",
        "Otkazni rok je 30 dana.",
        "Izvršilac se obavezuje da dostavi izveštaj do 15.03.2030. Naknada je 12.000,00 RSD.",
    ],
]


def fact(value, page, para):
    return {
        "vrednost": value,
        "dokaz": {"strana": page, "pasus": para, "citat": PAGES[page - 1][para - 1]},
    }


def extraction():
    return Extraction.model_validate(
        {
            "strane": [
                {
                    "naziv": fact("Studio Primer", 1, 2),
                    "uloga": fact("Izvršilac", 1, 2),
                    "pib_dokaz": fact("", 1, 2)["dokaz"],
                },
                {
                    "naziv": fact("Firma Primer", 1, 3),
                    "uloga": fact("Naručilac", 1, 3),
                    "pib_dokaz": fact("", 1, 3)["dokaz"],
                },
            ],
            "datumi": {
                "zakljucenje": fact("2030-02-01", 1, 4),
                "pocetak": fact("2030-03-01", 2, 1),
                "istek": fact("2030-12-31", 2, 2),
                "otkazni_rok": fact("30 dana", 2, 3),
            },
            "obaveze": [
                {
                    "ko": fact("Izvršilac", 2, 4),
                    "sta": fact("dostavi izveštaj", 2, 4),
                    "do_kada": fact("2030-03-15", 2, 4),
                    "iznos": fact("12.000,00 RSD", 2, 4),
                }
            ],
        }
    )


def review(owner=1):
    data = extraction()
    return Review(
        id="00000000-0000-0000-0000-000000000001",
        owner=owner,
        sha256="a" * 64,
        naziv="izmisljeni-ugovor.pdf",
        stranice=copy.deepcopy(PAGES),
        izdvojeno=data,
        predlozi=evidence.proposals(data, PAGES, date(2026, 10, 19)),
    )
