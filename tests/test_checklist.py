import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from dexter.config import Settings, settings
from dexter.services import checklist, dnevnik, insights
from dexter.services import notion_days as days
from dexter.tools import registry
from dexter.tools.checklist import DayArgs, DiaryArgs, InsightsArgs, MarkArgs


async def test_checklist_get_weekly_target_and_no_create(habits_notion):
    n = habits_notion
    for datum in ("2026-10-12", "2026-10-15", "2026-10-18", "2026-10-11", "2026-10-19"):
        n.page(datum, Trening=True)
    result = json.loads((await registry.execute("checklist_get", {"datum": "2026-10-18"})).text)
    assert result["postoji"] and result["dan"] == "Nedelja"
    assert result["fali"] == ["Doručak", "Bez slatkog"] and result["urađeno"] == 1
    assert result["teretana"] == {
        "stavka": "Trening",
        "odPonedeljka": "2026-10-12",
        "doNedelje": "2026-10-18",
        "bilo": 3,
        "cilj": 4,
        "ostalo": 1,
        "ispunjen": False,
    }
    assert n.create.call_count == n.update.call_count == 0
    assert n.check_query.calls[0].request.headers["Notion-Version"] == "2025-09-03"


async def test_missing_checklist_exposes_exact_names_without_creating(habits_notion):
    result = await checklist.get("2026-10-18")
    assert result["postoji"] is False
    assert list(result["stavke"]) == ["Trening", "Doručak", "Bez slatkog"]
    assert result["teretana"]["bilo"] == 0
    assert not habits_notion.create.called


async def test_mark_preserves_unmentioned_and_does_not_double_invert(habits_notion):
    n = habits_notion
    entry = n.page(Trening=True, **{"Bez slatkog": True})
    result = await registry.execute(
        "checklist_mark", {"datum": "2026-10-18", "stavke": {"Bez slatkog": False}}
    )
    data = json.loads(result.text)
    assert data["stavke"] == {"Trening": True, "Doručak": False, "Bez slatkog": False}
    assert data["id"] == entry["id"]
    assert json.loads(n.update.calls[0].request.content) == {
        "properties": {"Bez slatkog": {"checkbox": False}}
    }
    result = await checklist.mark({"Bez slatkog": True}, "2026-10-18")
    assert result["stavke"]["Bez slatkog"] is True


async def test_unknown_names_rejected_before_any_write(habits_notion):
    result = await registry.execute("checklist_mark", {"stavke": {"Teretana": True}})
    assert result.is_error and "Nepoznate" in result.text and "Trening" in result.text
    assert not habits_notion.create.called and not habits_notion.check_query.called


async def test_create_existing_day_is_idempotent(habits_notion):
    entry = habits_notion.page()
    result = await registry.execute("checklist_create_day", {"datum": "2026-10-18"})
    assert json.loads(result.text)["id"] == entry["id"]
    assert json.loads(result.text)["vecPostojao"] and result.pending is None
    assert not habits_notion.create.called


async def test_diary_read_missing_then_partial_write_preserves_fields(habits_notion):
    n = habits_notion
    result = await registry.execute("dnevnik_get", {"datum": "2026-10-18"})
    assert json.loads(result.text)["prazno"] == list(dnevnik.FIELDS)
    assert not n.create.called
    entry = n.page(diary=True)
    entry["properties"]["Ključna reč"] = {"rich_text": [{"plain_text": "фокус"}]}
    result = await registry.execute(
        "dnevnik_write", {"datum": "2026-10-18", "raspolozenje": "Dobro"}
    )
    data = json.loads(result.text)
    assert data["raspolozenje"] == "Dobro" and data["kljucnaRec"] == "fokus"
    assert data["energija"] is None and data["prazno"] == ["Energija"] and not data["popunjen"]
    assert json.loads(n.update.calls[0].request.content)["properties"] == {
        "Raspoloženje": {"select": {"name": "Dobro"}}
    }
    result = await dnevnik.write("2026-10-18", energija="Visoka", kljucnaRec="Срећан")
    assert result["prazno"] == [] and result["popunjen"] and result["kljucnaRec"] == "Srećan"


async def test_diary_empty_write_does_not_clear_existing_fields(habits_notion):
    habits_notion.page(diary=True)
    result = await dnevnik.write("2026-10-18")
    assert result["prazno"] == list(dnevnik.FIELDS)
    assert not habits_notion.update.called


