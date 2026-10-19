"""Izmišljeni ugovor je regresioni skup; tačnost pravog OCR-a meri se zasebno."""

import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from dexter.contracts import evidence, service
from dexter.contracts.models import Citation, Extraction, Fact
from dexter.tools import registry
from evals.contract_cases import PAGES, extraction, review


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


def test_contract_eval_reports_negative_cases_without_paid_calls():
    from evals.contract_eval import evaluate

    result = evaluate()
    assert result["uspesno"] == result["ukupno"] == 5 and result["placeni_pozivi"] == 0
    bad = next(c for c in result["primeri"] if c["primer"] == "izmisljen_citat")
    assert bad["statusi"]["nepotvrdjeno"] == 1
