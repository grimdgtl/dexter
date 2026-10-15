"""Jednokratno Google odobrenje; refresh token korisnik prepisuje u svoj .env."""

import asyncio
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow

from apu.services.google import SCOPES


def authorize() -> str:
    load_dotenv()
    client_id, secret = os.getenv("GOOGLE_CLIENT_ID"), os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not secret:
        raise ValueError("Nedostaju GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET u .env.")
    redirect = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3000/oauth2callback")
    uri = urlsplit(redirect)
    if (
        uri.scheme != "http"
        or uri.hostname not in {"localhost", "127.0.0.1"}
        or uri.query
        or uri.fragment
    ):
        raise ValueError(
            "GOOGLE_REDIRECT_URI mora biti lokalni http callback bez upita i fragmenta."
        )
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect],
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect,
    )
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    outcome = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlsplit(self.path)
            if request.path != (uri.path or "/"):
                self.send_error(404, "Nepoznata putanja")
                return
            query = parse_qs(request.query)
            if not secrets.compare_digest(query.get("state", [""])[0], state):
                self.send_error(400, "Neispravna OAuth potvrda")
                return
            try:
                code = query.get("code", [""])[0]
                if not code or query.get("error"):
                    raise ValueError("Google odobrenje nije dato.")
                flow.fetch_token(code=code)
                token = flow.credentials.refresh_token
                if not token:
                    raise ValueError("Google nije vratio refresh token; ponovi odobrenje pristupa.")
                outcome["token"] = token
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("Uspešno! Vrati se u terminal.".encode())
            except Exception:
                outcome["error"] = "Greška pri razmeni Google koda."
                self.send_error(400, "Google odobrenje nije uspelo")

        def log_message(self, *args):
            # URL callback-a sadrži kod koji ne sme da završi u logovima.
            pass

    with HTTPServer((uri.hostname, uri.port or 80), Handler) as server:
        server.timeout = 1
        print(f"Otvori URL i odobri Calendar + Drive pristup:\n{url}")
        webbrowser.open(url)
        deadline = time.monotonic() + 300
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if "token" not in outcome:
        raise RuntimeError(outcome.get("error", "Isteklo je pet minuta za Google odobrenje."))
    return outcome["token"]


async def main() -> None:
    token = await asyncio.to_thread(authorize)
    print(f"Nalepi u svoj .env fajl:\nGOOGLE_REFRESH_TOKEN={token}")


if __name__ == "__main__":
    asyncio.run(main())
