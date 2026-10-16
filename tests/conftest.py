import io
import os
import re
import threading
from datetime import UTC, datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

import pytest

# Testovi ne smeju da zavise od pravog .env-a ni od mreže.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("TELEGRAM_OWNER_CHAT_ID", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")


@pytest.fixture
def pdf_bytes():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 20 100 Td (Dokument za proveru indeksiranja PDF fajlova i pretrage znanja.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def make_mail():
    def make(
        subject="Projekat",
        text="Dogovor o projektu.",
        message_id="<test@example.com>",
        when="Thu, 15 Oct 2026 10:00:00 +0200",
        html=None,
        attachments=(),
    ):
        message = EmailMessage()
        message["From"] = "Marko Petrović <marko@example.com>"
        message["To"] = "vlasnik@example.com"
        message["Subject"] = subject
        message["Date"] = when
        if message_id:
            message["Message-ID"] = message_id
        if html:
            message.set_content(html, subtype="html")
        else:
            message.set_content(text)
        for name, payload, mime in attachments:
            main, sub = mime.split("/", 1)
            message.add_attachment(payload, maintype=main, subtype=sub, filename=name)
        return message.as_bytes()

    return make


@pytest.fixture
def imap_server(monkeypatch):
    from imap_tools.imap_utf7 import utf7_decode, utf7_encode

    from apu import config
    from apu.services import mail
    from apu.sources import mail as source

    for name in mail.REQUIRES:
        monkeypatch.setenv(name, "test")
    config.settings.cache_clear()
    main_thread = threading.get_ident()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 15, 10, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(source, "datetime", FrozenDatetime)

    class Server:
        state = "NONAUTH"
        selected = None
        fail_folder = None
        closed = False

        def __init__(self):
            self.messages = {"INBOX": [], "Poslato": []}
            self.flags = {"INBOX": "\\Inbox", "Poslato": "\\Sent"}
            self.calls = []

        def record(self, command, *args):
            assert threading.get_ident() != main_thread
            self.calls.append((command, *args))

        def _quote(self, text):
            return f'"{text}"'

        def _simple_command(self, command, *args):
            self.record(command, *args)
            assert command in {"LOGIN", "LIST"}
            return "OK", []

        def _untagged_response(self, typ, data, command):
            return "OK", [
                f'({self.flags.get(name, "")}) "/" "'.encode() + utf7_encode(name) + b'"'
                for name in self.messages
            ]

        def select(self, name, readonly=False):
            self.record("SELECT", name, readonly)
            assert readonly is True
            self.selected = utf7_decode(name).strip('"')
            if self.selected == self.fail_folder:
                raise RuntimeError("IMAP prekid foldera")
            return "OK", [str(len(self.messages[self.selected])).encode()]

        def uid(self, command, *args):
            self.record(command.upper(), *args)
            messages = self.messages[self.selected]
            if command.upper() == "SEARCH":
                criteria = args[-1].decode()
                match = re.search(r"SINCE (\d{1,2}-[A-Za-z]{3}-\d{4})", criteria)
                assert match and "UNSEEN" not in criteria
                since = datetime.strptime(match[1], "%d-%b-%Y").date()
                ids = [
                    str(i)
                    for i, raw in enumerate(messages, 1)
                    if parsedate_to_datetime(message_from_bytes(raw)["Date"]).date() >= since
                ]
                return "OK", [" ".join(ids).encode()]
            assert command.upper() == "FETCH" and "BODY.PEEK[]" in args[1]
            uid = int(args[0])
            flags = "\\Seen" if uid % 2 else ""
            return "OK", [(f"1 (UID {uid} FLAGS ({flags}))".encode(), messages[uid - 1]), b")"]

        def logout(self):
            self.record("LOGOUT")
            self.closed = True
            return "BYE", [b"logout"]

    server = Server()
    monkeypatch.setattr(mail.MailBox, "_get_mailbox_client", lambda self: server)
    yield server
    config.settings.cache_clear()
