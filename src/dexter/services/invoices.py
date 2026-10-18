"""Predlog je samo u memoriji; tek potvrda rezerviše broj i arhivira dokument."""

import asyncio
import hashlib
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dexter import db
from dexter.actions import ConfirmedAction, Document, PreparedAction
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import google, invoice_pdf, notion, notion_clients, notion_days

READ_REQUIRES = ["NOTION_API_KEY", "NOTION_INVOICES_DB_ID"]
ISSUER_FIELDS = {
    "name": "INVOICE_ISSUER_NAME",
    "address": "INVOICE_ISSUER_ADDRESS",
    "city": "INVOICE_ISSUER_CITY",
    "phone": "INVOICE_ISSUER_PHONE",
    "pib": "INVOICE_ISSUER_PIB",
    "mb": "INVOICE_ISSUER_MB",
    "account": "INVOICE_ISSUER_ACCOUNT",
    "bank": "INVOICE_ISSUER_BANK",
    "responsible_person": "INVOICE_RESPONSIBLE_PERSON",
}
CREATE_REQUIRES = [
    *READ_REQUIRES,
    "NOTION_CLIENTS_DB_ID",
    *google.REQUIRES,
    *ISSUER_FIELDS.values(),
]


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    opis: str = Field(min_length=1, max_length=2000)
    kolicina: Decimal = Field(Decimal(1), gt=0, le=1000000, decimal_places=3, allow_inf_nan=False)
    cena: Decimal = Field(ge=0, le=1000000000, decimal_places=2, allow_inf_nan=False)

    @field_validator("opis", mode="before")
    @classmethod
    def latin_description(cls, value):
        return u_latinicu(value) if isinstance(value, str) else value

    @field_validator("kolicina", "cena", mode="before")
    @classmethod
    def no_boolean(cls, value):
        if isinstance(value, bool):
            raise ValueError("Količina i cena moraju biti brojevi, ne true/false.")
        return value


class PreparedInvoice(BaseModel):
    model_config = ConfigDict(frozen=True)
    operation: str = Field(default_factory=lambda: str(uuid4()))
    broj: str
    customer: dict
    issuer: dict
    datumIzdavanja: str
    datumPrometa: str
    mesto: str
    stavke: tuple[Item, ...]
    comment: str
    vat_note: str
    source_id: str
    folder_id: str | None = None
    logo: bytes | None = Field(None, repr=False)
    pdf: bytes = Field(b"", repr=False)


def logo_path() -> Path:
    configured = settings().invoice_logo_path
    return Path(configured) if configured else invoice_pdf.FONTS.parent / "logo.png"


def configuration_error() -> str | None:
    cfg = settings()
    missing = [
        env for env in ISSUER_FIELDS.values() if not (getattr(cfg, env.lower()) or "").strip()
    ]
    if not logo_path().is_file() and not (cfg.invoice_issuer_brand or "").strip():
        missing.append("INVOICE_ISSUER_BRAND")
    return "Nedostaje: " + ", ".join(missing) if missing else None


def issuer_snapshot() -> tuple[dict, bytes | None]:
    if error := configuration_error():
        raise ValueError(error)
    cfg = settings()
    issuer = {
        key: u_latinicu(getattr(cfg, env.lower()).strip()) for key, env in ISSUER_FIELDS.items()
    }
    issuer["brand"] = u_latinicu((cfg.invoice_issuer_brand or "").strip())
    limits = {
        "pib": 32,
        "mb": 32,
        "phone": 50,
        "account": 64,
        "city": 100,
        "bank": 100,
        "responsible_person": 100,
    }
    for key, value in issuer.items():
        if len(value) > limits.get(key, 200):
            raise ValueError(f"Predugačak podatak izdavaoca: {key}.")
    if len(cfg.invoice_comment) > 1000 or len(cfg.invoice_vat_note) > 1000:
        raise ValueError("INVOICE_COMMENT i INVOICE_VAT_NOTE mogu imati najviše 1000 znakova.")
    path = logo_path()
    logo = path.read_bytes() if path.is_file() else None
    if logo and len(logo) > 5 * 1024 * 1024:
        raise ValueError("INVOICE_LOGO_PATH: logo je veći od 5 MB.")
    return issuer, logo


def parse_number(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d+)\s*-\s*(\d{4})", value.strip())
    return (int(match[1]), int(match[2])) if match else None


def save_prefix(source_id: str, year: int) -> str:
    return f"invoice:save:{UUID(source_id)}:{year}:"


