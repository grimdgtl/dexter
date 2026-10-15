"""Notion HTTP se uvek zamenjuje respx odgovorima."""

import json

import httpx
import pytest
from notion_client import APIResponseError

from apu import config
from apu.services import notion

ROOT = "11111111-1111-1111-1111-111111111111"
CHILD = "22222222-2222-2222-2222-222222222222"
BASE = "https://api.notion.com/v1"


@pytest.fixture(autouse=True)
def configured_notion(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "test-notion")
    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


async def test_search_paginates_and_preserves_limit(respx_mock):
    route = respx_mock.post(f"{BASE}/search").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [{"id": ROOT, "object": "page", "properties": {}}],
                    "has_more": True,
                    "next_cursor": "sledeci",
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [{"id": CHILD, "object": "data_source", "title": []}],
                    "has_more": False,
                },
            ),
        ]
    )
    result = await notion.search("beleška", 2)
    assert len(result) == 2 and result[1]["type"] == "data_source"
    body = json.loads(route.calls[1].request.content)
    assert body["start_cursor"] == "sledeci" and body["page_size"] == 1
    assert route.calls[0].request.headers["Notion-Version"] == "2025-09-03"


async def test_read_page_paginates_and_reads_child_pages(respx_mock):
    respx_mock.get(f"{BASE}/blocks/{ROOT}/children").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "results": [
                        {"id": CHILD, "type": "child_page", "child_page": {"title": "Подстраница"}},
                    ],
                    "has_more": True,
                    "next_cursor": "jos",
                },
            ),
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "type": "table_row",
                            "table_row": {
                                "cells": [[{"plain_text": "Prva"}], [{"plain_text": "Druga"}]]
                            },
                        }
                    ],
                    "has_more": False,
                },
            ),
        ]
    )
    respx_mock.get(f"{BASE}/blocks/{CHILD}/children").respond(
        200,
        json={
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"plain_text": "Tekst deteta."}]},
                },
                {"id": ROOT, "type": "child_page", "child_page": {"title": "Već viđena"}},
            ],
            "has_more": False,
        },
    )
    result = await notion.read_page(ROOT)
    assert "Podstranica\nTekst deteta." in result["text"]
    assert "Prva | Druga" in result["text"]


async def test_notion_reports_permission_failure(respx_mock):
    respx_mock.post(f"{BASE}/search").respond(
        403,
        json={
            "object": "error",
            "status": 403,
            "code": "restricted_resource",
            "message": "Pristup nije dozvoljen",
        },
    )
    with pytest.raises(APIResponseError):
        await notion.search("test")
