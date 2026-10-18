import io
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader

from dexter import telegram_bot
from dexter.agent.loop import AgentResult
from dexter.config import settings
from dexter.services import invoice_pdf, invoices, notion
from dexter.tools import registry
from dexter.tools.invoices import CreateArgs, ListArgs, invoice_create

ARGS = {
    "klijent": "Primer Studio",
    "datumIzdavanja": "2026-10-18",
    "stavke": [{"opis": "Održavanje sajta čćšđž", "cena": 12345.67}],
}


@pytest.fixture
def number_db(monkeypatch):
    pool = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    monkeypatch.setattr(invoices.db, "pool", lambda: pool)
    return pool


@pytest.mark.parametrize(
    "floor,year,numbers,expected",
    [
        (None, 2026, [], "001-2026"),
        ("066-2026", 2026, [], "067-2026"),
        ("066-2026", 2027, ["123-2026"], "001-2027"),
        ("066-2026", 2025, ["004-2025"], "005-2025"),
        ("066-2026", 2026, ["070-2026", "999-2025", "neispravan"], "071-2026"),
        (None, 2026, ["999-2026"], "1000-2026"),
    ],
)
async def test_numbering_year_floor_and_manual_rows(
    invoice_notion, number_db, monkeypatch, floor, year, numbers, expected
):
    n = invoice_notion
    monkeypatch.setattr(settings(), "invoice_last_number", floor)
    for number in numbers:
        n.add_invoice(number)
    async with notion.client() as api:
        assert await invoices.next_number(api, n.source, year) == expected


async def test_numbering_paginates_and_reads_durable_uncertain_attempts(invoice_notion, number_db):
    n = invoice_notion
    first = n.add_invoice("004-2026")
    second = n.add_invoice("009-2026")
    n.query.mock(
        side_effect=[
            httpx.Response(200, json={"results": [first], "has_more": True, "next_cursor": "jos"}),
            httpx.Response(200, json={"results": [second], "has_more": False}),
        ]
    )
    number_db.fetch.return_value = [{"value": {"broj": "010-2026", "status": "nepotvrđeno"}}]
    async with notion.client() as api:
        assert await invoices.next_number(api, n.source, 2026) == "011-2026"
    assert json.loads(n.query.calls[1].request.content)["start_cursor"] == "jos"


async def test_prepare_pdf_is_private_and_does_not_upload_or_archive(invoice_notion, number_db):
    n = invoice_notion
    out = await registry.execute("invoice_create", ARGS)
    assert not out.is_error and out.pending
    token, preview = out.pending
    doc = registry.pending_document(token)
    assert doc.data.startswith(b"%PDF-") and doc.filename.endswith(".pdf")
    assert (
        "PIB" not in registry._TOOLS["invoice_create"].args_model.model_json_schema()["properties"]
    )
    assert "pdf" not in out.text and "%PDF" not in out.text
    assert not n.upload.called and not n.create.called and not n.generated.called
    text = PdfReader(io.BytesIO(doc.data)).pages[0].extract_text()
    for expected in (
        "000000001",
        "000000002",
        "000-0000000000000-00",
        "Račun",
        "12.345,67",
    ):
        assert expected in text
    assert "001-2026" in preview and "12.345,67" in preview
    assert registry.pending_confirm_label(token) == "💾 Sačuvaj"
    assert registry.pending_cancel_label(token) == "❌ Odbaci"
    registry.cancel(token)


async def test_cancel_expiry_and_new_proposal_do_not_consume_number(invoice_notion, number_db):
    n = invoice_notion
    first = await registry.execute("invoice_create", ARGS)
    registry.cancel(first.pending[0])
    assert "istekla" in await registry.confirm(first.pending[0])
    second = await registry.execute("invoice_create", ARGS)
    registry._PENDING[second.pending[0]].created -= registry.CONFIRM_TTL_S + 1
    assert "istekla" in await registry.confirm(second.pending[0])
    assert "001-2026" in second.pending[1] and not n.upload.called and not n.create.called


async def test_new_proposal_discards_expired_pdf_bytes(invoice_notion, number_db):
    first = await registry.execute("invoice_create", ARGS)
    registry._PENDING[first.pending[0]].created -= registry.CONFIRM_TTL_S + 1
    second = await registry.execute("invoice_create", ARGS)
    assert first.pending[0] not in registry._PENDING
    assert registry.pending_document(first.pending[0]) is None
    registry.cancel(second.pending[0])


