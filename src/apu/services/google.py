"""Zajednički Google OAuth i izolovani SDK klijenti po operaciji."""

import asyncio
import io
from collections.abc import AsyncIterator
from pathlib import Path

import google_auth_httplib2
import httplib2
import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from apu.config import settings
from apu.pismo import u_latinicu
from apu.rag import office
from apu.rag.ingest import read_pdf

SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive"]
REQUIRES = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]
DOC = "application/vnd.google-apps.document"
SHEET = "application/vnd.google-apps.spreadsheet"
PDF = "application/pdf"


def configured() -> bool:
    return all(getattr(settings(), name.lower()) for name in REQUIRES)


def credentials() -> Credentials:
    if not configured():
        raise RuntimeError(
            "Google traži GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET i GOOGLE_REFRESH_TOKEN."
        )
    cfg = settings()
    return Credentials(
        token=None,
        refresh_token=cfg.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        scopes=SCOPES,
    )


class HttpxTransport:
    """SDK i osvežavanje tokena koriste isti HTTP transport, dostupan respx testovima."""

    def __init__(self):
        self.client = httpx.Client(timeout=60, follow_redirects=True)

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        response = self.client.request(method, uri, content=body, headers=headers)
        meta = httplib2.Response({**response.headers, "status": str(response.status_code)})
        return meta, response.content

    def close(self):
        self.client.close()


def build_service(name: str, version: str):
    transport = HttpxTransport()
    try:
        auth = google_auth_httplib2.AuthorizedHttp(credentials(), http=transport)
        # Statička discovery šema iz paketa izbegava mrežni poziv pri izradi klijenta.
        return build(name, version, http=auth, cache_discovery=False, static_discovery=True)
    except BaseException:
        transport.close()
        raise


def indexable(meta: dict) -> bool:
    mime = meta.get("mimeType", "")
    return (
        mime in {DOC, SHEET, PDF, "application/json"}
        or mime in office.MIMES
        or mime.startswith("text/")
        or Path(meta.get("name", "")).suffix.lower() in ({".txt", ".md"} | office.SUFFIXES)
    )


def escape_query(query: str) -> str:
    return query.replace("\\", "\\\\").replace("'", "\\'")


class Drive:
    async def __aenter__(self):
        # SDK ima sinhroni transport i nije bezbedan za deljenje između paralelnih zahteva.
        self.api = await asyncio.to_thread(build_service, "drive", "v3")
        return self

    async def __aexit__(self, *args):
        await asyncio.to_thread(self.api.close)

    async def call(self, method: str, **kwargs):
        def execute():
            return getattr(self.api.files(), method)(**kwargs).execute()

        return await asyncio.to_thread(execute)

    async def files(self, query: str = "", limit: int | None = None) -> AsyncIterator[dict]:
        q = "trashed = false"
        if query:
            escaped = escape_query(query)
            q += f" and (name contains '{escaped}' or fullText contains '{escaped}')"
        cursor = None
        seen = set()
        count = 0
        while True:
            result = await self.call(
                "list",
                q=q,
                pageSize=min(100, limit - count) if limit else 100,
                pageToken=cursor,
                orderBy="modifiedTime desc",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="nextPageToken,incompleteSearch,files(id,name,mimeType,modifiedTime,webViewLink)",
            )
            if result.get("incompleteSearch"):
                raise RuntimeError("Drive pretraga nije potpuna; indeks nije očišćen.")
            for meta in result.get("files", []):
                yield meta
                count += 1
                if limit and count >= limit:
                    return
            cursor = result.get("nextPageToken")
            if not cursor:
                return
            if cursor in seen:
                raise RuntimeError("Drive je ponovio token paginacije.")
            seen.add(cursor)

    async def read(self, file_id: str, meta: dict | None = None) -> dict:
        meta = meta or await self.call(
            "get", fileId=file_id, fields="id,name,mimeType,webViewLink", supportsAllDrives=True
        )
        mime = meta.get("mimeType", "")
        if mime in {DOC, SHEET}:
            data = await self.call(
                "export_media", fileId=file_id, mimeType="text/plain" if mime == DOC else "text/csv"
            )
        elif indexable(meta):
            data = await self.call("get_media", fileId=file_id, supportsAllDrives=True)
        else:
            return {
                "id": file_id,
                "name": meta.get("name"),
                "type": mime,
                "content": f"Fajl tipa {mime} nije tekstualni — ne mogu da ga pročitam ovde.",
            }
        suffix = Path(meta.get("name", "")).suffix.lower()
        if mime == PDF:
            text = await read_pdf(data)
        elif mime not in {DOC, SHEET} and (mime in office.MIMES or suffix in office.SUFFIXES):
            name = "fajl" + office.MIMES.get(mime, suffix)
            text = await asyncio.to_thread(office.text, name, data)
        else:
            text = data.decode("utf-8-sig", errors="replace")
        return {
            "id": file_id,
            "name": u_latinicu(meta.get("name", "")),
            "type": mime,
            "content": u_latinicu(text),
        }


async def search(query: str, limit: int = 10) -> list[dict]:
    async with Drive() as drive:
        return [
            {
                "id": f["id"],
                "name": u_latinicu(f["name"]),
                "type": f["mimeType"],
                "modified": f.get("modifiedTime"),
                "link": f.get("webViewLink"),
            }
            async for f in drive.files(query, limit)
        ]


async def read(file_id: str) -> dict:
    async with Drive() as drive:
        result = await drive.read(file_id)
        result["content"] = result["content"][:6000]
        return result


async def create_doc(name: str, content: str) -> dict:
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")), mimetype="text/plain", resumable=False
    )
    async with Drive() as drive:
        result = await drive.call(
            "create",
            body={"name": name, "mimeType": DOC},
            media_body=media,
            fields="id,name,webViewLink",
        )
        return {"id": result["id"], "name": result["name"], "link": result.get("webViewLink")}