@pytest.mark.parametrize(
    "tool_name,source_kind",
    [
        ("checklist_get", "check"),
        ("checklist_mark", "check"),
        ("checklist_create_day", "check"),
        ("dnevnik_get", "diary"),
        ("dnevnik_write", "diary"),
        ("insights_get", "check"),
    ],
)
async def test_each_tool_handles_api_error(habits_notion, respx_mock, tool_name, source_kind):
    n = habits_notion
    database = n.check_db if source_kind == "check" else n.diary_db
    respx_mock.get(f"{n.base}/databases/{database}").respond(
        403, json={"object": "error", "code": "restricted_resource", "message": "Nema pristupa"}
    )
    args = {"stavke": {"Trening": True}} if tool_name == "checklist_mark" else {}
    result = await registry.execute(tool_name, args)
    assert result.is_error and "Nema pristupa" in result.text
    assert not n.create.called


@pytest.mark.parametrize("change", ["duplicate", "missing_column", "wrong_target", "multi_source"])
async def test_checklist_refuses_misleading_data(habits_notion, monkeypatch, respx_mock, change):
    n = habits_notion
    entry = n.page()
    if change == "duplicate":
        n.page()
    elif change == "missing_column":
        del entry["properties"]["Doručak"]
    elif change == "wrong_target":
        monkeypatch.setattr(settings(), "checklist_ciljna_stavka", "Nepoznato")
    else:
        respx_mock.get(f"{n.base}/databases/{n.check_db}").respond(
            200, json={"data_sources": [{"id": n.check_source}] * 2}
        )
    with pytest.raises(ValueError):
        await checklist.get("2026-10-18")
    assert not n.create.called


async def test_period_pagination_and_bad_cursor(habits_notion):
    n = habits_notion
    first, second = n.page("2026-10-17"), n.page()
    n.check_query.mock(
        side_effect=[
            httpx.Response(
                200, json={"results": [first], "has_more": True, "next_cursor": "dalje"}
            ),
            httpx.Response(200, json={"results": [second], "has_more": False}),
        ]
    )
    from dexter.services import notion

    async with notion.client() as api:
        rows = await days.period(api, n.check_source, "2026-10-01", "2026-10-18")
    assert (
        len(rows) == 2
        and json.loads(n.check_query.calls[1].request.content)["start_cursor"] == "dalje"
    )
    n.check_query.mock(
        return_value=httpx.Response(
            200, json={"results": [], "has_more": True, "next_cursor": "opet"}
        )
    )
    async with notion.client() as api:
        with pytest.raises(RuntimeError, match="paginaciju"):
            await days.period(api, n.check_source, "2026-10-01", "2026-10-18")


