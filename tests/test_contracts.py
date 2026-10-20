"""Izmišljeni ugovor je regresioni skup; tačnost pravog OCR-a meri se zasebno."""

import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import BadRequestError
from pydantic import ValidationError

from dexter.contracts import evidence, service
from dexter.contracts.models import Citation, Extraction, Fact
from dexter.tools import registry
from evals.contract_cases import PAGES, extraction, review


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("tools.0.input_schema: unsupported keyword $ref", "unsupported keyword $ref"),
        ("tool_choice: this model requires auto", "this model requires auto"),
        ("Your credit balance is too low", "Nema dovoljno kredita"),
        ("messages.0.content: PRIVATE OCR", "Detaljan odgovor servisa je izostavljen"),
    ],
)
async def test_extraction_api_failure_gives_safe_diagnostic_without_actions(
    monkeypatch, caplog, reason, expected
):
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        headers={"request-id": "req_contract_test"},
    )
    exc = BadRequestError(
        "PRIVATE EXCEPTION TEXT",
        response=response,
        body={"error": {"type": "invalid_request_error", "message": reason}},
    )
    create = AsyncMock(side_effect=exc)
    monkeypatch.setattr(service.llm, "create", create)
    with pytest.raises(ValueError, match="HTTP 400") as failure:
        await service._extraction_request(model="test", messages=[])
    assert expected in str(failure.value)
    assert "req_contract_test" in str(failure.value)
    assert "zadaci nisu upisani" in str(failure.value)
    assert expected in caplog.text
    assert "PRIVATE" not in caplog.text + str(failure.value)
    create.assert_awaited_once()


def test_public_parameter_diagnostics_redact_keys_and_drop_additional_lines(monkeypatch):
    monkeypatch.setattr(service.settings(), "anthropic_api_key", "private-key")
    monkeypatch.setattr(service.settings(), "telegram_bot_token", "private-token")
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com"))
    exc = BadRequestError(
        "unused",
        response=response,
        body={
            "message": "tools.0.input_schema: private-key private-token sk-secret Bearer secret\nPRIVATE OCR"
        },
    )
    detail = service._request_error_detail(exc)
    assert detail.startswith("tools.0.input_schema:")
    assert "private" not in detail and "secret" not in detail and "PRIVATE OCR" not in detail
    assert detail.count("[uklonjeno]") == 4


@pytest.mark.parametrize("cached", [["old"], [None, "old"], ["x" * (service.MAX_CHARS + 1), "old"]])
async def test_invalid_ocr_checkpoint_does_not_replace_native_pages(monkeypatch, cached):
    db = SimpleNamespace(fetchval=AsyncMock(return_value={"stranice": cached}))
    monkeypatch.setattr(service, "pool", lambda: db)
    assert await service._reuse_ocr("review", ["native", ""]) == ["native", ""]


async def test_ocr_checkpoint_supplements_only_missing_native_pages(monkeypatch):
    db = SimpleNamespace(fetchval=AsyncMock(return_value={"stranice": ["old", "saved"]}))
    monkeypatch.setattr(service, "pool", lambda: db)
    assert await service._reuse_ocr("review", ["native", ""]) == ["native", "saved"]


def test_valid_fields_dates_and_tax_id_come_from_evidence():
    result = evidence.checked(extraction(), PAGES)
    assert result["strane"][0]["pib"]["vrednost"] == "000000001"
    assert result["datumi"]["istek"]["vrednost"] == "2030-12-31"
    assert result["obaveze"][0]["iznos"]["status"] == "citat_proveren"
    proposals = review().predlozi
    assert len(proposals) == 2
    assert proposals[0].rok == "2030-03-15" and proposals[0].podsetnik == "2030-03-14"
    assert proposals[1].rok == proposals[1].podsetnik == "2030-12-01"


@pytest.mark.parametrize(
    "change", ["page", "paragraph", "quote", "value", "relative", "invalid-date"]
)
def test_wrong_citation_or_value_is_never_a_confirmed_deadline(change):
    data = extraction()
    field = data.obaveze[0].do_kada
    if change == "page":
        field.dokaz.strana = 99
    elif change == "paragraph":
        field.dokaz.pasus = 1
    elif change == "quote":
        field.dokaz.citat = "Izmišljeni citat o datumu 15.03.2030."
    elif change == "value":
        field.vrednost = "2030-03-16"
    elif change == "relative":
        field.vrednost = "za pet dana"
    else:
        field.vrednost = "2030-02-30"
    actual = evidence.checked(data, PAGES)["obaveze"][0]["do_kada"]
    assert actual["status"] == "nepotvrdjeno" and actual["vrednost"] is None
    assert len(evidence.proposals(data, PAGES, date(2026, 10, 19))) == 1


def test_missing_data_stays_missing_and_made_up_tax_value_is_rejected():
    assert evidence.check(Fact(), PAGES)["status"] == "nije_pronadjeno"
    assert evidence.proposals(Extraction(), PAGES, date(2026, 10, 19)) == []
    raw = extraction().model_dump()
    raw["strane"][0]["pib"] = "123456789"
    with pytest.raises(ValidationError):
        Extraction.model_validate(raw)


