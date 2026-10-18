"""KLIJENTI: prepoznavanje firme i upis samo prosleđenih podataka iz v1."""

import asyncio
import re
import unicodedata
from collections import defaultdict
from urllib.parse import urlsplit

from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion

REQUIRES = ["NOTION_API_KEY", "NOTION_CLIENTS_DB_ID"]
TEXT_FIELDS = {
    "nazivZaFakturu": "Naziv za fakturu",
    "pib": "PIB",
    "mb": "MB",
    "adresa": "Adresa",
    "grad": "Grad",
    "opis": "Opis",
}
SELECT_FIELDS = {
    "aktivan": ("Aktivan", ("Aktivan", "Arhiva", "U izradi")),
    "tip": ("Tip", ("Klijent", "Interni", "Veliki ugovor")),
    "status": ("Status", ("Plaćeno", "Nije plaćeno", "Ne plaća")),
    "faktura": ("Faktura", ("Poslato", "Nije poslato", "Ne plaća")),
    "ponuda": ("Ponuda", ("Poslato", "Nije poslato")),
    "trajanje": ("Trajanje", ("Mesečno", "12 meseci", "6 meseci", "Nema održavanja")),
    "elementor": ("Elementor", ("Da", "Ne")),
    "mojHosting": ("Moj hosting", ("Da", "Ne")),
}
LEGAL_FORMS = {
    "pr",
    "doo",
    "d",
    "o",
    "ad",
    "dooel",
    "preduzetnik",
    "agencija",
    "llc",
    "ltd",
    "inc",
    "gmbh",
    "company",
    "co",
}
_locks = defaultdict(asyncio.Lock)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFD", u_latinicu(value).lower().replace("đ", "d"))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(
        word for word in re.sub(r"[^a-z0-9\s]", " ", value).split() if word not in LEGAL_FORMS
    )


def same_company(first: str, second: str) -> bool:
    first, second = normalized(first), normalized(second)
    if not first or not second:
        return False
    if first == second:
        return True
    a, b = set(first.split()), set(second.split())
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    return len(small) >= 2 and small <= large


def candidates(rows: list[dict], name: str, partial: bool = False) -> list[dict]:
    literal = u_latinicu(name).strip().casefold()
    core = normalized(name)
    if not core:
        raise ValueError("Navedi prepoznatljiv naziv firme, ne samo pravni oblik.")
    tiers = [
        lambda value: value.casefold() == literal,
        lambda value: normalized(value) == core,
        lambda value: same_company(value, name),
    ]
    if partial:
        tiers.append(lambda value: literal in value.casefold())
    for matches in tiers:
        found = [p for p in rows if matches(p["klijent"]) or matches(p["naziv"])]
        if found:
            return found
    return []


def domain_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError("Domen mora biti važeći HTTP/HTTPS URL ili naziv domena.")
    return value


def properties(values: dict) -> dict:
    result = {}
    if values.get("naziv"):
        result["Klijent"] = {"title": notion.text_fragments(values["naziv"])}
    for field, column in TEXT_FIELDS.items():
        if values.get(field):
            result[column] = {"rich_text": notion.text_fragments(values[field])}
    for field, kind in (("email", "email"), ("telefon", "phone_number")):
        if values.get(field):
            result[field.capitalize()] = {kind: values[field]}
    if values.get("domen"):
        result["Domen"] = {"url": domain_url(values["domen"])}
    if values.get("odrzavanjeCena") is not None:
        result["Održavanje cena"] = {"number": values["odrzavanjeCena"]}
    for field, (column, allowed) in SELECT_FIELDS.items():
        value = values.get(field)
        if value:
            if value not in allowed:
                raise ValueError(
                    f"Nepoznata vrednost za {column}. Dozvoljeno: {', '.join(allowed)}."
                )
            result[column] = {"select": {"name": value}}
    return result