def test_local_date_and_iso_validation(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 17, 22, 30, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(days, "datetime", FrozenDatetime)
    assert days.day().isoformat() == "2026-10-18"
    for value in ("2026-02-30", "20261018", "2026-10-18T12:00:00"):
        with pytest.raises(ValidationError):
            DayArgs(datum=value)
    for value in ("true", 1, None):
        with pytest.raises(ValidationError):
            MarkArgs(stavke={"Trening": value})
    for args in ({"raspolozenje": "Super"}, {"energija": "Dobra"}, {"kljucnaRec": ""}):
        with pytest.raises(ValidationError):
            DiaryArgs(**args)
    for value in (0, 367):
        with pytest.raises(ValidationError):
            InsightsArgs(dana=value)


def test_csv_config_defaults_and_custom_items(monkeypatch):
    cfg = Settings(_env_file=None)
    assert "Vežbanje" in cfg.checklist_pozitivne and cfg.checklist_cilj_nedeljno == 3
    monkeypatch.setattr(settings(), "checklist_pozitivne", " Jedna,  Druga ")
    monkeypatch.setattr(settings(), "checklist_izbegavanja", " Bez treće, ")
    assert checklist.items() == ["Jedna", "Druga", "Bez treće"]
    monkeypatch.setattr(settings(), "checklist_izbegavanja", "Jedna")
    with pytest.raises(ValueError, match="različite"):
        checklist.items()


def test_requirements_and_semantic_instructions(habits_notion, monkeypatch):
    for name in ("checklist_get", "checklist_mark", "checklist_create_day", "insights_get"):
        t = registry._TOOLS[name]
        assert t.requires == tuple(checklist.REQUIRES) and t.is_enabled() and not t.confirm
    assert "IZBEGAO" in registry._TOOLS["checklist_mark"].description
    assert "OBAVEZNO" in registry._TOOLS["dnevnik_write"].description
    assert "napomena" in registry._TOOLS["insights_get"].description
    monkeypatch.setattr(settings(), "notion_dnevnik_db_id", None)
    assert registry._TOOLS["dnevnik_get"].disabled_reason() == "Nedostaje: NOTION_DNEVNIK_DB_ID"
    assert registry._TOOLS["insights_get"].is_enabled()
    monkeypatch.setattr(settings(), "notion_checklist_db_id", None)
    assert not registry._TOOLS["checklist_get"].is_enabled()


def sample(datum, marked=True):
    return {"datum": datum, "stavke": {"Trening": marked, "Doručak": marked, "Bez slatkog": marked}}


def test_insights_scores_gaps_current_streak_and_weekday(habits_notion):
    checks = [
        sample("2026-10-12"),
        sample("2026-10-13"),
        sample("2026-10-15"),
        sample("2026-10-16", False),
    ]
    result = insights.calculate(checks, [], "2026-10-12", "2026-10-18")
    assert result["brojDana"] == 4 and result["danaBezReda"] == 3
    assert result["prosekProcenat"] == 75 and result["prosekSkora"] == 2.3
    assert result["nizovi"] == {"tekuci": 0, "najduzi": 2}
    assert result["najcescePreskoceno"][0]["propusteno"] == 1
    assert result["poDanimaNedelje"][-1] == {"dan": "Petak", "prosek": 0, "merenja": 1}
    checks.append(sample("2026-10-18"))
    assert insights.calculate(checks, [], "2026-10-12", "2026-10-18")["nizovi"]["tekuci"] == 1


def test_insights_associations_require_three_per_side_and_valid_matching_ratings(habits_notion):
    checks = [sample(f"2026-10-{i:02}", marked=i <= 3) for i in range(1, 7)]
    diary = [
        {
            "datum": p["datum"],
            "raspolozenje": "Odlično" if i < 3 else "Loše",
            "energija": "Visoka" if i < 3 else "Niska",
        }
        for i, p in enumerate(checks)
    ]
    result = insights.calculate(checks, diary, "2026-10-01", "2026-10-06")
    link = result["vezaSaRaspolozenjem"][0]
    assert link["danaSa"] == link["danaBez"] == 3 and link["razlika"] == 3
    assert result["vezaSaEnergijom"][0]["razlika"] == 2
    assert "ne dokaz" in result["napomena"]
    diary[-1]["raspolozenje"] = "constructor"
    diary[-1]["energija"] = None
    result = insights.calculate(checks, diary, "2026-10-01", "2026-10-06")
    assert result["vezaSaRaspolozenjem"] == result["vezaSaEnergijom"] == []
    assert result["uparenoRaspolozenje"] == 5 and "najmanje 3" in result["napomena"]


def test_insights_excludes_duplicates_invalid_dates_and_future(habits_notion):
    checks = [
        sample("2026-10-01"),
        sample("2026-10-01", False),
        sample("2026-10-02"),
        sample(None),
        sample("2026-02-30"),
        sample("2026-10-19"),
    ]
    result = insights.calculate(checks, [], "2026-10-01", "2026-10-18")
    assert result["brojDana"] == 1 and result["nizovi"]["najduzi"] == 1
    assert "dupli/neispravni" in result["napomena"]
    empty = insights.calculate([], [], "2026-10-01", "2026-10-18")
    assert empty["brojDana"] == 0


async def test_insights_tool_fetches_both_sources_and_allows_no_diary(habits_notion, monkeypatch):
    n = habits_notion
    n.page(Trening=True)
    n.page(diary=True)
    monkeypatch.setattr(days, "day", lambda value=None: datetime(2026, 10, 18).date())
    result = await registry.execute("insights_get", {"dana": 7})
    assert not result.is_error and json.loads(result.text)["brojDana"] == 1
    body = json.loads(n.check_query.calls[0].request.content)
    assert body["filter"]["and"][0]["date"] == {"on_or_after": "2026-10-12"}
    assert n.diary_query.call_count == 1
    monkeypatch.setattr(settings(), "notion_dnevnik_db_id", None)
    await insights.get(7)
    assert n.diary_query.call_count == 1


async def test_weekly_summary(habits_notion):
    habits_notion.page(Trening=True, **{"Doručak": True, "Bez slatkog": True})
    summary = await checklist.weekly_summary("2026-10-18")
    assert summary["brojDana"] == 1 and summary["procenat"] == 100
    assert summary["teretana"]["cilj"] == 4


async def test_invalid_diary_values_and_invalid_mark_prevent_writes(habits_notion):
    for args in ({"raspolozenje": "Super"}, {"energija": "super"}, {"kljucnaRec": " "}):
        with pytest.raises(ValueError):
            await dnevnik.write(**args)
    with pytest.raises(ValueError):
        await checklist.mark({"Trening": 1})
    assert not habits_notion.create.called and not habits_notion.update.called
