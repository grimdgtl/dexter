import io
import threading
from unittest.mock import AsyncMock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from dexter.rag import ingest, office


def test_docx_preserves_order_nested_table_headers_and_latin(office_files):
    text = office.text("UGOVOR.DOCX", office_files["ugovor.docx"])
    assert text.index("Početak") < text.index("Rok | 21. oktobar") < text.index("Kraj dokumenta")
    assert "Ugneždena napomena" in text
    assert "Zaglavlje ugovora" in text and "Podnožje dokumenta" in text
    assert "Орион" not in text


def test_xlsx_reads_every_sheet_numbers_dates_and_unevaluated_formulas(office_files):
    text = office.text("budzet.xlsx", office_files["budzet.xlsx"])
    assert "[List: Prihodi]" in text and "[List: Rezerva]" in text
    assert "125.5" in text and "2026-10-17" in text and "=SUM(B2:B3)" in text
    assert "0 | False" in text
    assert "Drugi list" in text


def test_incorrect_excel_dimension_does_not_hide_later_rows(office_files):
    out = io.BytesIO()
    with (
        ZipFile(io.BytesIO(office_files["budzet.xlsx"])) as source,
        ZipFile(out, "w", ZIP_DEFLATED) as dest,
    ):
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b'ref="A1:D2"', b'ref="A1:A1"')
            dest.writestr(name, data)
    assert "125.5" in office.text("test.xlsx", out.getvalue())


async def test_office_ingest_uses_worker_thread_and_rejects_oversized_zip(
    office_files, monkeypatch
):
    main = threading.get_ident()
    real = office.text

    def checked(*args):
        assert threading.get_ident() != main
        return real(*args)

    monkeypatch.setattr(office, "text", checked)
    store = AsyncMock(return_value=2)
    monkeypatch.setattr(ingest, "upsert_document", store)
    assert (await ingest.ingest_file("ugovor.docx", office_files["ugovor.docx"]))[0] == 2
    monkeypatch.setattr(office, "MAX_UNPACKED", 1)
    store.reset_mock()
    with pytest.raises(ValueError, match="prevelika"):
        await ingest.ingest_file("budzet.xlsx", office_files["budzet.xlsx"])
    store.assert_not_awaited()


async def test_drive_downloads_and_parses_office_file(office_files, monkeypatch):
    from dexter.services.google import Drive, indexable

    metadata = {
        "name": "Budžet",
        "mimeType": next(k for k, v in office.MIMES.items() if v == ".xlsx"),
    }
    assert indexable(metadata)
    drive = Drive()
    drive.call = AsyncMock(return_value=office_files["budzet.xlsx"])
    result = await drive.read("1", metadata)
    assert "[List: Rezerva]" in result["content"]
    assert drive.call.await_args.kwargs["fileId"] == "1"


def test_mail_reads_office_attachments_in_its_worker(office_files, make_mail):
    from imap_tools import MailMessage

    from dexter.services import mail

    raw = make_mail(
        attachments=[
            (name, data, "application/octet-stream") for name, data in office_files.items()
        ]
    )
    result = mail.document(MailMessage.from_bytes(raw))
    assert "Ugneždena napomena" in result.text and "[List: Rezerva]" in result.text
    assert result.skipped_attachments == 0
