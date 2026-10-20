"""Kratak prikaz ne gubi izvor, ishod ili upozorenja i ne izlaže interne rezultate."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter import telegram_bot
from dexter.actions import ConfirmedAction, confirmation_text
from dexter.contracts import tasks
from evals.contract_cases import review


def test_short_title_keeps_complete_details_in_page_body():
    value = review()
    proposal = value.predlozi[0]
    args = tasks.TaskArgs(pregled_id=value.id, predlog_id=proposal.id)
    args._review, args._proposal = value, proposal
    args._destination = {"putanja": "Work → FIRMA → TASKS", "baza_id": "internal-db"}
    assert tasks.title(proposal) == "Izvršilac: dostavi izveštaj"
    details = tasks.description(args)
    assert proposal.tekst in details and proposal.izvor in details
    assert "Ugovor: " + value.naziv in details
    assert "14.03.2030." in details
    preview = tasks.preview(args)
    assert "Work → FIRMA → TASKS" in preview and "15.03.2030." in preview
    assert "internal-db" not in preview and proposal.izvor not in preview
    original_id = proposal.id
    long = proposal.model_copy(update={"tekst": "Veoma dug zadatak " * 30})
    assert len(tasks.title(long)) <= 100 and tasks.title(long).endswith("…")
    assert proposal.id == original_id


def test_confirmation_shows_message_link_and_scheduler_warning_without_internal_fields():
    raw = json.dumps(
        {
            "status": "sacuvano",
            "poruka": "Sačuvano u Work-u: Izveštaj",
            "notion": {"id": "private-task-id", "url": "https://notion.so/test"},
            "odrediste": {"baza_id": "private-db-id"},
            "napomena": "Automatsko slanje podsetnika je isključeno.",
        }
    )
    shown = confirmation_text(raw)
    assert "Sačuvano u Work-u" in shown and "https://notion.so/test" in shown
    assert "isključeno" in shown
    assert "private" not in shown and "status" not in shown and "{" not in shown


def test_old_notion_slug_is_shortened_and_important_warning_is_preserved():
    raw = json.dumps(
        {
            "poruka": "Zadatak već postoji.",
            "napomena": "Proveri da je u Work-u.",
            "notion": {
                "id": "11111111-1111-4111-8111-111111111111",
                "url": "https://app.notion.com/p/" + "dug-naslov-" * 40,
            },
        }
    )
    shown = confirmation_text(raw)
    assert "dug-naslov" not in shown and "Proveri da je u Work-u" in shown
    assert "https://www.notion.so/11111111111141118111111111111111" in shown


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"provider": "resend", "messageId": "hidden", "poslato": True}, "Mejl je poslat."),
        (
            {
                "broj": "067-2026",
                "brojPromenjen": True,
                "drive": {"id": "hidden", "link": "https://drive.google.com/test"},
            },
            "konačni PDF",
        ),
        (
            {"status": "delimicno", "poruka": "PDF je na Drive-u; Notion nije potvrđen."},
            "Notion nije potvrđen",
        ),
    ],
)
def test_other_confirmations_keep_useful_outcomes_without_json(raw, expected):
    shown = confirmation_text(json.dumps(raw))
    assert expected in shown and "hidden" not in shown and "{" not in shown


@pytest.mark.parametrize("failed", [False, True])
async def test_telegram_displays_short_result_but_keeps_machine_note(monkeypatch, failed):
    raw = json.dumps(
        {
            "status": "delimicno" if failed else "sacuvano",
            "poruka": "Упис није потврђен." if failed else "Сачувано у Work-у.",
            "id": "internal-id",
        }
    )
    monkeypatch.setattr(
        telegram_bot.registry,
        "confirm",
        AsyncMock(return_value=ConfirmedAction(raw, successful=not failed)),
    )
    note = AsyncMock()
    monkeypatch.setattr(telegram_bot.history, "add_note", note)
    query = SimpleNamespace(
        data="ok:token",
        message=SimpleNamespace(text="old long preview"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), callback_query=query)
    await telegram_bot.on_button(update, SimpleNamespace())
    shown = query.edit_message_text.await_args.args[0]
    assert "old long preview" not in shown and "internal-id" not in shown
    assert "status" not in shown and "{" not in shown
    assert ("Nije potpuno izvršeno" in shown) if failed else ("Sačuvano u Work-u" in shown)
    assert "internal-id" in note.await_args.args[1]
