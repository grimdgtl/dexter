import asyncio
import ipaddress
import json
import socket
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from dexter.config import settings
from dexter.services import monitor
from dexter.tools import registry

PUBLIC = "93.184.216.34"
SITE = {"name": "Пример", "url": "https://example.test/path"}


@pytest.fixture
def dns(monkeypatch):
    addresses = {}
    thread = threading.get_ident()

    def resolve(host, port, **kwargs):
        assert threading.get_ident() != thread
        try:
            ipaddress.ip_address(host)
            values = [host]
        except ValueError:
            values = addresses.get(host, [PUBLIC])
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in values
        ]

    monkeypatch.setattr(monitor.socket, "getaddrinfo", resolve)
    return addresses


async def test_get_uses_public_ip_original_host_and_sni_without_reading_body(dns, respx_mock):
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            raise AssertionError("Telo sajta nije potrebno za proveru statusa.")
            yield b""

        async def aclose(self):
            self.closed = True

    body = Body()
    route = respx_mock.get(f"https://{PUBLIC}/path").respond(200, stream=body)
    result = await monitor.check_site(SITE)
    assert result["ok"] and not result["slow"] and result["status"] == 200
    assert result["name"] == "Primer" and result["url"] == SITE["url"]
    assert route.calls[0].request.headers["Host"] == "example.test"
    assert route.calls[0].request.extensions["sni_hostname"] == "example.test"
    assert body.closed


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.test",
        "http://localhost/",
        "https://a.localhost",
        "https://a.internal",
        "https://a.local",
        "https://user:pass@example.test",
        "https://bad host.test",
        "http://127.0.0.1",
        "http://10.0.0.1",
        "http://169.254.169.254",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://[::1]",
        "http://[fc00::1]",
        "http://[fe80::1]",
        "http://224.0.0.1",
        "http://0.0.0.0",
    ],
)
async def test_internal_and_invalid_urls_do_not_send_http(dns, respx_mock, url):
    result = await monitor.check_site({"name": "Test", "url": url})
    assert not result["ok"] and result["status"] is None and result["error"]
    assert not respx_mock.calls


async def test_mixed_dns_and_redirect_to_private_are_rejected(dns, respx_mock):
    dns["example.test"] = [PUBLIC, "127.0.0.1"]
    assert not (await monitor.check_site(SITE))["ok"]
    assert not respx_mock.calls
    dns["example.test"] = [PUBLIC]
    route = respx_mock.get(f"https://{PUBLIC}/path").respond(
        302, headers={"Location": "http://169.254.169.254/latest"}
    )
    result = await monitor.check_site(SITE)
    assert not result["ok"] and "javne" in result["error"]
    assert route.call_count == 1 and len(respx_mock.calls) == 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("IPv6 nije dostupan"), httpx.ConnectTimeout("IPv6 kasni")]
)
async def test_public_redirect_and_next_dns_address(dns, respx_mock, error):
    dns["example.test"] = ["2606:4700:4700::1111", PUBLIC]
    respx_mock.get("https://[2606:4700:4700::1111]/path").mock(side_effect=error)
    respx_mock.get(f"https://{PUBLIC}/path").respond(
        302, headers={"Location": "https://other.test/final"}
    )
    final = respx_mock.get(f"https://{PUBLIC}/final").respond(200)
    result = await monitor.check_site(SITE)
    assert result["ok"] and final.call_count == 1
    assert final.calls[0].request.headers["Host"] == "other.test"
    assert final.calls[0].request.extensions["sni_hostname"] == "other.test"


@pytest.mark.parametrize(
    "status,elapsed,ok,slow",
    [
        (200, 0.01, True, False),
        (200, 6, False, True),
        (500, 6, False, False),
        (404, 0.01, False, False),
    ],
)
async def test_http_slow_and_down_status(dns, respx_mock, monkeypatch, status, elapsed, ok, slow):
    timer = iter([0, elapsed])
    monkeypatch.setattr(monitor, "time", SimpleNamespace(perf_counter=lambda: next(timer)))
    respx_mock.get(f"https://{PUBLIC}/path").respond(status)
    result = await monitor.check_site(SITE)
    assert result["ok"] == ok and result["slow"] == slow
    assert result["ms"] == round(elapsed * 1000) and result["status"] == status
    assert result["error"] == (f"HTTP {status}" if status >= 400 else None)


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout("Proba"), httpx.ConnectError("Proba"), OSError("DNS")]
)
async def test_network_errors_are_per_site(dns, respx_mock, error):
    respx_mock.get(f"https://{PUBLIC}/path").mock(side_effect=error)
    result = await monitor.check_site(SITE)
    assert not result["ok"] and result["error"]
    if isinstance(error, httpx.ReadTimeout):
        assert "timeout" in result["error"]