async def next_number(api, source_id: str, year: int, conn=None) -> str:
    floor = settings().invoice_last_number
    parsed = parse_number(floor) if floor else None
    if floor and not parsed:
        raise ValueError("INVOICE_LAST_NUMBER mora biti NNN-GGGG; ispravi ga pre izrade fakture.")
    maximum = parsed[0] if parsed and parsed[1] == year else 0
    async for page in notion.query_pages(api, source_id):
        number = parse_number(
            notion.rich_text(page.get("properties", {}).get("Broj", {}).get("title", []))
        )
        if number and number[1] == year:
            maximum = max(maximum, number[0])
    # Potvrđen pokušaj sa neizvesnim ishodom ne sme kasnije ponovo dobiti isti broj.
    for state in await (conn or db.pool()).fetch(
        "SELECT value FROM kv_state WHERE key LIKE $1", save_prefix(source_id, year) + "%"
    ):
        number = parse_number(state["value"].get("broj", ""))
        if number and number[1] == year:
            maximum = max(maximum, number[0])
    return f"{maximum + 1:03}-{year:04}"


def filename(invoice: PreparedInvoice) -> str:
    client = re.sub(r"[/\\\x00-\x1f]", "_", invoice.customer["klijent"])[:100]
    return f"Racun {invoice.broj} - {client}.pdf"


def preview(invoice: PreparedInvoice) -> str:
    missing = [name for name in ("adresa", "grad", "pib", "mb") if not invoice.customer[name]]
    entries = [
        f"• {s.opis}: {s.kolicina} × {invoice_pdf.money(s.cena)} RSD" for s in invoice.stavke
    ]
    return (
        f"Faktura {invoice.broj}\nKlijent: {invoice.customer['naziv']}\n"
        f"Datum izdavanja: {invoice.datumIzdavanja}\nDatum prometa: {invoice.datumPrometa}\n"
        f"Mesto: {invoice.mesto}\n"
        + "\n".join(entries)
        + f"\nUkupno: {invoice_pdf.money(invoice_pdf.total(invoice.stavke))} RSD\n"
        + (
            f"⚠️ Klijentu fale podaci u Notion-u: {', '.join(missing)}. "
            "Dopuni bazu i pripremi ponovo ili potvrdi sa praznim poljima.\n"
            if missing
            else ""
        )
        + "Pogledaj PDF. Sačuvaj ga upisuje na Drive i u Notion; Odbaci ne zauzima broj."
    )


async def prepare(args) -> PreparedAction:
    issuer, logo = await asyncio.to_thread(issuer_snapshot)
    matches = await notion_clients.find(args.klijent)
    if len(matches) != 1:
        raise ValueError(
            "Ne nalazim tačno jednog klijenta u KLIJENTI bazi. Preciziraj naziv ili dopuni bazu."
        )
    if invoice_pdf.total(args.stavke) > Decimal("1000000000000"):
        raise ValueError("Ukupan iznos prelazi podržanu granicu od 1000000000000 RSD.")
    issued = notion_days.day(args.datumIzdavanja).isoformat()
    cfg = settings()
    async with notion.client() as api:
        source_id = await notion.database_source(
            api, cfg.notion_invoices_db_id, "NOTION_INVOICES_DB_ID"
        )
        number = await next_number(api, source_id, int(issued[:4]))
    invoice = PreparedInvoice(
        broj=number,
        customer=matches[0],
        issuer=issuer,
        logo=logo,
        datumIzdavanja=issued,
        datumPrometa=args.datumPrometa or issued,
        mesto=u_latinicu(args.mesto or issuer["city"]),
        stavke=tuple(args.stavke),
        comment=u_latinicu(cfg.invoice_comment),
        vat_note=u_latinicu(cfg.invoice_vat_note),
        source_id=source_id,
        folder_id=cfg.google_invoices_folder_id or None,
    )
    invoice = invoice.model_copy(
        update={"pdf": await asyncio.to_thread(invoice_pdf.render, invoice)}
    )
    return PreparedAction(invoice, Document(invoice.pdf, filename(invoice)))


async def record(conn, key: str, state: dict):
    await conn.execute(
        "INSERT INTO kv_state(key,value) VALUES($1,$2) ON CONFLICT(key) "
        "DO UPDATE SET value=$2, updated_at=now()",
        key,
        state,
    )