@pytest.mark.parametrize("text", ["PIB: 000000001; PIB: 000000002.", "PIB: 0000000010."])
def test_ambiguous_or_wrong_length_tax_id_is_not_a_fact(text):
    result = evidence.tax_id(Citation(strana=1, pasus=1, citat=text), [[text]])
    assert result["status"] == "nepotvrdjeno" and result["vrednost"] is None


def test_quote_whitespace_latin_and_number_boundaries():
    field = Fact(vrednost="Izvršilac", dokaz=Citation(strana=1, pasus=1, citat="Улога: Извршилац."))
    assert evidence.check(field, [["Uloga:\nIzvršilac."]])["status"] == "citat_proveren"
    field.vrednost = "Izvrši"
    assert evidence.check(field, [["Uloga:\nIzvršilac."]])["status"] == "nepotvrdjeno"
    assert evidence.dates_in("29.02.2030. 31.04.2030. 2030-12-31") == {date(2030, 12, 31)}
    amount = extraction().obaveze[0].iznos
    amount.vrednost = "000"
    assert evidence.check(amount, PAGES, kind="money")["status"] == "nepotvrdjeno"


@pytest.mark.parametrize(
    "text",
    [
        "Ugovor se automatski produžava.",
        "Trajanje je neodređeno.",
        "Važenje pod uslovom potpisa aneksa.",
    ],
)
def test_conditional_expiration_has_no_automatic_date_proposal(text):
    pages = copy.deepcopy(PAGES)
    pages[1].append(text)
    assert len(evidence.proposals(extraction(), pages, date(2026, 10, 19))) == 1


def test_wrong_date_role_does_not_create_expiration_reminder_and_past_dates_are_skipped():
    data = extraction()
    data.datumi.istek = data.datumi.zakljucenje
    assert len(evidence.proposals(data, PAGES, date(2026, 10, 19))) == 1
    assert evidence.proposals(extraction(), PAGES, date(2031, 1, 1)) == []


def test_review_is_latin_and_missing_or_bad_field_is_explicit():
    result = review()
    result.izdvojeno.datumi.pocetak.vrednost = "2030-03-02"
    text = service.render(result)
    assert "nepotvrđeno" in text and "Strana 1" in text and "str. 2, pasus 1" in text
    assert "nije upisano" in text and "ne tačnost OCR-a" in text


async def test_confirmation_private_arguments_cannot_be_supplied_by_model(monkeypatch):
    monkeypatch.setattr(registry.settings(), "notion_api_key", "test")
    monkeypatch.setattr(registry.settings(), "notion_todo_db_id", "test")
    result = await registry.execute(
        "contract_task_create",
        {
            "pregled_id": review().id,
            "predlog_id": review().predlozi[0].id,
            "tekst": "Izmišljeni zadatak",
            "rok": "2030-01-01",
        },
    )
    assert result.is_error and result.pending is None


async def test_analyze_limits_before_paid_calls(monkeypatch):
    db = SimpleNamespace(fetchval=AsyncMock(return_value=None))
    monkeypatch.setattr(service, "pool", lambda: db)
    create = AsyncMock()
    monkeypatch.setattr(service.llm, "create", create)
    monkeypatch.setattr(service.ingest, "_pdf_pages", lambda _: ["x"] * 6)
    with pytest.raises(ValueError, match="CONTRACT_MAX_PAGES"):
        await service.analyze("x.pdf", b"x")
    with pytest.raises(ValueError, match="10 MB"):
        await service.analyze("x.pdf", b"x" * (service.MAX_BYTES + 1))
    create.assert_not_awaited()


@pytest.mark.parametrize("kind", ["text", "wrong-tool", "multiple", "truncated", "invalid"])
async def test_auto_contract_requires_one_complete_valid_expected_tool_before_saving(
    monkeypatch, kind
):
    db = SimpleNamespace(fetchval=AsyncMock(return_value=None), execute=AsyncMock())
    monkeypatch.setattr(service, "pool", lambda: db)
    monkeypatch.setattr(service.ingest, "_pdf_pages", lambda _: ["Izmišljeni ugovor."])
    block = SimpleNamespace(type="tool_use", name="contract_data", input=extraction().model_dump())
    content, stop = [block], "tool_use"
    if kind == "text":
        content, stop = [SimpleNamespace(type="text", text="Običan sažetak ugovora")], "end_turn"
    elif kind == "wrong-tool":
        block.name = "mail_send"
    elif kind == "multiple":
        content = [block, block]
    elif kind == "truncated":
        stop = "max_tokens"
    else:
        block.input = {"strane": "neispravna struktura"}
    create = AsyncMock(return_value=SimpleNamespace(content=content, stop_reason=stop))
    monkeypatch.setattr(service.llm, "create", create)
    with pytest.raises(ValueError):
        await service.analyze("primer.pdf", b"primer")
    db.execute.assert_not_awaited()
    create.assert_awaited_once()
    assert create.await_args.kwargs["tool_choice"]["type"] == "auto"


def test_contract_eval_reports_negative_cases_without_paid_calls():
    from evals.contract_eval import evaluate

    result = evaluate()
    assert result["uspesno"] == result["ukupno"] == 5 and result["placeni_pozivi"] == 0
    bad = next(c for c in result["primeri"] if c["primer"] == "izmisljen_citat")
    assert bad["statusi"]["nepotvrdjeno"] == 1