async def test_redirect_loop_is_bounded(dns, respx_mock):
    route = respx_mock.get(f"https://{PUBLIC}/path").respond(302, headers={"Location": "/path"})
    result = await monitor.check_site(SITE)
    assert not result["ok"] and "preusmeravanje" in result["error"]
    assert route.call_count == 6


async def test_total_deadline_covers_dns(dns, monkeypatch):
    monkeypatch.setattr(settings(), "site_monitor_timeout_ms", 100)

    async def blocked(url):
        await asyncio.sleep(2)

    monkeypatch.setattr(monitor, "pinned_urls", blocked)
    result = await monitor.check_site(SITE)
    assert not result["ok"] and "timeout" in result["error"]


async def test_active_sites_paginates_filter_and_skips_empty(monkeypatch, respx_mock):
    base = "https://api.notion.com/v1"
    database, source = str(uuid4()), str(uuid4())
    monkeypatch.setattr(settings(), "notion_api_key", "test")
    monkeypatch.setattr(settings(), "notion_clients_db_id", database)
    respx_mock.get(f"{base}/databases/{database}").respond(
        200, json={"data_sources": [{"id": source}]}
    )

    def page(name, url):
        return {
            "id": str(uuid4()),
            "properties": {
                "Klijent": {"type": "title", "title": [{"plain_text": name}]},
                "Domen": {"url": url},
            },
        }

    route = respx_mock.post(f"{base}/data_sources/{source}/query").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [page("A", "https://example.test"), page("Prazno", None)],
                    "has_more": True,
                    "next_cursor": "druga",
                },
            ),
            httpx.Response(200, json={"results": [page("B", "other.test")], "has_more": False}),
        ]
    )
    assert [site["name"] for site in await monitor.active_sites()] == ["A", "B"]
    first = json.loads(route.calls[0].request.content)
    assert first["filter"] == {"property": "Aktivan", "select": {"equals": "Aktivan"}}
    assert json.loads(route.calls[1].request.content)["start_cursor"] == "druga"


async def test_concurrency_is_bounded_and_history_failure_is_visible(monkeypatch):
    sites = [{"name": str(i), "url": "https://example.test"} for i in range(17)]
    active = peak = 0

    async def check(site):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        await asyncio.sleep(0)
        active -= 1
        return {**site, "ok": site["name"] != "0"}

    monkeypatch.setattr(monitor, "active_sites", AsyncMock(return_value=sites))
    monkeypatch.setattr(monitor, "check_site", check)
    recorder = AsyncMock(side_effect=RuntimeError("Nema baze"))
    monkeypatch.setattr(monitor, "record", recorder)
    result = await monitor.check_all_sites()
    assert peak == 5 and result["checked"] == 17 and len(result["problems"]) == 1
    assert "nije sačuvana" in result["napomena"]
    recorder.assert_awaited_once_with(result["results"])


async def test_monitor_status_and_notion_error(monkeypatch, respx_mock):
    monkeypatch.setattr(settings(), "notion_api_key", "test")
    monkeypatch.setattr(settings(), "notion_clients_db_id", "clients")
    respx_mock.get("https://api.notion.com/v1/databases/clients").respond(
        403, json={"code": "restricted_resource", "message": "Nema pristupa"}
    )
    assert (await registry.execute("monitor_check_sites", {})).is_error
    monkeypatch.setattr(settings(), "notion_clients_db_id", None)
    assert "NOTION_CLIENTS_DB_ID" in registry._TOOLS["monitor_check_sites"].disabled_reason()
    assert registry._TOOLS["monitor_uptime"].is_enabled()