@pytest.mark.parametrize("env", [*invoices.ISSUER_FIELDS.values(), "INVOICE_ISSUER_BRAND"])
async def test_missing_issuer_names_variable_and_refuses_before_io(
    invoice_notion, number_db, monkeypatch, env
):
    monkeypatch.setattr(settings(), env.lower(), " ")
    assert env in invoices.configuration_error()
    with pytest.raises(ValueError, match=env):
        await invoices.prepare(CreateArgs(**ARGS))
    assert not invoice_notion.client_query.called and not invoice_notion.create.called


def test_real_logo_file_allows_no_brand_but_missing_file_does_not(
    invoice_notion, monkeypatch, tmp_path
):
    path = tmp_path / "logo.png"
    Image.new("RGB", (400, 100), "black").save(path)
    monkeypatch.setattr(settings(), "invoice_issuer_brand", None)
    monkeypatch.setattr(settings(), "invoice_logo_path", str(path))
    assert invoices.configuration_error() is None
    assert invoices.issuer_snapshot()[1]
    path.unlink()
    assert "INVOICE_ISSUER_BRAND" in invoices.configuration_error()


@pytest.mark.parametrize("case", ["missing", "ambiguous"])
async def test_customer_must_be_found_in_notion(invoice_notion, number_db, case):
    n = invoice_notion
    n.client_query.respond(
        200,
        json={
            "results": []
            if case == "missing"
            else [
                {
                    "id": "a",
                    "properties": {"Klijent": {"title": [{"plain_text": "Primer Studio"}]}},
                },
                {
                    "id": "b",
                    "properties": {"Klijent": {"title": [{"plain_text": "Primer Studio"}]}},
                },
            ],
            "has_more": False,
        },
    )
    result = await registry.execute("invoice_create", ARGS)
    assert result.is_error and not result.pending and not n.upload.called


async def test_missing_customer_fields_are_warned_not_invented(invoice_notion, number_db):
    n = invoice_notion
    n.client_query.respond(
        200,
        json={
            "results": [
                {
                    "id": n.customer["id"],
                    "properties": {"Klijent": {"title": [{"plain_text": "Primer Studio"}]}},
                }
            ],
            "has_more": False,
        },
    )
    result = await registry.execute("invoice_create", ARGS)
    assert "adresa, grad, pib, mb" in result.pending[1]
    document = registry.pending_document(result.pending[0])
    text = PdfReader(io.BytesIO(document.data)).pages[0].extract_text()
    assert "000000002" not in text
    registry.cancel(result.pending[0])


@pytest.mark.parametrize(
    "changes",
    [
        {"broj": "999-2026"},
        {"pib": "123"},
        {"issuer": {}},
        {"pdf": "x"},
        {"datumIzdavanja": "2026-02-30"},
        {"datumPrometa": "20261018"},
        {"stavke": []},
        {"stavke": [{"opis": "X"}]},
        {"stavke": [{"opis": "X", "cena": -1}]},
        {"stavke": [{"opis": "X", "cena": True}]},
        {"stavke": [{"opis": "X", "cena": 1, "kolicina": 0}]},
        {"stavke": [{"opis": "X", "cena": float("nan")}]},
        {"stavke": [{"opis": "X", "cena": 1.001}]},
    ],
)
def test_model_cannot_supply_fiscal_snapshot_or_invalid_amounts(changes):
    with pytest.raises(ValidationError):
        CreateArgs(**{**ARGS, **changes})


async def test_direct_unprepared_tool_call_refuses():
    with pytest.raises(ValueError, match="potvrđena"):
        await invoice_create(CreateArgs(**ARGS))


@pytest.mark.parametrize("name", ["invoice_create", "invoice_list"])
async def test_invoice_tools_report_notion_permission_error(
    invoice_notion, number_db, respx_mock, name
):
    n = invoice_notion
    database = n.client_db if name == "invoice_create" else n.archive_db
    respx_mock.get(f"{n.base}/databases/{database}").respond(
        403, json={"object": "error", "code": "restricted_resource", "message": "Nema pristupa"}
    )
    result = await registry.execute(name, ARGS if name == "invoice_create" else {})
    assert result.is_error and "Nema pristupa" in result.text
    assert not n.upload.called and not n.create.called


async def test_invoice_list_works_without_issuer_or_google_and_sorts(invoice_notion, monkeypatch):
    n = invoice_notion
    n.add_invoice("001-2026")
    monkeypatch.setattr(settings(), "invoice_issuer_name", None)
    monkeypatch.setattr(settings(), "google_refresh_token", None)
    result = await registry.execute("invoice_list", {"status": "Nije plaćeno"})
    assert not result.is_error and json.loads(result.text)[0]["broj"] == "001-2026"
    body = json.loads(n.query.calls[0].request.content)
    assert body["sorts"] == [{"property": "Datum izdavanja", "direction": "descending"}]
    assert body["filter"] == {"property": "Status", "select": {"equals": "Nije plaćeno"}}
    with pytest.raises(ValidationError):
        ListArgs(status="Platio")


