"""Pravi Google SDK i OAuth transport, sa lažnim HTTP odgovorima."""

import threading
from urllib.parse import parse_qs

import httpx
import pytest
from googleapiclient.errors import HttpError

from apu import config
from apu.services import google

BASE = "https://www.googleapis.com/drive/v3/files"


@pytest.fixture(autouse=True)
def google_config(monkeypatch):
    for name in google.REQUIRES:
        monkeypatch.setenv(name, "test")
    config.settings.cache_clear()
    yield
    config.settings.cache_clear()


@pytest.fixture
def token(respx_mock):
    return respx_mock.post("https://oauth2.googleapis.com/token").respond(
        200, json={"access_token": "access-test", "expires_in": 3600, "token_type": "Bearer"}
    )


async def test_drive_search_refreshes_token_and_paginates(respx_mock, token):
    route = respx_mock.get(BASE).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "files": [{"id": "1", "name": "Prvi", "mimeType": google.DOC}],
                    "nextPageToken": "drugi",
                },
            ),
            httpx.Response(
                200, json={"files": [{"id": "2", "name": "Drugi", "mimeType": "text/plain"}]}
            ),
        ]
    )
    result = await google.search("Markov 'plan'\\", 2)
    assert [f["id"] for f in result] == ["1", "2"]
    assert token.call_count == 1
    assert route.calls[1].request.url.params["pageToken"] == "drugi"
    assert "\\'plan\\'\\\\" in route.calls[0].request.url.params["q"]
    assert route.calls[0].request.headers["authorization"] == "Bearer access-test"
    form = parse_qs(token.calls[0].request.content.decode())
    assert set(form["scope"][0].split()) == set(google.SCOPES)


@pytest.mark.parametrize(
    "mime,export", [(google.DOC, "text/plain"), (google.SHEET, "text/csv"), ("text/markdown", None)]
)
async def test_drive_read_exports_or_downloads_and_limits_model_text(
    respx_mock, token, mime, export
):
    respx_mock.get(
        f"{BASE}/1", params__contains={"fields": "id,name,mimeType,webViewLink"}
    ).respond(200, json={"id": "1", "name": "Документ", "mimeType": mime})
    if export:
        route = respx_mock.get(f"{BASE}/1/export", params__contains={"mimeType": export})
    else:
        route = respx_mock.get(f"{BASE}/1", params__contains={"alt": "media"})
    route.respond(200, content=("\ufeffТекст " * 1500).encode())
    result = await google.read("1")
    assert result["name"] == "Dokument" and result["content"].startswith("Tekst ")
    assert len(result["content"]) == 6000


async def test_drive_reads_pdf(respx_mock, token, pdf_bytes):
    respx_mock.get(
        f"{BASE}/1", params__contains={"fields": "id,name,mimeType,webViewLink"}
    ).respond(200, json={"id": "1", "name": "Dok.pdf", "mimeType": google.PDF})
    respx_mock.get(f"{BASE}/1", params__contains={"alt": "media"}).respond(200, content=pdf_bytes)
    assert "proveru indeksiranja PDF" in (await google.read("1"))["content"]


async def test_drive_create_uploads_text_as_google_doc_in_worker_thread(respx_mock, token):
    owner_thread = threading.get_ident()

    def upload(request):
        assert threading.get_ident() != owner_thread
        assert b"Sadrzaj" in request.content and google.DOC.encode() in request.content
        return httpx.Response(
            200,
            json={"id": "novo", "name": "Izveštaj", "webViewLink": "https://docs.google.com/novo"},
        )

    respx_mock.post("https://www.googleapis.com/upload/drive/v3/files").mock(side_effect=upload)
    assert (await google.create_doc("Izveštaj", "Sadrzaj"))["id"] == "novo"


async def test_drive_surfaces_permission_error(respx_mock, token):
    respx_mock.get(BASE).respond(403, json={"error": {"code": 403, "message": "Nema pristupa"}})
    with pytest.raises(HttpError):
        await google.search("test")


def test_auth_script_rejects_remote_callback(monkeypatch):
    from scripts import google_auth

    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.com/callback")
    with pytest.raises(ValueError, match="lokalni http"):
        google_auth.authorize()
