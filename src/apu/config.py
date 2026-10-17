"""Konfiguracija iz .env-a, sa tipovima i proverom pri pokretanju.

U staroj verziji je config.js ručno čitao process.env. Ovde pydantic-settings
radi isto, ali pukne odmah pri startu ako nešto obavezno fali ili ima pogrešan
tip — umesto da bot padne tek kad prvi put zatreba ta vrednost.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Obavezno
    telegram_bot_token: str
    telegram_owner_chat_id: int
    anthropic_api_key: str

    # Modeli
    model_fast: str = "claude-haiku-5-5"
    model_main: str = "claude-sonnet-5-5"
    model_deep: str = "claude-opus-5-5"
    max_tokens: int = 8192
    prompt_cache: Literal["on", "off"] = "on"
    router_mode: Literal["rule", "classifier"] = "rule"
    streaming: Literal["on", "off"] = "on"
    daily_budget_usd: Decimal | None = Field(None, gt=0, allow_inf_nan=False)

    database_url: str = "postgresql://apu:apu@localhost:5432/apu"

    embed_provider: Literal["openai", "local"] = "openai"
    chunk_chars: int = Field(2000, ge=100)
    chunk_overlap: int = Field(200, ge=0)
    rerank: Literal["on", "off"] = "off"
    rag_min_similarity: float = Field(0.3, ge=0, le=1)
    openai_api_key: str | None = None
    notion_api_key: str | None = None
    semantic_index_cron: str = "0 4 * * *"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_refresh_token: str | None = None
    google_redirect_uri: str = "http://localhost:3000/oauth2callback"
    google_calendar_id: str = "primary"
    imap_host: str | None = None
    imap_port: int = Field(993, ge=1, le=65535)
    imap_user: str | None = None
    imap_password: str | None = None
    mail_index_months: int = Field(12, ge=1)
    mail_index_exclude: str = ""
    mail_index_sent_folder: str | None = None

    transcribe_provider: Literal["openai", "local"] = "openai"
    whisper_local_model: str = "small"

    timezone: str = "Europe/Belgrade"
    weather_lat: float = 44.8125
    weather_lon: float = 20.4612
    weather_location: str = "Beograd"

    history_turns: int = 12
    log_level: str = "INFO"

    @model_validator(mode="after")
    def valid_chunking(self):
        if self.chunk_overlap >= self.chunk_chars:
            raise ValueError("CHUNK_OVERLAP mora biti manji od CHUNK_CHARS.")
        return self

    @property
    def embed_dim(self) -> int:
        """Dimenzija vektora zavisi od modela — baza mora da je zna unapred."""
        return 1536 if self.embed_provider == "openai" else 384


@lru_cache
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
