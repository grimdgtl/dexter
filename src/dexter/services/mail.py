"""Mejl: IMAP PEEK za čitanje, APPEND za draft i Resend/SMTP za potvrđeno slanje."""

import asyncio
import calendar
import csv
import hashlib
import re
import smtplib
import ssl
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage, Message
from email.utils import formatdate, make_msgid
from html.parser import HTMLParser
from pathlib import Path

import httpx
from imap_tools import AND, MailAttachment, MailBox, MailMessage
from imap_tools.folder import FolderInfo

from dexter.config import Settings, settings
from dexter.pismo import u_latinicu
from dexter.rag import office
from dexter.rag.ingest import pdf_text, read_pdf

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
REQUIRES = ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"]
SENT_NAMES = {"sent", "sent mail", "sent messages", "sent items", "poslato", "poslate poruke"}
SEND_REQUIRES = [
    ["RESEND_API_KEY", "MAIL_FROM_ADDRESS"],
    ["RESEND_API_KEY", "SMTP_USER"],
    ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
]


def configured() -> bool:
    return all(getattr(settings(), name.lower()) for name in REQUIRES)


def months_ago(today: date, months: int) -> date:
    if months < 1:
        raise ValueError("MAIL_INDEX_MONTHS mora biti pozitivan.")
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    month += 1
    if year < 1:
        raise ValueError("MAIL_INDEX_MONTHS daje datum van podržanog opsega.")
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def index_folders(folders: list[FolderInfo], cfg: Settings) -> list[str]:
    excluded = {
        name.strip().casefold()
        for name in next(csv.reader([cfg.mail_index_exclude]))
        if name.strip()
    }
    selectable = [f for f in folders if "\\noselect" not in {s.casefold() for s in f.flags}]
    names = {f.name.casefold(): f.name for f in selectable}
    result = []
    if "inbox" not in excluded:
        if "inbox" not in names:
            raise RuntimeError("IMAP nije vratio INBOX; postojeći indeks je sačuvan.")
        result.append(names["inbox"])
    if cfg.mail_index_sent_folder:
        key = cfg.mail_index_sent_folder.casefold()
        if key in excluded:
            sent = []
        elif key not in names:
            raise RuntimeError("MAIL_INDEX_SENT_FOLDER ne odgovara dostupnom folderu.")
        else:
            sent = [names[key]]
    else:
        sent = [f.name for f in selectable if "\\sent" in {s.casefold() for s in f.flags}]
        if not sent:
            sent = [
                f.name
                for f in selectable
                if f.name.casefold().rsplit(f.delim or "/", 1)[-1] in SENT_NAMES
            ]
        if not sent:
            raise RuntimeError("Sent folder nije pronađen. Podesi MAIL_INDEX_SENT_FOLDER.")
    return list(dict.fromkeys(result + [name for name in sent if name.casefold() not in excluded]))


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    parser.close()
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


@dataclass
class MailDocument:
    id: str
    title: str
    text: str
    skipped_attachments: int = 0
    modified_at: datetime | None = None
    pdf_attachments: list[tuple[str, bytes]] = field(default_factory=list, repr=False)


def message_id(message: MailMessage) -> str:
    value = str(message.headers.get("message-id", ("",))[0]).strip()
    # Poruke bez Message-ID ostaju prepoznatljive i posle premeštanja između foldera.
    return value or "sha256:" + hashlib.sha256(message.obj.as_bytes()).hexdigest()


def _parts(part: Message):
    attached = (
        part.get_content_disposition() == "attachment"
        or part.get_filename() is not None
        or part.get("Content-ID") is not None
        or part.get_content_maintype() == "message"
    )
    if attached:
        # I prilog bez imena je prilog; telo ugnježdenog .eml-a ne sme da zaobiđe limit.
        yield True, part
    elif part.get_content_maintype() == "multipart":
        for child in part.get_payload():
            yield from _parts(child)
    else:
        yield False, part