def row(page: dict) -> dict:
    props = page.get("properties", {})
    title = u_latinicu(notion.rich_text(props.get("Klijent", {}).get("title", [])))
    result = {
        "id": page["id"],
        "url": page.get("url"),
        "klijent": title,
        **{
            field: u_latinicu(notion.rich_text(props.get(column, {}).get("rich_text", []))).strip()
            for field, column in TEXT_FIELDS.items()
        },
        **{
            field: u_latinicu((props.get(column, {}).get("select") or {}).get("name"))
            for field, (column, _) in SELECT_FIELDS.items()
        },
        "domen": props.get("Domen", {}).get("url"),
        "email": props.get("Email", {}).get("email"),
        "telefon": props.get("Telefon", {}).get("phone_number"),
        "odrzavanjeCena": props.get("Održavanje cena", {}).get("number"),
        "odrzavanjeDatum": (props.get("Održavanje datum", {}).get("date") or {}).get("start"),
        "datumPustanja": (props.get("Datum puštanja", {}).get("date") or {}).get("start"),
    }
    result["naziv"] = result["nazivZaFakturu"] or title
    return result


async def source(api) -> str:
    return await notion.database_source(
        api, settings().notion_clients_db_id, "NOTION_CLIENTS_DB_ID"
    )


async def all_clients(api, source_id: str) -> list[dict]:
    return [row(p) async for p in notion.query_pages(api, source_id)]


async def find(query: str) -> list[dict]:
    async with notion.client() as api:
        return candidates(await all_clients(api, await source(api)), query, partial=True)


async def list_clients(aktivan: str | None = None, limit: int = 50) -> list[dict]:
    async with notion.client() as api:
        source_id = await source(api)
        filter_ = {"property": "Aktivan", "select": {"equals": aktivan}} if aktivan else None
        return [row(p) async for p in notion.query_pages(api, source_id, filter_, limit)]


async def add(values: dict) -> dict:
    properties(values)
    if not values.get("naziv") or not normalized(values["naziv"]):
        raise ValueError("Nedostaje prepoznatljiv naziv klijenta.")
    async with notion.client() as api:
        source_id = await source(api)
        # Paralelni pozivi modela ne smeju oba da pročitaju praznu listu pre create-a.
        async with _locks[source_id]:
            found = candidates(await all_clients(api, source_id), values["naziv"])
            if len(found) > 1:
                raise ValueError(
                    "Naziv liči na više klijenata: "
                    + ", ".join(p["klijent"] for p in found)
                    + ". Preciziraj i koristi client_update."
                )
            if found:
                existing = found[0]
                updates = {k: v for k, v in values.items() if k != "naziv"}
                if (
                    not updates.get("nazivZaFakturu")
                    and not existing["nazivZaFakturu"]
                    and u_latinicu(values["naziv"]).strip() != existing["klijent"].strip()
                ):
                    updates["nazivZaFakturu"] = values["naziv"]
                props = properties(updates)
                if not props:
                    return {
                        **existing,
                        "dopunjen": False,
                        "poruka": "Klijent već postoji; nema šta da se dopuni.",
                    }
                page = await api.pages.update(page_id=existing["id"], properties=props)
                return {
                    **row(page),
                    "dopunjen": True,
                    "poruka": "Dopunjen je postojeći klijent; nije napravljen novi red. "
                    "Reci to korisniku.",
                }
            page = await api.pages.create(
                parent={"type": "data_source_id", "data_source_id": source_id},
                properties=properties({"aktivan": "Aktivan", "tip": "Klijent", **values}),
            )
            return {**row(page), "dopunjen": False}


async def update(klijent: str, values: dict) -> dict:
    props = properties(values)
    if not props:
        raise ValueError("Nije zadato nijedno polje za izmenu.")
    async with notion.client() as api:
        source_id = await source(api)
        async with _locks[source_id]:
            found = candidates(await all_clients(api, source_id), klijent, partial=True)
            if not found:
                raise ValueError(f'Ne nalazim klijenta "{klijent}" u bazi.')
            if len(found) > 1:
                raise ValueError(
                    "Naziv odgovara većem broju klijenata: "
                    + ", ".join(p["klijent"] for p in found)
                    + ". Budi precizniji."
                )
            return row(await api.pages.update(page_id=found[0]["id"], properties=props))
