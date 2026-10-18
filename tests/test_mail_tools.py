"""Pravi MIME/IMAP kod uz lažni protokol; Resend je uvek respx mock."""

import asyncio
import json
import smtplib
import threading
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from dexter import telegram_bot
from dexter.agent.loop import AgentResult
from dexter.config import settings
from dexter.services import mail
from dexter.tools import registry
from dexter.tools.mail import DraftArgs, SearchArgs

ARGS = {"to": "primalac@example.com", "subject": "Проба", "body": "Први ред.\nДруги ред."}


@pytest.fixture
def sending(monkeypatch):
    cfg = settings()
    for key in ("resend_api_key", "smtp_host", "smtp_user", "smtp_password"):
        monkeypatch.setattr(cfg, key, None)
    monkeypatch.setattr(cfg, "mail_from_address", "bot@example.com")
    monkeypatch.setattr(cfg, "mail_from_name", "Никола")
    monkeypatch.setattr(cfg, "resend_api_key", "test-resend")
    monkeypatch.setattr(cfg, "smtp_port", 465)
    monkeypatch.setattr(cfg, "smtp_secure", True)
    return cfg


async def test_search_unread_seen_all_and_combined_filters(imap_server, make_mail):
    imap_server.messages["INBOX"] = [
        make_mail(subject="Stara ponuda", when="Wed, 14 Oct 2026 10:00:00 +0200"),
        make_mail(subject="Понуда", text="Priprema ponude"),
        make_mail(subject="Pročitana ponuda"),
        make_mail(subject="Posle granice", when="Fri, 16 Oct 2026 10:00:00 +0200"),
    ]
    result = await registry.execute(
        "mail_search",
        {
            "from": "marko@example.com",
            "to": "vlasnik@example.com",
            "subject": "Понуда",
            "text": "Priprema",
            "since": "2026-10-15",
            "before": "2026-10-16",
            "unread": True,
        },
    )
    assert not result.is_error
    rows = json.loads(result.text)
    assert len(rows) == 1 and rows[0]["uid"] == 2 and rows[0]["subject"] == "Ponuda"
    assert rows[0]["folder"] == "INBOX" and not rows[0]["procitan"]
    criteria = [c[-1].decode() for c in imap_server.calls if c[0] == "SEARCH"][-1]
    assert 'BODY "Priprema"' in criteria and 'SUBJECT "Понуда"' in criteria
    assert "SINCE 15-Oct-2026" in criteria and "BEFORE 16-Oct-2026" in criteria
    result = await registry.execute("mail_search", {"unread": False})
    assert [r["uid"] for r in json.loads(result.text)] == [3, 1]
    result = await registry.execute("mail_search", {"limit": 2})
    assert [r["uid"] for r in json.loads(result.text)] == [4, 3]
    result = await registry.execute("mail_list_unread", {"limit": 1})
    assert [r["uid"] for r in json.loads(result.text)] == [4]
    assert all(c[2] for c in imap_server.calls if c[0] == "SELECT")
    assert all("BODY.PEEK[]" in c[2] for c in imap_server.calls if c[0] == "FETCH")
    assert not any(c[0] in {"STORE", "EXPUNGE"} for c in imap_server.calls)
    assert imap_server.closed


async def test_read_keeps_body_and_attachment_metadata(imap_server, make_mail):
    imap_server.messages["Poslato"] = [
        make_mail(
            text="Почетак " + "a" * 15000 + " крај",
            attachments=[("рачун.pdf", b"PDF", "application/pdf")],
        )
    ]
    result = await registry.execute("mail_read", {"uid": 1, "folder": "Poslato"})
    row = json.loads(result.text)
    assert not result.is_error and len(result.text) > registry.MAX_RESULT_CHARS
    assert row["telo"].endswith("kraj") and not row["skraceno"]
    assert row["messageId"] == "<test@example.com>" and row["procitan"]
    assert row["prilozi"][0]["naziv"] == "račun.pdf"
    assert row["prilozi"][0]["tip"] == "application/pdf"
    assert imap_server.closed


