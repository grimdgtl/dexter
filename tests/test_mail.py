"""Pravi MIME parser i IMAP biblioteka rade nad lažnim protokolom, bez mreže."""

import asyncio
from contextlib import aclosing
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from imap_tools import MailMessage
from imap_tools.folder import FolderInfo

from apu import config, sources
from apu.services import mail
from apu.sources import mail as source


@pytest.mark.parametrize(
    ("today", "months", "expected"),
    [
        (date(2026, 10, 15), 12, date(2025, 10, 15)),
        (date(2024, 3, 31), 1, date(2024, 2, 29)),
        (date(2025, 3, 31), 1, date(2025, 2, 28)),
    ],
)
def test_calendar_month_boundary(today, months, expected):
    assert mail.months_ago(today, months) == expected


def test_mime_document_has_metadata_html_fallback_and_stable_id(make_mail, pdf_bytes):
    raw = make_mail(
        subject="Понуда",
        message_id=None,
        html="<p>Договор &amp; рок</p><script>ne indeksiraj skriptu</script>",
        attachments=[
            ("opis.md", "Обим посла.".encode(), "text/markdown"),
            ("propis.pdf", pdf_bytes, "application/pdf"),
            ("veliki.txt", b"Z" * (mail.MAX_ATTACHMENT_BYTES + 1), "text/plain"),
        ],
    )
    result = mail.document(MailMessage.from_bytes(raw))
    assert result.id.startswith("mail:sha256:")
    assert result.id == mail.document(MailMessage.from_bytes(raw)).id
    assert "Ponuda" in result.title and "Marko Petrović" in result.title
    assert "2026-10-15" in result.title
    assert "Dogovor & rok" in result.text and "Obim posla." in result.text
    assert "proveru indeksiranja PDF" in result.text
    assert "ne indeksiraj skriptu" not in result.text and "ZZZZZ" not in result.text
    assert result.skipped_attachments == 1


def test_exclusions_sent_detection_and_missing_folder_fail_safely(imap_server, monkeypatch):
    cfg = config.settings()
    folders = [FolderInfo("INBOX", "/", ()), FolderInfo("Lične poruke", "/", ("\\Sent",))]
    assert mail.index_folders(folders, cfg) == ["INBOX", "Lične poruke"]
    cfg.mail_index_exclude = "Lične poruke"
    assert mail.index_folders(folders, cfg) == ["INBOX"]
    cfg.mail_index_sent_folder = "Nepostojeći"
    with pytest.raises(RuntimeError, match="MAIL_INDEX_SENT_FOLDER"):
        mail.index_folders(folders, cfg)
    cfg.mail_index_sent_folder = None
    with pytest.raises(RuntimeError, match="Sent folder"):
        mail.index_folders(folders[:1], cfg)


@pytest.mark.parametrize("filename", [None, "prilog.txt"])
@pytest.mark.parametrize("size", [32, 33])
def test_attachment_limit_cannot_be_bypassed_by_missing_filename(
    make_mail, monkeypatch, filename, size
):
    monkeypatch.setattr(mail, "MAX_ATTACHMENT_BYTES", 32)
    raw = make_mail(attachments=[(filename, b"X" * size, "text/plain")])
    result = mail.document(MailMessage.from_bytes(raw))
    assert ("X" * size in result.text) == (size == 32)
    assert result.skipped_attachments == int(size > 32)


async def test_real_sdk_uses_peek_readonly_and_logs_out_on_early_close(imap_server, make_mail):
    imap_server.messages["INBOX"] = [make_mail(), make_mail(message_id="<drugi@example.com>")]
    async with aclosing(mail.documents(date(2025, 10, 15))) as documents:
        first = await anext(documents)
        assert first.id == "mail:<test@example.com>"
    assert imap_server.closed
    fetches = [c for c in imap_server.calls if c[0] == "FETCH"]
    assert len(fetches) == 1 and "BODY.PEEK[]" in fetches[0][2]
    assert all(c[2] for c in imap_server.calls if c[0] == "SELECT")


async def test_index_or_embedding_failure_keeps_previous_index(imap_server, make_mail, monkeypatch):
    imap_server.messages["INBOX"] = [make_mail()]
    remove = AsyncMock()
    monkeypatch.setattr(source.store, "remove_missing", remove)
    monkeypatch.setattr(
        source.store, "upsert_document", AsyncMock(side_effect=RuntimeError("Embeddinzi"))
    )
    with pytest.raises(RuntimeError, match="Embeddinzi"):
        await source.reindex()
    assert imap_server.closed
    remove.assert_not_awaited()


async def test_cancellation_waits_for_imap_worker_before_cleanup():
    import threading

    started, release = threading.Event(), threading.Event()
    finished = []

    def blocking():
        started.set()
        assert release.wait(2)
        finished.append(True)

    async with asyncio.timeout(3):
        task = asyncio.create_task(mail._in_thread(blocking))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished == [True]


async def test_mail_only_configuration_connects_to_reindex_scheduler(imap_server, monkeypatch):
    from apu import scheduler

    for name in (
        "NOTION_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    config.settings.cache_clear()
    assert sources.available() == ["mail"]
    reindex = AsyncMock(return_value={"ukupno": 0})
    monkeypatch.setattr(source, "reindex", reindex)
    assert await sources.reindex("mail") == {"mail": {"ukupno": 0}}
    monkeypatch.setattr(scheduler.AsyncIOScheduler, "start", lambda self: None)
    sched = scheduler.start(SimpleNamespace())
    assert sched.get_job("knowledge_index") is not None