def _decode_text(part: Message) -> str:
    data = part.get_payload(decode=True) or b""
    try:
        return data.decode(part.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def document(message: MailMessage, *, defer_pdf: bool = False) -> MailDocument:
    sender = message.from_values
    sender_text = f"{sender.name} <{sender.email}>" if sender and sender.name else message.from_
    when = message.date.isoformat() if message.date_str else "(bez datuma)"
    subject = message.subject or "(bez naslova)"
    title = u_latinicu(f"{subject} — {sender_text} — {when}")
    parts = list(_parts(message.obj))
    plain = [
        _decode_text(part)
        for attached, part in parts
        if not attached and part.get_content_type() == "text/plain"
    ]
    html = [
        _decode_text(part)
        for attached, part in parts
        if not attached and part.get_content_type() == "text/html"
    ]
    lines = [
        f"Naslov: {subject}",
        f"Pošiljalac: {sender_text}",
        f"Primaoci: {', '.join(message.to)}",
        f"CC: {', '.join(message.cc)}",
        f"Datum: {when}",
        "\n".join(plain).strip() or html_text("\n".join(html)),
    ]
    skipped = 0
    pdf_attachments = []
    for attached, part in parts:
        if not attached:
            continue
        attachment = MailAttachment(part)
        if attachment.size > MAX_ATTACHMENT_BYTES:
            skipped += 1
            continue
        mime = attachment.content_type
        suffix = Path(attachment.filename).suffix.lower()
        if mime == "application/pdf" or suffix == ".pdf":
            if defer_pdf:
                pdf_attachments.append((attachment.filename, attachment.payload))
                continue
            text = pdf_text(attachment.payload)
        elif suffix in office.SUFFIXES or mime in office.MIMES:
            name = (
                attachment.filename if suffix in office.SUFFIXES else "prilog" + office.MIMES[mime]
            )
            text = office.text(name, attachment.payload)
        elif (
            mime.startswith("text/")
            or mime == "application/json"
            or suffix in {".txt", ".md", ".csv"}
        ):
            text = _decode_text(part)
            if mime == "text/html" or suffix in {".html", ".htm"}:
                text = html_text(text)
        else:
            skipped += 1
            continue
        if text.strip():
            lines += [f"Prilog: {attachment.filename}", text]
    return MailDocument(
        f"mail:{message_id(message)}",
        title,
        u_latinicu("\n\n".join(lines)),
        skipped,
        modified_at=message.date if message.date_str and message.date.tzinfo else None,
        pdf_attachments=pdf_attachments,
    )


def _documents(cfg: Settings, since: date) -> Iterator[MailDocument]:
    seen = set()
    with MailBox(cfg.imap_host, port=cfg.imap_port, timeout=30) as box:
        # login inače odmah bira INBOX za pisanje, zato ga biramo posebno kao read-only.
        box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
        for folder in index_folders(box.folder.list(), cfg):
            box.folder.set(folder, readonly=True)
            for message in box.fetch(AND(date_gte=since), mark_seen=False, bulk=False):
                key = message_id(message)
                if key in seen:
                    continue
                seen.add(key)
                yield document(message, defer_pdf=True)


async def _in_thread(fn, *args):
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Sačekaj aktivni IMAP poziv pre logout-a nad istom konekcijom.
        try:
            await task
        except Exception:
            pass
        raise


async def documents(since: date) -> AsyncIterator[MailDocument]:
    if not configured():
        raise RuntimeError("Mejl indeks traži IMAP_HOST, IMAP_USER i IMAP_PASSWORD.")
    iterator = _documents(settings(), since)
    try:
        while (item := await _in_thread(next, iterator, None)) is not None:
            for name, data in item.pdf_attachments:
                text = await read_pdf(data)
                if text.strip():
                    item.text += u_latinicu(f"\n\nPrilog: {name}\n\n{text}")
            item.pdf_attachments.clear()
            yield item
    finally:
        await _in_thread(iterator.close)


def header_value(value: str, label: str) -> str:
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{label} ne sme sadržati prelom reda ili kontrolne znakove.")
    return value.strip()


def addresses(value: str, label: str = "To") -> list[str]:
    value = header_value(value, label)
    msg = EmailMessage(policy=policy.SMTP)
    try:
        msg["To"] = value
        parsed = msg["To"]
        result = list(dict.fromkeys(a.addr_spec for a in parsed.addresses))
        if (
            parsed.defects
            or not result
            or any(
                not a.username or not a.domain or not a.addr_spec.isascii()
                for a in parsed.addresses
            )
        ):
            raise ValueError
    except (ValueError, IndexError) as exc:
        raise ValueError(f"{label} mora sadržati ispravne email adrese, odvojene zarezom.") from exc
    if len(result) > 50:
        raise ValueError(f"{label} može imati najviše 50 primalaca.")
    return result


def sender(*, draft: bool = False) -> str:
    cfg = settings()
    value = cfg.mail_from_address or cfg.smtp_user or (cfg.imap_user if draft else None)
    if not value:
        raise ValueError("Nedostaje MAIL_FROM_ADDRESS (ili SMTP_USER).")
    parsed = addresses(value, "Pošiljalac")
    if len(parsed) != 1:
        raise ValueError("Pošiljalac mora biti jedna email adresa.")
    return str(
        Address(
            display_name=u_latinicu(header_value(cfg.mail_from_name, "MAIL_FROM_NAME")),
            addr_spec=parsed[0],
        )
    )


def body_text(message: MailMessage) -> str:
    # Tekst priloženog .eml-a ili .txt-a ne predstavlja telo osnovne poruke.
    parts = [(attached, part) for attached, part in _parts(message.obj)]
    plain = "\n".join(
        _decode_text(part)
        for attached, part in parts
        if not attached and part.get_content_type() == "text/plain"
    ).strip()
    html = "\n".join(
        _decode_text(part)
        for attached, part in parts
        if not attached and part.get_content_type() == "text/html"
    )
    return u_latinicu(plain or html_text(html))


def summary(message: MailMessage, folder: str) -> dict:
    person = message.from_values
    # Primljena pošta može imati neispravnu From adresu; čitanje je ne koristi za slanje.
    sender_text = (
        (
            f"{person.name} <{person.email}>"
            if person.name and person.email
            else person.name or person.email
        )
        if person
        else ""
    )
    return {
        "uid": int(message.uid),
        "folder": folder,
        "from": u_latinicu(sender_text),
        "to": ", ".join(message.to),
        "subject": u_latinicu(message.subject or "(bez naslova)"),
        "date": message.date.isoformat() if message.date_str else None,
        "procitan": "\\Seen" in message.flags,
        "prilozi": [u_latinicu(a.filename) for a in message.attachments if a.filename],
        "preview": body_text(message)[:500],
    }


def _mailbox():
    if not configured():
        raise RuntimeError("Nedostaje IMAP_HOST, IMAP_USER ili IMAP_PASSWORD.")
    cfg = settings()
    return MailBox(
        cfg.imap_host, port=cfg.imap_port, timeout=30, ssl_context=ssl.create_default_context()
    )


async def search_messages(*, folder="INBOX", limit=20, **filters) -> list[dict]:
    query = {}
    for source, target in (
        ("from_", "from_"),
        ("to", "to"),
        ("subject", "subject"),
        ("text", "body"),
        ("since", "date_gte"),
        ("before", "date_lt"),
    ):
        if filters.get(source) is not None:
            query[target] = filters[source]
    if filters.get("unread") is not None:
        query["seen"] = not filters["unread"]
    criteria = AND(**query) if query else "ALL"

    def read():
        cfg = settings()
        with _mailbox() as box:
            box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
            box.folder.set(header_value(folder, "Folder"), readonly=True)
            return [
                summary(m, folder)
                for m in box.fetch(
                    criteria, charset="UTF-8", mark_seen=False, reverse=True, limit=limit
                )
            ]

    return await _in_thread(read)


async def read_message(uid: int, folder: str = "INBOX") -> dict:
    def read():
        cfg = settings()
        with _mailbox() as box:
            box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
            box.folder.set(header_value(folder, "Folder"), readonly=True)
            message = next(box.fetch(uid_list=[str(uid)], mark_seen=False, limit=1), None)
            if message is None:
                raise ValueError(f'Ne nalazim poruku sa uid {uid} u folderu "{folder}".')
            result = summary(message, folder)
            text = body_text(message)
            result.pop("preview")
            return {
                **result,
                "cc": ", ".join(message.cc),
                "messageId": str(message.headers.get("message-id", ("",))[0]).strip() or None,
                "prilozi": [
                    {
                        "naziv": u_latinicu(a.filename or "(bez imena)"),
                        "tip": a.content_type,
                        "velicinaKb": round(a.size / 1024) if a.size else None,
                    }
                    for a in message.attachments
                ],
                "telo": text[:20000],
                "skraceno": len(text) > 20000,
            }

    return await _in_thread(read)


async def list_folders() -> list[dict]:
    def read():
        cfg = settings()
        with _mailbox() as box:
            box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
            return [
                {
                    "putanja": f.name,
                    "naziv": u_latinicu(f.name.rsplit(f.delim or "/", 1)[-1]),
                    "namena": next(
                        (
                            flag
                            for flag in f.flags
                            if flag.lower()
                            in {"\\inbox", "\\sent", "\\drafts", "\\trash", "\\junk", "\\archive"}
                        ),
                        None,
                    ),
                }
                for f in box.folder.list()
                if "\\noselect" not in {s.casefold() for s in f.flags}
            ]

    return await _in_thread(read)


def build_message(
    from_: str, to: str, subject: str, body: str, cc=None, inReplyTo=None
) -> EmailMessage:
    message = EmailMessage(policy=policy.SMTP)
    header_value(from_, "Pošiljalac")
    message["From"] = from_
    message["To"] = ", ".join(addresses(to))
    if cc:
        message["Cc"] = ", ".join(addresses(cc, "CC"))
    message["Subject"] = u_latinicu(header_value(subject, "Naslov"))
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=addresses(from_, "Pošiljalac")[0].split("@", 1)[1])
    if inReplyTo:
        value = header_value(inReplyTo, "In-Reply-To")
        if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", value):
            raise ValueError("In-Reply-To mora biti Message-ID iz mail_read, u obliku <id@domen>.")
        message["In-Reply-To"] = value
        message["References"] = value
    message.set_content(u_latinicu(body))
    return message


