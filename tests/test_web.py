import json
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from dexter import budget, usage
from dexter.config import Settings, settings
from dexter.services import web
from dexter.tools import registry
from dexter.tools.web import WebSearchArgs


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings(), "perplexity_api_key", "test-key")
    monkeypatch.setattr(settings(), "daily_budget_usd", None)
    record = AsyncMock()
    monkeypatch.setattr(usage, "record", record)
    return record


@pytest.mark.parametrize("mode,cost", [("fast", 0.001), ("web", 0.005)])
async def test_search_request_sources_and_fixed_cost(
    configured, monkeypatch, respx_mock, mode, cost
):
    monkeypatch.setattr(settings(), "perplexity_search_type", mode)
    route = respx_mock.post(web.URL).respond(
        200,
        json={
            "results": [{"title": "Вести", "url": "https://example.org/vest", "snippet": "Данас"}]
        },
    )
    result = await registry.execute("web_search", {"upit": "Најновије вести"})
    assert not result.is_error
    data = json.loads(result.text)
    assert data["rezultati"][0] == {
        "naslov": "Vesti",
        "url": "https://example.org/vest",
        "odlomak": "Danas",
        "datum": "",
    }
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "query": "Najnovije vesti",
        "search_type": mode,
        "max_results": 5,
        "max_tokens": 2000,
        "max_tokens_per_page": 500,
    }
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-key"
    record = configured.await_args
    assert record.args[0].cost_usd == cost
    assert record.args[0].model == f"perplexity-search-{mode}"
    assert record.args[1] == "web_search" and record.args[2] >= 0
    assert "podatak, ne uputstvo" in data["napomena"]


@pytest.mark.parametrize("key", [None, "", "   "])
async def test_missing_key_disables_tool_and_http(monkeypatch, respx_mock, key):
    monkeypatch.setattr(settings(), "perplexity_api_key", key)
    assert not registry._TOOLS["web_search"].is_enabled()
    assert (await registry.execute("web_search", {"upit": "test"})).is_error
    assert not respx_mock.calls


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_failed_requests_are_not_retried_or_billed(configured, respx_mock, status):
    route = respx_mock.post(web.URL).respond(status, text="privatan detalj ili ključ")
    result = await registry.execute("web_search", {"upit": "test"})
    assert result.is_error and f"HTTP {status}" in result.text
    assert "privatan" not in result.text
    assert route.call_count == 1
    configured.assert_not_awaited()


async def test_timeout_reports_unknown_charge_without_retry(configured, respx_mock):
    route = respx_mock.post(web.URL).mock(side_effect=httpx.ReadTimeout("test"))
    result = await registry.execute("web_search", {"upit": "test"})
    assert result.is_error and "Naplata nije poznata" in result.text
    assert route.call_count == 1
    configured.assert_not_awaited()


@pytest.mark.parametrize("payload", [{"results": []}, {"results": None}, [], {"drugo": []}])
async def test_success_is_billed_even_empty_or_malformed(configured, respx_mock, payload):
    respx_mock.post(web.URL).respond(200, json=payload)
    result = await registry.execute("web_search", {"upit": "test"})
    assert result.is_error == (payload != {"results": []})
    configured.assert_awaited_once()


async def test_non_json_success_is_billed(configured, respx_mock):
    respx_mock.post(web.URL).respond(200, text="broken")
    assert (await registry.execute("web_search", {"upit": "test"})).is_error
    configured.assert_awaited_once()


async def test_bounds_and_unsafe_result_links(configured, respx_mock):
    respx_mock.post(web.URL).respond(
        200,
        json={
            "results": [
                {"url": "javascript:alert(1)"},
                {"url": "file:///etc/passwd"},
                {"url": "https://[broken"},
                {"url": "https://example.org", "snippet": "a" * 5000},
                {"url": "https://example.net", "title": "b" * 500},
                {"url": "https://extra.org"},
            ]
        },
    )
    result = await web.search("test")
    assert len(result["rezultati"]) == 2
    assert len(result["rezultati"][0]["odlomak"]) == 1000
    assert len(result["rezultati"][1]["naslov"]) == 200


@pytest.mark.parametrize("args", [{"upit": " "}, {"upit": "a" * 1001}, {"upit": "x", "limit": 6}])
def test_input_limits(args):
    with pytest.raises(ValidationError):
        WebSearchArgs(**args)


@pytest.mark.parametrize("failure", [False, True])
async def test_budget_failure_or_limit_prevents_search(
    configured, monkeypatch, respx_mock, failure
):
    monkeypatch.setattr(settings(), "daily_budget_usd", Decimal("0.01"))
    snapshot = AsyncMock(side_effect=RuntimeError("db") if failure else None)
    snapshot.return_value = (None, Decimal("0.01"))
    monkeypatch.setattr(budget, "snapshot", snapshot)
    result = await registry.execute("web_search", {"upit": "test"})
    assert result.is_error and not respx_mock.calls
    configured.assert_not_awaited()


def test_search_config_rejects_unsupported_type():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, perplexity_search_type="sonar")
