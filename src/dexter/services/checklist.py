"""Dnevne navike i nedeljni cilj iz konfiguracije, bez menjanja formule Skor."""

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion, todo
from dexter.services import notion_days as days

REQUIRES = ["NOTION_API_KEY", "NOTION_CHECKLIST_DB_ID"]


def items() -> list[str]:
    cfg = settings()
    names = [
        s.strip()
        for csv in (cfg.checklist_pozitivne, cfg.checklist_izbegavanja)
        for s in csv.split(",")
        if s.strip()
    ]
    if not names or len(names) != len(set(names)):
        raise ValueError(
            "CHECKLIST_POZITIVNE / CHECKLIST_IZBEGAVANJA moraju dati neprazne, različite stavke."
        )
    return names


def row(page: dict) -> dict:
    props = page.get("properties", {})
    names = items()
    missing = [name for name in names if "checkbox" not in props.get(name, {})]
    if missing:
        raise ValueError("U Notion checklisti nedostaju Checkbox kolone: " + ", ".join(missing))
    values = {name: props[name]["checkbox"] for name in names}
    return {
        "id": page["id"],
        "url": page.get("url"),
        "dan": u_latinicu(notion.rich_text(props.get("Dan", {}).get("title", []))),
        "datum": (props.get("Datum", {}).get("date") or {}).get("start"),
        "stavke": values,
        "urađeno": sum(values.values()),
        "ukupno": len(names),
    }


async def weekly(api, source_id: str, datum: str) -> dict:
    cfg = settings()
    target = cfg.checklist_ciljna_stavka.strip()
    if target not in items():
        raise ValueError("CHECKLIST_CILJNA_STAVKA mora biti među podešenim stavkama.")
    start, end = todo.week_window(days.day(datum))
    pages = await days.period(api, source_id, start.isoformat(), end.isoformat())
    by_date = {}
    for page in pages:
        entry = row(page)
        if entry["datum"] in by_date:
            raise ValueError("Nedeljni cilj nije izračunat: postoje dupli datumi u checklisti.")
        by_date[entry["datum"]] = entry
    count = sum(bool(p["stavke"][target]) for p in by_date.values())
    return {
        "stavka": target,
        "odPonedeljka": start.isoformat(),
        "doNedelje": end.isoformat(),
        "bilo": count,
        "cilj": cfg.checklist_cilj_nedeljno,
        "ostalo": max(0, cfg.checklist_cilj_nedeljno - count),
        "ispunjen": count >= cfg.checklist_cilj_nedeljno,
    }


async def get(datum: str | None = None) -> dict:
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        source_id = await days.source(api, "NOTION_CHECKLIST_DB_ID")
        page = await days.find(api, source_id, datum)
        result = (
            row(page)
            if page
            else {
                "datum": datum,
                "dan": days.DAYS[days.day(datum).weekday()],
                "poruka": "Red za taj datum još ne postoji.",
                "stavke": dict.fromkeys(items(), False),
                "urađeno": 0,
                "ukupno": len(items()),
            }
        )
        return {
            **result,
            "postoji": page is not None,
            "fali": [s for s, marked in result["stavke"].items() if not marked],
            "teretana": await weekly(api, source_id, datum),
        }


async def create_day(datum: str | None = None) -> dict:
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        page, existed = await days.ensure(
            api, await days.source(api, "NOTION_CHECKLIST_DB_ID"), datum
        )
        return {**row(page), "vecPostojao": existed}


async def mark(stavke: dict[str, bool], datum: str | None = None) -> dict:
    unknown = set(stavke) - set(items())
    if unknown:
        raise ValueError(
            f"Nepoznate stavke: {', '.join(sorted(unknown))}. Dozvoljeno: {', '.join(items())}."
        )
    if not stavke or any(type(value) is not bool for value in stavke.values()):
        raise ValueError("Stavke moraju biti neprazna mapa naziva i true/false vrednosti.")
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        page, _ = await days.ensure(api, await days.source(api, "NOTION_CHECKLIST_DB_ID"), datum)
        row(page)
        return row(
            await api.pages.update(
                page_id=page["id"],
                properties={name: {"checkbox": value} for name, value in stavke.items()},
            )
        )


async def weekly_summary(datum: str | None = None) -> dict:
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        source_id = await days.source(api, "NOTION_CHECKLIST_DB_ID")
        target = await weekly(api, source_id, datum)
        entries = [
            row(p)
            for p in await days.period(api, source_id, target["odPonedeljka"], target["doNedelje"])
        ]
    total = sum(p["urađeno"] for p in entries)
    maximum = len(entries) * len(items())
    best = max(entries, key=lambda p: p["urađeno"], default=None)
    return {
        "odPonedeljka": target["odPonedeljka"],
        "doNedelje": target["doNedelje"],
        "brojDana": len(entries),
        "ukupnoStavki": total,
        "maksimum": maximum,
        "procenat": int(total / maximum * 100 + 0.5) if maximum else 0,
        "najboljiDan": {"dan": best["dan"], "skor": best["urađeno"]} if best else None,
        "teretana": target,
    }
