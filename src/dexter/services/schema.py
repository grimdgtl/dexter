"""Notion šema je ugovor za čitanje; provera nikada ne menja baze ni njihove redove."""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field

from notion_client import APIResponseError, RequestTimeoutError
from telegram.error import BadRequest, Forbidden, RetryAfter

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import checklist, notion

log = logging.getLogger(__name__)
STATE_KEY = "schema-check"
CHECK_TIMEOUT = 15


@dataclass
class ExpectedBase:
    name: str
    database_id: str
    columns: dict[str, str]
    untracked: str | None = None
    filter_column: str | None = None
    configuration: list[str] = field(default_factory=list)


def expected() -> list[ExpectedBase]:
    cfg = settings()
    if not cfg.notion_api_key:
        return []
    bases = []
    for name, attribute, columns in (
        ("TASK BOARD", "notion_tasks_db_id", {"Name": "title", "Status": "status"}),
        (
            "KLIJENTI",
            "notion_clients_db_id",
            {"Klijent": "title", "Domen": "url", "Aktivan": "select"},
        ),
        ("Rođendani", "notion_birthdays_db_id", {"Ime i prezime": "title", "Rođendan": "date"}),
        (
            "FAKTURE",
            "notion_invoices_db_id",
            {
                "Broj": "title",
                "Datum izdavanja": "date",
                "Datum prometa": "date",
                "Iznos": "number",
                "Status": "select",
            },
        ),
    ):
        if database_id := getattr(cfg, attribute):
            bases.append(ExpectedBase(name, database_id, columns))
    if cfg.notion_checklist_db_id:
        configuration = []
        names = [
            value.strip()
            for csv in (cfg.checklist_pozitivne, cfg.checklist_izbegavanja)
            for value in csv.split(",")
            if value.strip()
        ]
        try:
            checklist.items()
        except ValueError as exc:
            configuration.append(str(exc))
        target = cfg.checklist_ciljna_stavka.strip()
        if target not in names:
            configuration.append(
                "CHECKLIST_CILJNA_STAVKA mora biti među podešenim stavkama checkliste."
            )
        bases.append(
            ExpectedBase(
                "Dnevna checklista",
                cfg.notion_checklist_db_id,
                {"Dan": "title", "Datum": "date", **dict.fromkeys(names, "checkbox")},
                "checkbox",
                target,
                configuration,
            )
        )
    if cfg.notion_dnevnik_db_id:
        columns = {
            "Dan": "title",
            "Datum": "date",
            "Raspoloženje": "select",
            "Energija": "select",
            "Ključna reč": "rich_text",
        }
        if cfg.notion_checklist_db_id:
            columns["Checklista"] = "relation"
        bases.append(ExpectedBase("Dnevnik", cfg.notion_dnevnik_db_id, columns))
    if cfg.notion_todo_db_id:
        bases.append(
            ExpectedBase(
                "To-do lista",
                cfg.notion_todo_db_id,
                {"Zadatak": "title", "Status": "status", "Rok": "date"},
            )
        )
    return bases


class Unavailable(Exception):
    pass


def error_reason(exc: Exception) -> str:
    if isinstance(exc, Unavailable):
        return str(exc)
    if isinstance(exc, (TimeoutError, RequestTimeoutError)):
        return "Isteklo je vreme provere; dostupnost i šema nisu potvrđene."
    if isinstance(exc, APIResponseError):
        return {
            401: "Notion prijava nije prihvaćena; proveri NOTION_API_KEY.",
            403: "Pristup nije dozvoljen; podeli bazu sa Notion integracijom.",
            404: "Baza ili izvor nisu dostupni; proveri ID i deljenje sa integracijom.",
            429: "Notion je ograničio broj zahteva; ponovi proveru kasnije.",
        }.get(exc.status, "Notion zahtev nije uspeo; dostupnost i šema nisu potvrđene.")
    return "Provera nije uspela; dostupnost i šema nisu potvrđene."


def compare(base: ExpectedBase, properties: dict) -> dict | None:
    missing, wrong = [], []
    for name, kind in base.columns.items():
        actual = properties.get(name)
        if not actual:
            missing.append({"ime": name, "uFilteru": name == base.filter_column})
        elif actual.get("type") != kind:
            wrong.append(
                {"ime": name, "ocekivano": kind, "nadjeno": actual.get("type", "nepoznat")}
            )
    untracked = sorted(
        name
        for name, prop in properties.items()
        if base.untracked and prop.get("type") == base.untracked and name not in base.columns
    )
    if missing or wrong or untracked or base.configuration:
        return {
            "baza": base.name,
            "fale": missing,
            "pogresanTip": wrong,
            "nepracene": untracked,
            "podesavanja": base.configuration,
        }
    return None