async def test_telegram_document_precedes_save_button_and_failure_cancels(
    invoice_notion, number_db, monkeypatch
):
    out = await registry.execute("invoice_create", ARGS)
    monkeypatch.setattr(settings(), "streaming", "off")
    monkeypatch.setattr(
        telegram_bot.loop,
        "run",
        AsyncMock(return_value=AgentResult("Pogledaj PDF.", "test", [out.pending])),
    )
    events = []

    async def message(*args, **kwargs):
        if "reply_markup" in kwargs:
            events.append("buttons")
            buttons = kwargs["reply_markup"].inline_keyboard[0]
            assert [b.text for b in buttons] == ["💾 Sačuvaj", "❌ Odbaci"]

    async def document(*args, **kwargs):
        events.append("pdf")

    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=message),
        send_document=AsyncMock(side_effect=document),
        send_chat_action=AsyncMock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1))
    await telegram_bot._answer(update, SimpleNamespace(bot=bot), "Napravi fakturu")
    assert events == ["pdf", "buttons"]
    bot.send_document.side_effect = RuntimeError("Telegram ne prima PDF")
    bot.send_message.reset_mock()
    await telegram_bot._answer(update, SimpleNamespace(bot=bot), "Ponovo prikaz")
    assert out.pending[0] not in registry._PENDING
    assert not any("reply_markup" in call.kwargs for call in bot.send_message.call_args_list)


def test_money_decimal_rounding_matches_printed_line_totals():
    assert invoices.Item(opis="Одржавање сајта", cena=1).opis == "Održavanje sajta"
    items = [invoices.Item(opis="Proba", kolicina="0.333", cena="0.05")] * 3
    assert invoice_pdf.total(items) == Decimal("0.06")
    assert invoice_pdf.money(Decimal("12345.67")) == "12.345,67"
    assert invoice_pdf.display_date("2026-01-02") == "2.1.2026."


@pytest.mark.parametrize("document_fails", [False, True])
async def test_button_delivers_final_pdf_and_reports_partial_saves(monkeypatch, document_fails):
    from dexter.actions import ConfirmedAction, Document

    query = SimpleNamespace(
        data="ok:token",
        message=SimpleNamespace(text="Faktura za pregled"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)
    bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock())
    if document_fails:
        bot.send_document.side_effect = RuntimeError("Nije poslat PDF")
    monkeypatch.setattr(
        registry,
        "confirm",
        AsyncMock(
            return_value=ConfirmedAction(
                '{"broj":"002-2026","drive":"https://drive.google.com/test"}',
                Document(b"%PDF test", "Racun.pdf"),
            )
        ),
    )
    note = AsyncMock()
    monkeypatch.setattr(telegram_bot.history, "add_note", note)
    await telegram_bot.on_button(update, SimpleNamespace(bot=bot))
    assert bot.send_document.await_count == 1
    assert "002-2026" in query.edit_message_text.call_args.args[0]
    if document_fails:
        assert "preuzmi" in query.edit_message_text.call_args.args[0]
    monkeypatch.setattr(
        registry,
        "confirm",
        AsyncMock(return_value=ConfirmedAction('{"status":"delimicno"}', successful=False)),
    )
    await telegram_bot.on_button(update, SimpleNamespace(bot=bot))
    assert "Nije potpuno izvršeno" in query.edit_message_text.call_args.args[0]


async def test_long_pdf_keeps_all_items_total_and_stays_inside_page(invoice_notion, number_db):
    args = CreateArgs(
        **{
            **ARGS,
            "stavke": [
                {"opis": f"Stavka {i}: " + "Dugačak opis usluge. " * 70, "cena": "12.34"}
                for i in range(12)
            ],
        }
    )
    prepared = await invoices.prepare(args)
    pages = PdfReader(io.BytesIO(prepared.document.data)).pages
    assert len(pages) > 1
    text = "".join(p.extract_text() for p in pages)
    assert all(f"Stavka {i}:" in text for i in range(12))
    assert "148,08" in text and "Odgovorno lice" in text
    for page in pages:
        positions = []
        page.extract_text(
            visitor_text=lambda text, cm, tm, font, size, positions=positions: positions.append(
                (text, tm[5])
            )
        )
        assert all(35 <= y <= 805 for text, y in positions if text.strip())
