"""Dnevnik čuva samo navedena polja; praznine ostaju vidljive za potpitanje."""

from dexter.pismo import u_latinicu
from dexter.services import notion
from dexter.services import notion_days as days

REQUIRES = ["NOTION_API_KEY", "NOTION_DNEVNIK_DB_ID"]
MOODS = ("Odlično", "Dobro", "Neutralno", "Loše", "Teško")
ENERGIES = ("Visoka", "Srednja", "Niska")
FIELDS = ("Raspoloženje", "Energija", "Ključna reč")


def row(page: dict) -> dict:
    props = page.get("properties", {})
    values = [
        u_latinicu((props.get("Raspoloženje", {}).get("select") or {}).get("name")),
        u_latinicu((props.get("Energija", {}).get("select") or {}).get("name")),
        u_latinicu(notion.rich_text(props.get("Ključna reč", {}).get("rich_text", []))) or None,
    ]
    empty = [name for name, value in zip(FIELDS, values, strict=True) if not value]
    return {
        "id": page["id"],
        "url": page.get("url"),
        "dan": u_latinicu(notion.rich_text(props.get("Dan", {}).get("title", []))),
        "datum": (props.get("Datum", {}).get("date") or {}).get("start"),
        "raspolozenje": values[0],
        "energija": values[1],
        "kljucnaRec": values[2],
        "prazno": empty,
        "popunjen": not empty,
    }


async def get(datum: str | None = None) -> dict:
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        page = await days.find(api, await days.source(api, "NOTION_DNEVNIK_DB_ID"), datum)
        return (
            {**row(page), "postoji": True}
            if page
            else {
                "datum": datum,
                "dan": days.DAYS[days.day(datum).weekday()],
                "postoji": False,
                "popunjen": False,
                "prazno": list(FIELDS),
            }
        )


async def create_day(datum: str | None = None, checklist_page_id: str | None = None) -> dict:
    datum = days.day(datum).isoformat()
    extra = {"Checklista": {"relation": [{"id": checklist_page_id}]}} if checklist_page_id else None
    async with notion.client() as api:
        page, existed = await days.ensure(
            api, await days.source(api, "NOTION_DNEVNIK_DB_ID"), datum, extra
        )
        return {**row(page), "vecPostojao": existed}


async def write(datum=None, raspolozenje=None, energija=None, kljucnaRec=None) -> dict:
    if raspolozenje is not None and raspolozenje not in MOODS:
        raise ValueError("Nepoznato raspoloženje. Dozvoljeno: " + ", ".join(MOODS))
    if energija is not None and energija not in ENERGIES:
        raise ValueError("Nepoznata energija. Dozvoljeno: " + ", ".join(ENERGIES))
    properties = {}
    if raspolozenje is not None:
        properties["Raspoloženje"] = {"select": {"name": raspolozenje}}
    if energija is not None:
        properties["Energija"] = {"select": {"name": energija}}
    if kljucnaRec is not None:
        if not kljucnaRec.strip() or len(kljucnaRec) > 2000:
            raise ValueError("Ključna reč mora imati 1–2000 znakova.")
        properties["Ključna reč"] = {
            "rich_text": [{"text": {"content": u_latinicu(kljucnaRec.strip())}}]
        }
    datum = days.day(datum).isoformat()
    async with notion.client() as api:
        page, _ = await days.ensure(api, await days.source(api, "NOTION_DNEVNIK_DB_ID"), datum)
        if properties:
            page = await api.pages.update(page_id=page["id"], properties=properties)
        return row(page)