async def test_read_html_fallback_truncation_and_missing_uid(imap_server, make_mail):
    imap_server.messages["INBOX"] = [
        make_mail(html="<p>Налог</p><script>skriven</script>"),
        make_mail(text="Z" * 21000),
    ]
    row = await mail.read_message(1)
    assert row["telo"] == "Nalog"
    row = await mail.read_message(2)
    assert row["skraceno"] and len(row["telo"]) == 20000
    result = await registry.execute("mail_read", {"uid": 999})
    assert result.is_error and "Ne nalazim" in result.text
    assert imap_server.closed


async def test_read_tolerates_malformed_sender_and_missing_date(imap_server):
    imap_server.messages["INBOX"] = [
        b"From: automated-system\r\nSubject: Bez datuma\r\n\r\nTekst poruke."
    ]
    row = await mail.read_message(1)
    assert row["from"] == "automated-system" and row["date"] is None
    assert row["telo"] == "Tekst poruke." and row["messageId"] is None


async def test_folder_paths_are_exact_and_noselect_is_hidden(imap_server):
    imap_server.messages.update({"Lične poruke": [], "Roditelj": []})
    imap_server.flags.update({"Lične poruke": "\\Drafts", "Roditelj": "\\Noselect"})
    result = await registry.execute("mail_folders", {})
    rows = json.loads(result.text)
    assert "Roditelj" not in {r["putanja"] for r in rows}
    assert next(r for r in rows if r["putanja"] == "Lične poruke")["namena"] == "\\Drafts"
    assert imap_server.closed


@pytest.mark.parametrize(
    "name,args",
    [
        ("mail_list_unread", {}),
        ("mail_search", {}),
        ("mail_read", {"uid": 1}),
        ("mail_folders", {}),
        ("mail_save_draft", ARGS),
    ],
)
async def test_imap_errors_close_connection(imap_server, sending, name, args):
    imap_server.fail_login = True
    result = await registry.execute(name, args)
    assert result.is_error and "prijava" in result.text
    assert imap_server.closed


@pytest.mark.parametrize(
    "folder,flag", [("Nacrti", "\\Drafts"), ("[Gmail]/Drafts", ""), ("Drafts", "")]
)
async def test_draft_is_mime_append_without_sending(imap_server, sending, folder, flag):
    imap_server.messages[folder] = []
    imap_server.flags[folder] = flag
    result = await registry.execute("mail_save_draft", {**ARGS, "cc": "kopija@example.com"})
    assert not result.is_error and result.pending is None
    assert json.loads(result.text) == {"saved": True, "mailbox": folder, "poslato": False}
    name, flags, raw = imap_server.appended[0]
    assert name == folder and "\\Draft" in flags
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert str(msg["From"]) == "Nikola <bot@example.com>"
    assert str(msg["Subject"]) == "Proba" and str(msg["Cc"]) == "kopija@example.com"
    assert msg.get_content().splitlines() == ["Prvi red.", "Drugi red."]
    assert not msg["Bcc"] and imap_server.closed


async def test_missing_drafts_folder_does_not_write_elsewhere(imap_server, sending):
    result = await registry.execute("mail_save_draft", ARGS)
    assert result.is_error and "Drafts folder" in result.text
    assert not imap_server.appended and imap_server.closed