async def check() -> dict:
    bases = expected()
    if not bases:
        return {"provereno": 0, "nalazi": [], "ok": True}
    semaphore = asyncio.Semaphore(3)
    async with notion.client() as api:

        async def inspect(base):
            async with semaphore:
                try:
                    async with asyncio.timeout(CHECK_TIMEOUT):
                        database = await api.databases.retrieve(database_id=base.database_id)
                        sources = database.get("data_sources", [])
                        if len(sources) != 1:
                            raise Unavailable(
                                "Baza mora imati tačno jedan izvor podataka (data source)."
                            )
                        source = await api.data_sources.retrieve(data_source_id=sources[0]["id"])
                        properties = source.get("properties")
                        if not isinstance(properties, dict):
                            raise Unavailable(
                                "Izvor nije vratio šemu kolona; provera nije potvrđena."
                            )
                        return compare(base, properties)
                except Exception as exc:
                    log.warning("Provera šeme %s nije uspela (%s).", base.name, type(exc).__name__)
                    return {"baza": base.name, "nedostupna": error_reason(exc)}

        findings = [
            finding
            for finding in await asyncio.gather(*(inspect(base) for base in bases))
            if finding
        ]
    log.info("Provera šema: %d baza, problema u %d.", len(bases), len(findings))
    return {"provereno": len(bases), "nalazi": findings, "ok": not findings}


def format_report(result: dict) -> str:
    if not result["provereno"]:
        return "Nijedna Notion baza nije podešena — nema šta da se proveri."
    if result["ok"]:
        return f"✅ Notion šeme su u redu (provereno baza: {result['provereno']})."
    sections = []
    for finding in result["nalazi"]:
        lines = [finding["baza"]]
        if finding.get("nedostupna"):
            lines.append("❌ Nedostupna: " + finding["nedostupna"])
        else:
            for missing in finding["fale"]:
                lines.append(
                    f"❌ Nema kolone „{missing['ime']}”."
                    + (" Koristi se u filteru nedeljnog cilja." if missing["uFilteru"] else "")
                )
            for wrong in finding["pogresanTip"]:
                lines.append(
                    f"⚠️ „{wrong['ime']}”: tip {wrong['nadjeno']}, očekuje se {wrong['ocekivano']}."
                )
            if finding["nepracene"]:
                lines.append(
                    "ℹ️ Checkbox kolone koje bot ne prati: " + ", ".join(finding["nepracene"])
                )
            lines.extend("⚠️ " + issue for issue in finding["podesavanja"])
        sections.append("\n".join(lines))
    return u_latinicu(
        "⚠️ Notion šeme se ne poklapaju sa podešavanjima:\n\n"
        + "\n\n".join(sections)
        + "\n\nUskladi nazive/tipove u Notion-u ili podešavanja CHECKLIST_POZITIVNE, CHECKLIST_IZBEGAVANJA i CHECKLIST_CILJNA_STAVKA. Provera ništa ne menja."
    )


def parts(text: str):
    buffer, units = [], 0
    for char in u_latinicu(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > 3900:
            yield "".join(buffer)
            buffer, units = [], 0
        buffer.append(char)
        units += width
    if buffer:
        yield "".join(buffer)


def fingerprint(result: dict) -> str:
    def canonical(value):
        if isinstance(value, dict):
            return {key: canonical(item) for key, item in value.items()}
        if isinstance(value, list):
            return sorted(
                (canonical(item) for item in value),
                key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
            )
        return value

    raw = json.dumps(
        canonical(result["nalazi"]), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def _save(conn, value):
    await conn.execute(
        "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=$2,updated_at=now()",
        STATE_KEY,
        value,
    )


async def startup(bot):
    try:
        if not expected():
            return
        async with db.pool().acquire() as conn:
            await conn.execute("SELECT pg_advisory_lock(19402026)")
            try:
                result = await check()
                if not result["provereno"]:
                    return result
                digest = fingerprint(result)
                previous = await conn.fetchval("SELECT value FROM kv_state WHERE key=$1", STATE_KEY)
                if previous and previous["fingerprint"] == digest:
                    return result
                message = (
                    format_report(result)
                    if not result["ok"]
                    else (
                        "✅ Notion šeme su ponovo usklađene."
                        if previous and not previous["ok"]
                        else None
                    )
                )
                state = {
                    "fingerprint": digest,
                    "ok": result["ok"],
                    "delivery": "attempted" if message else "silent",
                }
                # Upis pre slanja sprečava restart petlju i pri izgubljenom Telegram odgovoru.
                await _save(conn, state)
                if message:
                    sent = 0
                    try:
                        for part in parts(message):
                            await bot.send_message(settings().telegram_owner_chat_id, part)
                            sent += 1
                    except Exception as exc:
                        if not sent and isinstance(exc, (BadRequest, Forbidden, RetryAfter)):
                            if previous:
                                await _save(conn, previous)
                            else:
                                await conn.execute("DELETE FROM kv_state WHERE key=$1", STATE_KEY)
                        else:
                            await _save(conn, {**state, "delivery": "unknown"})
                        raise
                    await _save(conn, {**state, "delivery": "sent"})
                return result
            finally:
                await conn.execute("SELECT pg_advisory_unlock(19402026)")
    except Exception as exc:
        log.warning(
            "Provera šema pri startu nije završena (%s); bot nastavlja rad.", type(exc).__name__
        )
