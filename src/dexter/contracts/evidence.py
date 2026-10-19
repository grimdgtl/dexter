"""Provera ne koristi LLM: citat, lokacija, doslovna vrednost i kalendarski datumi."""

import hashlib
import re
import unicodedata
from datetime import date, timedelta

from dexter.contracts.models import Citation, Extraction, Fact, Proposal
from dexter.pismo import u_latinicu


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", u_latinicu(text)).split())


def citation(c: Citation | None, pages: list[list[str]]) -> str | None:
    if c is None or c.strana > len(pages) or c.pasus > len(pages[c.strana - 1]):
        return None
    paragraph = pages[c.strana - 1][c.pasus - 1]
    return paragraph if normalized(c.citat) in normalized(paragraph) else None


def dates_in(text: str) -> set[date]:
    result = set()
    for value in re.findall(
        r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s*\.\s*\d{1,2}\s*\.\s*\d{4})(?!\d)", text
    ):
        try:
            if "-" in value:
                result.add(date.fromisoformat(value))
            else:
                day, month, year = map(int, re.findall(r"\d+", value))
                result.add(date(year, month, day))
        except ValueError:
            continue
    return result


def check(fact: Fact, pages: list[list[str]], *, kind="text") -> dict:
    result = {
        "vrednost": None,
        "predlog": u_latinicu(fact.vrednost or ""),
        "status": "nije_pronadjeno",
        "razlog": "Podatak nije izdvojen.",
        "izvor": None,
    }
    if not fact.vrednost:
        return result
    result.update(status="nepotvrdjeno", razlog="Citat nije pronađen na navedenoj lokaciji.")
    paragraph = citation(fact.dokaz, pages)
    if paragraph is None:
        return result
    result["izvor"] = {**fact.dokaz.model_dump(), "pasus_tekst": paragraph}
    quote = normalized(fact.dokaz.citat)
    value = normalized(fact.vrednost)
    valid = bool(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", quote))
    if kind == "money":
        # Deo broja posle separatora hiljada nije zaseban iznos.
        valid = bool(re.search(r"(?<![\w.,])" + re.escape(value) + r"(?!\w|[.,]\d)", quote))
    if kind == "date":
        try:
            valid = date.fromisoformat(value) in dates_in(quote)
        except ValueError:
            valid = False
    if not valid:
        result["razlog"] = "Citat postoji, ali predložena vrednost nije potvrđena u citatu."
        return result
    result.update(
        vrednost=value,
        status="citat_proveren",
        razlog="Citat i vrednost pronađeni u OCR tekstu; tumačenje proveri u originalu.",
    )
    return result


def tax_id(c: Citation | None, pages: list[list[str]]) -> dict:
    paragraph = citation(c, pages)
    if paragraph is None:
        return check(Fact(vrednost="PIB" if c else None, dokaz=c), pages) | {
            "status": "nepotvrdjeno" if c else "nije_pronadjeno",
            "vrednost": None,
        }
    ids = set(re.findall(r"\bPIB\s*[:=]?\s*([0-9]{9})(?!\d)", normalized(c.citat), re.I))
    if len(ids) != 1:
        return {
            "status": "nepotvrdjeno",
            "vrednost": None,
            "predlog": "",
            "razlog": "PIB nije jednoznačno pročitan uz oznaku PIB.",
            "izvor": None,
        }
    return check(Fact(vrednost=next(iter(ids)), dokaz=c), pages)


def checked(data: Extraction, pages: list[list[str]]) -> dict:
    return {
        "strane": [
            {
                "naziv": check(p.naziv, pages),
                "uloga": check(p.uloga, pages),
                "pib": tax_id(p.pib_dokaz, pages),
            }
            for p in data.strane
        ],
        "datumi": {
            key: check(value, pages, kind="text" if key == "otkazni_rok" else "date")
            for key, value in data.datumi
        },
        "obaveze": [
            {
                key: check(
                    value,
                    pages,
                    kind="date" if key == "do_kada" else "money" if key == "iznos" else "text",
                )
                for key, value in item
            }
            for item in data.obaveze
        ],
    }


def reference(field: dict) -> str:
    source = field["izvor"]
    return f"str. {source['strana']}, pasus {source['pasus']}: {source['pasus_tekst']}"


def proposals(data: Extraction, pages: list[list[str]], today: date) -> list[Proposal]:
    result = []
    verified = checked(data, pages)

    def add(text, due, reminder, source):
        task_id = hashlib.sha256(f"{text}\n{due}\n{source}".encode()).hexdigest()[:16]
        result.append(
            Proposal(
                id=task_id,
                tekst=text[:1200],
                rok=due.isoformat() if due else None,
                podsetnik=reminder.isoformat() if reminder else None,
                izvor=source,
            )
        )

    for item in verified["obaveze"]:
        if any(item[k]["status"] != "citat_proveren" for k in ("ko", "sta")):
            continue
        if any(f["status"] == "nepotvrdjeno" for f in item.values()):
            continue
        due = (
            date.fromisoformat(item["do_kada"]["vrednost"]) if item["do_kada"]["vrednost"] else None
        )
        if due and due < today:
            continue
        text = f"{item['ko']['vrednost']}: {item['sta']['vrednost']}"
        if item["iznos"]["vrednost"]:
            text += f" ({item['iznos']['vrednost']})"
        add(
            text,
            due,
            max(today, due - timedelta(days=1)) if due else None,
            "\n".join(dict.fromkeys(reference(f) for f in item.values() if f["izvor"])),
        )

    expiry = verified["datumi"]["istek"]
    all_text = normalized(" ".join(p for page in pages for p in page)).casefold()
    ambiguous = re.search(
        r"automatsk\w*|produž\w*|produz\w*|neodređen\w*|neodredjen\w*|pod uslovom", all_text
    )
    if expiry["status"] == "citat_proveren" and not ambiguous:
        value = date.fromisoformat(expiry["vrednost"])
        paragraph = expiry["izvor"]["pasus_tekst"]
        explicit = re.search(r"ističe|istice|važi do|vazi do|datum isteka", paragraph, re.I)
        due = value - timedelta(days=30)
        if explicit and dates_in(paragraph) == {value} and due >= today:
            add(f"Pregled ugovora 30 dana pre isteka ({value})", due, due, reference(expiry))
    return list({p.id: p for p in result}.values())