async def test_resend_only_sends_after_confirmation_once(sending, respx_mock):
    route = respx_mock.post("https://api.resend.com/emails").respond(200, json={"id": "mail-id"})
    args = {
        **ARGS,
        "to": "Ana <ana@example.com>, druga@example.com",
        "cc": "kopija@example.com",
        "inReplyTo": "<original@example.com>",
    }
    out = await registry.execute("mail_send", args)
    assert not out.is_error and out.pending and not route.called
    token, preview = out.pending
    assert "Od: Nikola <bot@example.com>" in preview
    assert "ana@example.com, druga@example.com" in preview and "kopija@example.com" in preview
    assert "Prvi red.\nDrugi red." in preview and "<original@example.com>" in preview
    assert registry.pending_confirm_label(token) == "📨 Pošalji"
    results = await asyncio.gather(registry.confirm(token), registry.confirm(token))
    assert any("mail-id" in r for r in results) and any("istekla" in r for r in results)
    assert route.call_count == 1
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "from": "Nikola <bot@example.com>",
        "to": ["ana@example.com", "druga@example.com"],
        "cc": ["kopija@example.com"],
        "subject": "Proba",
        "text": "Prvi red.\nDrugi red.",
        "headers": {
            "In-Reply-To": "<original@example.com>",
            "References": "<original@example.com>",
        },
    }
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-resend"
    assert "sender" not in registry._TOOLS["mail_send"].schema()["input_schema"]["properties"]


async def test_cancel_and_expiration_never_send(sending, respx_mock):
    route = respx_mock.post("https://api.resend.com/emails")
    first = await registry.execute("mail_send", ARGS)
    registry.cancel(first.pending[0])
    assert "istekla" in await registry.confirm(first.pending[0])
    second = await registry.execute("mail_send", ARGS)
    registry._PENDING[second.pending[0]].created -= registry.CONFIRM_TTL_S + 1
    assert "istekla" in await registry.confirm(second.pending[0])
    assert not route.called


@pytest.mark.parametrize("failure", ["forbidden", "timeout", "invalid_json", "no_id"])
async def test_resend_failure_never_falls_back_to_smtp(sending, respx_mock, monkeypatch, failure):
    sending.smtp_host, sending.smtp_user, sending.smtp_password = (
        "smtp.test",
        "u@example.com",
        "test",
    )

    def forbidden_smtp(*a, **kw):
        pytest.fail("SMTP ne sme biti pozvan posle Resend-a")

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", forbidden_smtp)
    route = respx_mock.post("https://api.resend.com/emails")
    if failure == "forbidden":
        route.respond(403, json={"message": "Pristup odbijen"})
    elif failure == "timeout":
        route.mock(side_effect=httpx.ReadTimeout("timeout"))
    elif failure == "invalid_json":
        route.respond(200, text="nije-json")
    else:
        route.respond(200, json={})
    out = await registry.execute("mail_send", ARGS)
    result = await registry.confirm(out.pending[0])
    assert result.startswith("Greška:") and route.call_count == 1
    assert "istekla" in await registry.confirm(out.pending[0])


@pytest.mark.parametrize("secure,reject", [(True, False), (False, False), (True, True)])
async def test_smtp_tls_threading_headers_and_partial_rejection(
    sending, monkeypatch, secure, reject
):
    sending.resend_api_key = None
    sending.smtp_host, sending.smtp_user, sending.smtp_password = (
        "smtp.test",
        "bot@example.com",
        "test",
    )
    sending.smtp_secure = secure
    main_thread, calls = threading.get_ident(), []

    class SMTP:
        def __init__(self, host, port, **kwargs):
            assert threading.get_ident() != main_thread
            assert host == "smtp.test" and port == 465 and kwargs["timeout"] == 20
            assert ("context" in kwargs) == secure

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("zatvoren")

        def starttls(self, **kwargs):
            assert kwargs["context"].check_hostname
            calls.append("tls")

        def login(self, user, password):
            assert secure or calls == ["tls"]
            assert user == "bot@example.com" and password == "test"

        def send_message(self, message, *, from_addr, to_addrs):
            assert from_addr == "bot@example.com" and to_addrs == [
                "primalac@example.com",
                "kopija@example.com",
            ]
            assert message["In-Reply-To"] == message["References"] == "<original@example.com>"
            assert message["Message-ID"] and message["Date"]
            assert message.get_content().splitlines() == ["Prvi red.", "Drugi red."]
            calls.append("slanje")
            return {"kopija@example.com": (550, b"odbijen")} if reject else {}

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL" if secure else "SMTP", SMTP)
    out = await registry.execute(
        "mail_send", {**ARGS, "cc": "kopija@example.com", "inReplyTo": "<original@example.com>"}
    )
    assert "slanje" not in calls
    result = json.loads(await registry.confirm(out.pending[0]))
    assert result["provider"] == "smtp" and result["poslato"]
    assert result["rejected"] == (["kopija@example.com"] if reject else [])
    assert result["accepted"] == (
        ["primalac@example.com"] if reject else ["primalac@example.com", "kopija@example.com"]
    )
    assert calls[-1] == "zatvoren" and calls.count("slanje") == 1