async def save_draft(to: str, subject: str, body: str, cc=None) -> dict:
    message = build_message(sender(draft=True), to, subject, body, cc)

    def save():
        cfg = settings()
        with _mailbox() as box:
            box.login(cfg.imap_user, cfg.imap_password, initial_folder=None)
            folders = [
                f for f in box.folder.list() if "\\noselect" not in {s.casefold() for s in f.flags}
            ]
            draft = next(
                (f.name for f in folders if "\\drafts" in {s.casefold() for s in f.flags}), None
            )
            draft = draft or next(
                (
                    f.name
                    for f in folders
                    if f.name.casefold()
                    in {"[gmail]/drafts", "drafts", "inbox.drafts", "inbox/drafts"}
                ),
                None,
            )
            if not draft:
                raise ValueError("Drafts folder nije pronađen na IMAP nalogu.")
            box.append(message.as_bytes(), folder=draft, flag_set=["\\Draft"])
            return {"saved": True, "mailbox": draft, "poslato": False}

    return await _in_thread(save)


async def send_mail(from_: str, to: str, subject: str, body: str, cc=None, inReplyTo=None) -> dict:
    cfg = settings()
    message = build_message(from_, to, subject, body, cc, inReplyTo)
    recipients = list(dict.fromkeys(addresses(to) + (addresses(cc, "CC") if cc else [])))
    if cfg.resend_api_key:
        payload = {
            "from": from_,
            "to": addresses(to),
            "subject": str(message["Subject"]),
            "text": u_latinicu(body),
        }
        if cc:
            payload["cc"] = addresses(cc, "CC")
        if inReplyTo:
            payload["headers"] = {"In-Reply-To": inReplyTo, "References": inReplyTo}
        try:
            async with httpx.AsyncClient(timeout=20) as api:
                response = await api.post(
                    "https://api.resend.com/emails",
                    json=payload,
                    headers={"Authorization": f"Bearer {cfg.resend_api_key}"},
                )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Ishod slanja preko Resend-a nije potvrđen. Proveri Resend pre ponavljanja."
            ) from exc
        if not response.is_success:
            raise RuntimeError(
                f"Resend greška {response.status_code}; slanje nije potvrđeno. SMTP nije pozvan."
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Resend odgovor je neispravan; proveri ishod pre ponavljanja."
            ) from exc
        if not result.get("id"):
            raise RuntimeError("Resend nije vratio ID; proveri ishod pre ponavljanja.")
        return {"messageId": result["id"], "provider": "resend", "poslato": True}

    def send():
        if not all((cfg.smtp_host, cfg.smtp_user, cfg.smtp_password)):
            raise ValueError("Nedostaje SMTP_HOST, SMTP_USER ili SMTP_PASSWORD.")
        context = ssl.create_default_context()
        smtp = (
            smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=20, context=context)
            if cfg.smtp_secure
            else smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=20)
        )
        with smtp:
            if not cfg.smtp_secure:
                smtp.starttls(context=context)
            smtp.login(cfg.smtp_user, cfg.smtp_password)
            rejected = smtp.send_message(
                message, from_addr=addresses(from_, "Pošiljalac")[0], to_addrs=recipients
            )
        return {
            "messageId": str(message["Message-ID"]),
            "provider": "smtp",
            "poslato": True,
            "accepted": [r for r in recipients if r not in rejected],
            "rejected": list(rejected),
            "napomena": "Neki primaoci su odbijeni; ne ponavljaj ceo mejl." if rejected else None,
        }

    return await _in_thread(send)
