"""IMAP čitanje za indeks: TLS, read-only folderi i BODY.PEEK bez promene oznaka."""

import asyncio
import calendar
import csv
import hashlib
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path

from imap_tools import AND, MailAttachment, MailBox, MailMessage
from imap_tools.folder import FolderInfo

from apu.config import Settings, settings
from apu.pismo import u_latinicu
from apu.rag.ingest import pdf_text

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
REQUIRES = ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"]
SENT_NAMES = {"sent", "sent mail", "sent messages", "sent items", "poslato", "poslate poruke"}


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


def document(message: MailMessage) -> MailDocument:
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
            text = pdf_text(attachment.payload)
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
                yield document(message)


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
            yield item
    finally:
        await _in_thread(iterator.close)