async def archive(invoice: PreparedInvoice) -> ConfirmedAction:
    year = int(invoice.datumIzdavanja[:4])
    key = save_prefix(invoice.source_id, year) + invoice.operation
    lock = int.from_bytes(
        hashlib.sha256(save_prefix(invoice.source_id, year).encode()).digest()[:8],
        "big",
        signed=True,
    )
    async with db.pool().acquire() as conn:
        # Session lock koristi isti konektor za trajne upise: rollback ne briše trag pokušaja.
        await conn.execute("SELECT pg_advisory_lock($1::bigint)", lock)
        try:
            previous = await conn.fetchval("SELECT value FROM kv_state WHERE key=$1", key)
            if previous:
                return ConfirmedAction(
                    previous["result"], successful=previous.get("status") == "gotovo"
                )
            async with notion.client() as api:
                number = await next_number(api, invoice.source_id, year, conn)
                changed = number != invoice.broj
                current = invoice.model_copy(update={"broj": number})
                if changed:
                    current = current.model_copy(
                        update={"pdf": await asyncio.to_thread(invoice_pdf.render, current)}
                    )
                state = {
                    "broj": number,
                    "status": "pokusano",
                    "result": {
                        "broj": number,
                        "status": "nepotvrđeno",
                        "poruka": "Čuvanje je pokušano; prvo proveri Drive i Notion, ne ponavljaj upis naslepo.",
                    },
                }
                await record(conn, key, state)
                try:
                    async with google.Drive() as drive:
                        generated = await drive.call(
                            "generateIds", count=1, space="drive", type="files"
                        )
                        file_id = generated["ids"][0]
                        state["drive_id"] = file_id
                        state["result"]["driveProvera"] = (
                            f"https://drive.google.com/file/d/{file_id}/view"
                        )
                        await record(conn, key, state)
                        try:
                            file = await drive.upload(
                                filename(current),
                                current.pdf,
                                google.PDF,
                                current.folder_id,
                                file_id,
                            )
                        except Exception:
                            # Unapred dobijen ID omogućava proveru posle izgubljenog upload odgovora.
                            meta = await drive.call(
                                "get",
                                fileId=file_id,
                                supportsAllDrives=True,
                                fields="id,name,webViewLink,md5Checksum,size",
                            )
                            if meta.get("md5Checksum") != hashlib.md5(
                                current.pdf
                            ).hexdigest() or str(meta.get("size")) != str(len(current.pdf)):
                                raise RuntimeError(
                                    "Drive upload nije potvrđen odgovarajućim PDF sadržajem."
                                ) from None
                            file = {
                                "id": file_id,
                                "name": meta.get("name", filename(current)),
                                "link": meta.get("webViewLink")
                                or f"https://drive.google.com/file/d/{file_id}/view",
                            }
                    state["result"] = {
                        "broj": number,
                        "status": "delimicno",
                        "drive": file,
                        "poruka": "PDF je na Drive-u; Notion upis još nije potvrđen. Proveri arhivu pre novog pokušaja.",
                    }
                    state["status"] = "drive"
                    await record(conn, key, state)
                    page = await api.pages.create(
                        parent={"type": "data_source_id", "data_source_id": current.source_id},
                        properties={
                            "Broj": {"title": notion.text_fragments(number)},
                            "Klijent": {"relation": [{"id": current.customer["id"]}]},
                            "Datum izdavanja": {"date": {"start": current.datumIzdavanja}},
                            "Datum prometa": {"date": {"start": current.datumPrometa}},
                            "Iznos": {"number": float(invoice_pdf.total(current.stavke))},
                            "Stavke": {
                                "rich_text": notion.text_fragments(
                                    "; ".join(s.opis for s in current.stavke)
                                )
                            },
                            "Status": {"select": {"name": "Nije plaćeno"}},
                            "Mesto": {"rich_text": notion.text_fragments(current.mesto)},
                            "PDF": {"url": file["link"]},
                        },
                    )
                except Exception as exc:
                    state["status"] = "nepotvrđeno"
                    state["error_type"] = type(exc).__name__
                    await record(conn, key, state)
                    return ConfirmedAction(state["result"], successful=False)
                result = {
                    "broj": number,
                    "iznos": str(invoice_pdf.total(current.stavke)),
                    "klijent": current.customer["klijent"],
                    "drive": file,
                    "notion": {"id": page["id"], "url": page.get("url")},
                    "brojPromenjen": changed,
                    "sacuvano": True,
                }
                await record(conn, key, {"broj": number, "status": "gotovo", "result": result})
                return ConfirmedAction(
                    result, Document(current.pdf, filename(current)) if changed else None
                )
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1::bigint)", lock)


async def list_invoices(status=None, limit=25) -> list[dict]:
    async with notion.client() as api:
        source_id = await notion.database_source(
            api, settings().notion_invoices_db_id, "NOTION_INVOICES_DB_ID"
        )
        filter_ = {"property": "Status", "select": {"equals": status}} if status else None
        rows = []
        async for page in notion.query_pages(
            api,
            source_id,
            filter_,
            limit,
            sorts=[{"property": "Datum izdavanja", "direction": "descending"}],
        ):
            props = page.get("properties", {})
            rows.append(
                {
                    "id": page["id"],
                    "url": page.get("url"),
                    "broj": u_latinicu(notion.rich_text(props.get("Broj", {}).get("title", []))),
                    "iznos": props.get("Iznos", {}).get("number"),
                    "status": u_latinicu((props.get("Status", {}).get("select") or {}).get("name")),
                    "datumIzdavanja": (props.get("Datum izdavanja", {}).get("date") or {}).get(
                        "start"
                    ),
                    "stavke": u_latinicu(
                        notion.rich_text(props.get("Stavke", {}).get("rich_text", []))
                    ),
                    "pdf": props.get("PDF", {}).get("url"),
                }
            )
        return rows
