"""Proverljiva statistika navika; razlika proseka nije dokaz uzročnosti."""

import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean

from dexter.config import settings
from dexter.services import checklist, dnevnik, notion
from dexter.services import notion_days as days

MOOD_SCORES = dict(zip(dnevnik.MOODS, (5, 4, 3, 2, 1), strict=True))
ENERGY_SCORES = dict(zip(dnevnik.ENERGIES, (3, 2, 1), strict=True))


def rounded(value: float, places: int = 1) -> float:
    # Isti prikaz kao v1: 2.25 na jednu decimalu daje 2.3, a ne bankarskih 2.2.
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def unique_rows(rows: list[dict], start: str, end: str) -> tuple[list[dict], int]:
    valid = []
    for entry in rows:
        try:
            value = entry.get("datum")
            if not value or date.fromisoformat(value).isoformat() != value:
                continue
            if start <= value <= end:
                valid.append(entry)
        except (ValueError, TypeError):
            continue
    counts = Counter(entry["datum"] for entry in valid)
    # Ne biramo proizvoljan duplikat: taj dan nema pouzdan skor ni vezu sa dnevnikom.
    result = [entry for entry in valid if counts[entry["datum"]] == 1]
    return sorted(result, key=lambda p: p["datum"]), len(rows) - len(result)


def streaks(entries: list[dict], threshold: int, end: str) -> dict:
    longest = current = 0
    previous = None
    for entry in entries:
        current_day = date.fromisoformat(entry["datum"])
        if entry["skor"] >= threshold:
            current = current + 1 if previous == current_day - timedelta(days=1) else 1
            longest = max(longest, current)
        else:
            current = 0
        previous = current_day
    return {"tekuci": current if previous == date.fromisoformat(end) else 0, "najduzi": longest}


def associations(entries: list[dict], diary: dict, field: str, scores: dict) -> list[dict]:
    results = []
    for name in checklist.items():
        yes, no = [], []
        for entry in entries:
            score = scores.get(diary.get(entry["datum"], {}).get(field))
            if score is not None:
                (yes if entry["stavke"][name] else no).append(score)
        if len(yes) >= 3 and len(no) >= 3:
            results.append(
                {
                    "stavka": name,
                    "danaSa": len(yes),
                    "danaBez": len(no),
                    "prosekSa": rounded(mean(yes), 2),
                    "prosekBez": rounded(mean(no), 2),
                    "razlika": rounded(mean(yes) - mean(no), 2),
                }
            )
    return sorted(results, key=lambda p: abs(p["razlika"]), reverse=True)[:3]


def calculate(checks: list[dict], diary: list[dict], start: str, end: str) -> dict:
    checks, bad_checks = unique_rows(checks, start, end)
    diary, bad_diary = unique_rows(diary, start, end)
    notes = []
    if bad_checks or bad_diary:
        notes.append(
            "Izostavljeni nepouzdani redovi (dupli/neispravni datumi): "
            f"checklista {bad_checks}, dnevnik {bad_diary}."
        )
    if not checks:
        return {
            "od": start,
            "do": end,
            "brojDana": 0,
            "poruka": "Nema nijednog pouzdanog dana u tom periodu.",
            "napomena": " ".join(notes) or None,
        }
    names = checklist.items()
    maximum = len(names)
    entries = [{**p, "skor": sum(bool(p["stavke"][s]) for s in names)} for p in checks]
    average = mean(p["skor"] for p in entries)
    by_weekday = defaultdict(list)
    for entry in entries:
        by_weekday[days.DAYS[date.fromisoformat(entry["datum"]).weekday()]].append(entry["skor"])
    weekdays = sorted(
        [
            {"dan": name, "prosek": rounded(mean(values)), "merenja": len(values)}
            for name, values in by_weekday.items()
        ],
        key=lambda p: p["prosek"],
        reverse=True,
    )
    by_date = {p["datum"]: p for p in diary}
    moods = associations(entries, by_date, "raspolozenje", MOOD_SCORES)
    energies = associations(entries, by_date, "energija", ENERGY_SCORES)
    matched_moods = sum(
        by_date.get(p["datum"], {}).get("raspolozenje") in MOOD_SCORES for p in entries
    )
    matched_energies = sum(
        by_date.get(p["datum"], {}).get("energija") in ENERGY_SCORES for p in entries
    )
    if not moods or not energies:
        notes.append(
            "Za pojedine veze nema dovoljno podataka: potrebno je najmanje 3 dana "
            "sa označenom i 3 sa neoznačenom navikom, uz poznatu ocenu iz dnevnika."
        )
    if moods or energies:
        notes.append(
            "Veze su razlike prosečnih ocena, ne dokaz da navika uzrokuje "
            "raspoloženje ili energiju."
        )
    missing = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1 - len(entries)
    if missing:
        notes.append(
            f"Bez pouzdanog reda: {missing} dana; prosek se računa samo iz postojećih redova."
        )
    return {
        "od": start,
        "do": end,
        "brojDana": len(entries),
        "danaBezReda": missing,
        "prosekSkora": rounded(average),
        "maksSkor": maximum,
        "prosekProcenat": int(average / maximum * 100 + 0.5),
        "najboljiDan": max(entries, key=lambda p: p["skor"]),
        "nizovi": streaks(entries, math.ceil(maximum * 0.7), end),
        "najcescePreskoceno": sorted(
            [
                {
                    "stavka": name,
                    "propusteno": sum(not p["stavke"][name] for p in entries),
                    "udeo": int(
                        sum(not p["stavke"][name] for p in entries) / len(entries) * 100 + 0.5
                    ),
                }
                for name in names
            ],
            key=lambda p: p["propusteno"],
            reverse=True,
        )[:5],
        "poDanimaNedelje": weekdays,
        "vezaSaRaspolozenjem": moods,
        "vezaSaEnergijom": energies,
        "uparenoRaspolozenje": matched_moods,
        "uparenoEnergija": matched_energies,
        "napomena": " ".join(notes) or None,
    }


async def get(dana: int = 30, datum: str | None = None) -> dict:
    if not 1 <= dana <= 366:
        raise ValueError("Period mora biti 1–366 dana.")
    end = days.day(datum)
    start = (end - timedelta(days=dana - 1)).isoformat()
    async with notion.client() as api:
        source_id = await days.source(api, "NOTION_CHECKLIST_DB_ID")
        checks = [
            checklist.row(p) for p in await days.period(api, source_id, start, end.isoformat())
        ]
        diary = []
        if settings().notion_dnevnik_db_id:
            source_id = await days.source(api, "NOTION_DNEVNIK_DB_ID")
            diary = [
                dnevnik.row(p) for p in await days.period(api, source_id, start, end.isoformat())
            ]
    return calculate(checks, diary, start, end.isoformat())
