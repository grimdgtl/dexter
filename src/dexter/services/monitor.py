"""Provere javnih sajtova iz KLIJENTI i istorija uzorka, bez čitanja sadržaja sajta."""

import asyncio
import ipaddress
import logging
import socket
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

import httpx

from dexter import db
from dexter.config import settings
from dexter.pismo import u_latinicu
from dexter.services import notion, notion_clients

REQUIRES = notion_clients.REQUIRES
MAX_HISTORY = 8000
log = logging.getLogger(__name__)


def normalize_url(raw: str) -> httpx.URL:
    text = raw.strip()
    url = httpx.URL(text if "://" in text else "https://" + text)
    if url.scheme not in {"http", "https"} or not url.host:
        raise ValueError("Domen mora biti HTTP/HTTPS adresa.")
    host = url.host.lower().rstrip(".")
    if (
        url.username
        or url.password
        or any(ch.isspace() for ch in text)
        or host == "localhost"
        or host.endswith((".localhost", ".internal", ".local"))
    ):
        raise ValueError("Interna adresa ili URL sa pristupnim podacima nije dozvoljen.")
    return url.copy_with(fragment=None)


async def pinned_urls(url: httpx.URL) -> list[httpx.URL]:
    addresses = await asyncio.to_thread(
        socket.getaddrinfo,
        url.host,
        url.port or (443 if url.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    ips = [ipaddress.ip_address(address[4][0]) for address in addresses]
    if not ips or any(not address.is_global or address.is_multicast for address in ips):
        raise ValueError("Domen ne pokazuje isključivo na javne IP adrese.")
    # GET koristi proverenu IP adresu; novo DNS razrešavanje ne može ga poslati u internu mrežu.
    return [url.copy_with(host=str(ip)) for ip in dict.fromkeys(ips)]


async def probe(client: httpx.AsyncClient, url: httpx.URL) -> tuple[int, str | None]:
    addresses = await pinned_urls(url)
    for index, pinned in enumerate(addresses):
        try:
            async with client.stream(
                "GET",
                pinned,
                headers={"Host": url.netloc.decode("ascii"), "User-Agent": "Dexter-Monitor/2.0"},
                extensions={"sni_hostname": url.host},
                timeout=httpx.Timeout(
                    settings().site_monitor_timeout_ms / 1000,
                    connect=settings().site_monitor_timeout_ms / (1000 * len(addresses)),
                ),
            ) as response:
                return response.status_code, response.headers.get("location")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if index == len(addresses) - 1:
                raise
    raise ValueError("Domen nema javnu adresu za proveru.")


async def check_site(site: dict) -> dict:
    result = {
        "name": u_latinicu(site["name"]),
        "url": site["url"],
        "ok": False,
        "slow": False,
        "status": None,
        "ms": 0,
        "error": None,
    }
    cfg, started = settings(), time.perf_counter()
    try:
        url = normalize_url(site["url"])
        result["url"] = str(url)
        async with asyncio.timeout(cfg.site_monitor_timeout_ms / 1000):
            # Bez keepalive-a isti IP kod dva redirect hosta ne deli tuđu TLS sesiju/SNI.
            async with httpx.AsyncClient(
                trust_env=False,
                follow_redirects=False,
                timeout=cfg.site_monitor_timeout_ms / 1000,
                limits=httpx.Limits(max_keepalive_connections=0),
            ) as client:
                for redirect in range(6):
                    status, target = await probe(client, url)
                    if status in {301, 302, 303, 307, 308}:
                        if not target or redirect == 5:
                            raise ValueError("Neispravno ili predugačko preusmeravanje.")
                        url = normalize_url(urljoin(str(url), target))
                        continue
                    result["status"] = status
                    result["ms"] = max(0, round(1000 * (time.perf_counter() - started)))
                    result["slow"] = status < 400 and result["ms"] > cfg.site_monitor_slow_ms
                    result["ok"] = status < 400 and not result["slow"]
                    result["error"] = f"HTTP {status}" if status >= 400 else None
                    return result
    except (TimeoutError, httpx.TimeoutException):
        result["error"] = f"timeout (>{cfg.site_monitor_timeout_ms} ms)"
    except (ValueError, httpx.InvalidURL) as exc:
        result["error"] = u_latinicu(str(exc))
    except (httpx.HTTPError, OSError):
        result["error"] = "Mrežna/DNS/TLS greška."
    result["ms"] = max(0, round(1000 * (time.perf_counter() - started)))
    return result


async def active_sites() -> list[dict]:
    async with notion.client() as api:
        source = await notion_clients.source(api)
        return [
            {
                "id": page["id"],
                "name": notion.title_of(page),
                "url": page["properties"]["Domen"]["url"],
            }
            async for page in notion.query_pages(
                api, source, {"property": "Aktivan", "select": {"equals": "Aktivan"}}
            )
            if (page.get("properties", {}).get("Domen", {}).get("url") or "").strip()
        ]


async def record(results: list[dict]) -> None:
    if not results:
        return
    now = datetime.now(UTC)
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(42702026)")
        await conn.executemany(
            "INSERT INTO monitor_checks(checked_at,name,url,ok,slow,status,ms,error) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            [
                (now, r["name"], r["url"], r["ok"], r["slow"], r["status"], r["ms"], r["error"])
                for r in results
            ],
        )
        await conn.execute(
            "DELETE FROM monitor_checks WHERE id IN (SELECT id FROM monitor_checks "
            "ORDER BY checked_at DESC,id DESC OFFSET $1)",
            MAX_HISTORY,
        )


async def check_all_sites() -> dict:
    sites = await active_sites()
    semaphore = asyncio.Semaphore(5)

    async def check(site):
        async with semaphore:
            return await check_site(site)

    results = await asyncio.gather(*(check(site) for site in sites))
    response = {
        "results": results,
        "problems": [r for r in results if not r["ok"]],
        "checked": len(results),
    }
    try:
        await record(results)
    except Exception as exc:
        log.warning("Istorija monitoringa nije upisana: %s", type(exc).__name__)
        response["napomena"] = "Provera je izvršena, ali njena istorija nije sačuvana."
    return response


async def uptime(days: int = 30, site: str | None = None) -> dict:
    if not 1 <= days <= 366:
        raise ValueError("Period dostupnosti mora biti 1–366 dana.")
    now = datetime.now(UTC)
    start = now - timedelta(days=days)
    rows = await db.pool().fetch(
        "SELECT checked_at,name,url,ok,status,error FROM monitor_checks "
        "WHERE checked_at >= $1 AND checked_at <= $2 ORDER BY checked_at,id",
        start,
        now,
    )
    groups = {}
    needle = u_latinicu(site or "").strip().casefold()
    for row in rows:
        if needle not in row["name"].casefold():
            continue
        group = groups.setdefault(
            row["name"],
            {
                "sajt": row["name"],
                "provera": 0,
                "uspesnih": 0,
                "brojPadova": 0,
                "poslednjiPad": None,
            },
        )
        group["url"] = row["url"]
        group["provera"] += 1
        group["uspesnih"] += int(row["ok"])
        if not row["ok"]:
            group["brojPadova"] += 1
            group["poslednjiPad"] = {
                "vreme": row["checked_at"].isoformat(),
                "greska": row["error"],
                "status": row["status"],
            }
    for group in groups.values():
        group["uptime"] = round(100 * group["uspesnih"] / group["provera"], 2)
    sites = sorted(groups.values(), key=lambda g: g["uptime"])
    total = sum(g["provera"] for g in sites)
    return {
        "dana": days,
        "odDatuma": start.date().isoformat(),
        "brojProvera": total,
        "sajtovi": sites,
        "ukupanUptime": round(100 * sum(g["uspesnih"] for g in sites) / total, 2)
        if total
        else None,
        "napomena": "Procenat uspešnih zabeleženih provera, ne neprekidno merena dostupnost. "
        "Spor odgovor se računa kao problem; istorija čuva najviše 8000 provera.",
        **(
            {"poruka": "Nema zabeleženih provera za taj period; istorija počinje prvom proverom."}
            if not total
            else {}
        ),
    }
