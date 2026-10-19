from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dexter.agent import router
from dexter.config import settings


@pytest.mark.parametrize("level,tier", [("lako", "fast"), ("srednje", "main"), ("teško", "deep")])
async def test_classifier_selects_tier(monkeypatch, level, tier):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"nivo":"' + level + '"}')],
            stop_reason="end_turn",
        )
    )
    monkeypatch.setattr(router.llm, "create", create)
    assert (await router.select_model("Poruka"))[0] == getattr(settings(), "model_" + tier)
    assert create.await_args.kwargs["purpose"] == "router"


@pytest.mark.parametrize("bad", ["nije json", '{"nivo":"nepoznato"}', '{"nivo":[]}', "{}"])
async def test_classifier_failure_falls_back_to_rule(monkeypatch, bad):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    monkeypatch.setattr(
        router.llm,
        "create",
        AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=bad)], stop_reason="end_turn"
            )
        ),
    )
    assert await router.select_model("Poruka") == router.pick_model("Poruka")


async def test_explicit_deep_prefix_bypasses_classifier(monkeypatch):
    monkeypatch.setattr(settings(), "router_mode", "classifier")
    create = AsyncMock()
    monkeypatch.setattr(router.llm, "create", create)
    assert await router.select_model("/duboko Analiziraj") == (settings().model_deep, "Analiziraj")
    create.assert_not_awaited()


@pytest.mark.parametrize(
    "text",
    [
        "Zdravo!",
        "Hvala na pomoći.",
        "Kakvo je vreme danas?",
        "Колико је 12 пута 5?",
        "Prikaži poslednja tri mejla.",
        "Prikaži moje lične zadatke",
        "Proveri sajtove",
        "Pronađi belešku u Notion-u",
        "Prikaži memoriju",
        "Šta imam u kalendaru sutra?",
        "Pretraži internet: vesti o Python-u",
        "Označi Doručak u checklisti",
        "Dodaj lični zadatak: kupiti kafu",
        "Ko slavi rođendan danas?",
        "Zapamti da volim kratke odgovore",
        "Pročitaj jednu belešku o projektu Orion.",
    ],
)
async def test_economy_routine_uses_fast_without_classifier(monkeypatch, text):
    monkeypatch.setattr(settings(), "router_mode", "economy")
    create = AsyncMock()
    monkeypatch.setattr(router.llm, "create", create)
    assert await router.select_model(text) == (settings().model_fast, text.strip())
    create.assert_not_awaited()


@pytest.mark.parametrize(
    "text",
    [
        "može",
        "da",
        "uradi to",
        "nastavi",
        "Šta misliš o tome?",
        "Objasni razliku između hostinga i domena.",
        "Analiziraj ugovor i uporedi rizike.",
        "Prikaži zadatke i napravi plan",
        "Proveri sajtove; pošalji izveštaj",
        "Prikaži zadatke\nNapravi predlog",
        "Prikaži kalendar pa pročitaj mejlove",
        "Napravi fakturu za klijenta",
        "Pošalji mejl za klijenta",
        "Zaboravi činjenicu 4",
        "Obriši sve zadatke",
        "Prikaži zadatke i kalendar",
        "Prikaži mejl " + "a" * 500,
        "a" * 801,
    ],
)
async def test_economy_complex_sensitive_and_ambiguous_stay_main(monkeypatch, text):
    monkeypatch.setattr(settings(), "router_mode", "economy")
    assert (await router.select_model(text))[0] == settings().model_main


@pytest.mark.parametrize("text", ["/duboko Analiziraj ugovor", "duboko: Razradi plan"])
async def test_economy_deep_is_explicit_and_strips_prefix(monkeypatch, text):
    monkeypatch.setattr(settings(), "router_mode", "economy")
    model, clean = await router.select_model(text)
    assert model == settings().model_deep
    assert clean in {"Analiziraj ugovor", "Razradi plan"}


def test_economy_offline_eval_preserves_fixed_dataset_and_labels():
    from evals.economy_eval import evaluate

    before, after = evaluate()
    assert before["poruka"] == after["poruka"] == 40
    assert before["lako_na_brzom"] == 0
    assert after["lako_na_brzom"] >= 10
    assert after["srednje_ili_tesko_na_brzom"] == 0
    assert after["hipoteticki_usd"] < before["hipoteticki_usd"]
    assert before["placeni_pozivi_izbora"] == after["placeni_pozivi_izbora"] == 0