async def test_smtp_auth_failure_is_not_retried(sending, monkeypatch):
    sending.resend_api_key = None
    sending.smtp_host, sending.smtp_user, sending.smtp_password = (
        "smtp.test",
        "bot@example.com",
        "test",
    )
    calls = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            calls.append("connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("close")

        def login(self, *args):
            raise smtplib.SMTPAuthenticationError(535, b"Neispravna prijava")

    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", SMTP)
    out = await registry.execute("mail_send", ARGS)
    assert (await registry.confirm(out.pending[0])).startswith("Greška:")
    assert calls == ["connect", "close"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("to", "a@example.com\r\nBcc: skriven@example.com"),
        ("cc", "a@example.com\nBcc: skriven@example.com"),
        ("subject", "Proba\r\nBcc: skriven@example.com"),
        ("to", "nije-adresa"),
        ("subject", " "),
        ("body", " "),
        ("sender", "skriven@example.com"),
        ("inReplyTo", "<id@example.com>\nBcc: x@example.com"),
    ],
)
async def test_invalid_or_injected_headers_cannot_create_pending_send(sending, field, value):
    out = await registry.execute("mail_send", {**ARGS, field: value})
    assert out.is_error and not out.pending


def test_filters_validate_dates_and_prevent_protocol_injection():
    for args in (
        {"since": "2026-02-30"},
        {"since": "2026-10-18", "before": "2026-10-17"},
        {"subject": "ponuda\r\nSTORE 1 +FLAGS \\Seen"},
        {"limit": 0},
    ):
        with pytest.raises(ValidationError):
            SearchArgs(**args)
    with pytest.raises(ValidationError):
        DraftArgs(**{**ARGS, "to": "valid@example.com, neispravan"})


def test_sending_requirements_are_independent_of_imap(sending, monkeypatch):
    for key in ("imap_host", "imap_user", "imap_password"):
        monkeypatch.setattr(sending, key, None)
    assert registry._TOOLS["mail_send"].disabled_reason() is None
    assert "IMAP_HOST" in registry._TOOLS["mail_search"].disabled_reason()
    sending.resend_api_key = None
    reason = registry._TOOLS["mail_send"].disabled_reason()
    assert "RESEND_API_KEY" in reason and "SMTP_HOST" in reason and "SMTP_PASSWORD" in reason


async def test_telegram_shows_complete_preview_then_send_button(sending, monkeypatch):
    out = await registry.execute("mail_send", {**ARGS, "body": "x" * 9000 + " kraj"})
    monkeypatch.setattr(settings(), "streaming", "off")
    monkeypatch.setattr(
        telegram_bot.loop,
        "run",
        AsyncMock(
            return_value=AgentResult("Pripremljeno; potvrdi dugmetom.", "test", [out.pending])
        ),
    )
    bot = SimpleNamespace(send_message=AsyncMock(), send_chat_action=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))
    await telegram_bot._answer(update, SimpleNamespace(bot=bot), "Pripremi mejl")
    calls = bot.send_message.call_args_list
    assert all(len(c.args[1]) <= telegram_bot.TG_LIMIT for c in calls)
    assert "kraj" in calls[-1].args[1]
    buttons = calls[-1].kwargs["reply_markup"].inline_keyboard[0]
    assert buttons[0].text == "📨 Pošalji" and buttons[0].callback_data.startswith("ok:")
    assert all("reply_markup" not in c.kwargs for c in calls[:-1])
    registry.cancel(out.pending[0])
