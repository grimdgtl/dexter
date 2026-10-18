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

    database_url: str = "postgresql://dexter:dexter@localhost:5432/dexter"

    embed_provider: Literal["openai", "local"] = "openai"
    embed_local_model: Literal[
        "intfloat/multilingual-e5-small", "intfloat/multilingual-e5-base"
    ] = "intfloat/multilingual-e5-small"
    chunk_chars: int = Field(2000, ge=100)
    chunk_overlap: int = Field(200, ge=0)
    rerank: Literal["on", "off"] = "off"
    rag_min_similarity: float = Field(0.3, ge=0, le=1)
    openai_api_key: str | None = None
    notion_api_key: str | None = None
    notion_tasks_db_id: str | None = None
    notion_clients_db_id: str | None = None
    notion_kb_page_id: str | None = None
    notion_invoices_db_id: str | None = None
    notion_birthdays_db_id: str | None = None
    site_monitor_timeout_ms: int = Field(15000, ge=100, le=120000)
    site_monitor_slow_ms: int = Field(5000, ge=1, le=120000)
    google_invoices_folder_id: str | None = None
    invoice_last_number: str | None = None
    invoice_issuer_name: str | None = None
    invoice_issuer_brand: str | None = None
    invoice_issuer_address: str | None = None
    invoice_issuer_city: str | None = None
    invoice_issuer_phone: str | None = None
    invoice_issuer_pib: str | None = None
    invoice_issuer_mb: str | None = None
    invoice_issuer_account: str | None = None
    invoice_issuer_bank: str | None = None
    invoice_responsible_person: str | None = None
    invoice_logo_path: str | None = None
    invoice_comment: str = "Račun je važeći bez pečata i potpisa."
    invoice_vat_note: str = "Pravno lice nije u sistemu PDV-a."
    notion_todo_db_id: str | None = None
    notion_checklist_db_id: str | None = None
    notion_dnevnik_db_id: str | None = None
    checklist_pozitivne: str = "Ustajanje 6:00, Vežbanje, Doručak, Vitamini, Večera 19:00"
    checklist_izbegavanja: str = "Bez slatkog, Bez alkohola, Bez telefona posle 22:00"
    checklist_ciljna_stavka: str = "Vežbanje"
    checklist_cilj_nedeljno: int = Field(3, ge=1, le=7)
    weekly_task_title: str = Field("Nedeljni zadatak", min_length=1, max_length=2000)
    flowers_task_cron: str = "0 5 * * 1"
    scheduler_enabled: Literal["on", "off"] = "on"
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
    smtp_host: str | None = None
    smtp_port: int = Field(465, ge=1, le=65535)
    smtp_secure: bool = True
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from_name: str = ""
    mail_from_address: str | None = None
    resend_api_key: str | None = None
    mail_index_months: int = Field(12, ge=1)
    mail_index_exclude: str = ""
    mail_index_sent_folder: str | None = None

    transcribe_provider: Literal["openai", "local"] = "openai"
    whisper_local_model: str = "small"
    ocr_max_pages: int = Field(20, ge=1, le=100)
    glas_odgovor: Literal["on", "off"] = "off"
    tts_model: str = Field("gpt-4o-mini-tts", min_length=1)
    tts_voice: str = Field("coral", min_length=1)

    timezone: str = "Europe/Belgrade"
    quiet_hours: str = Field("22-07", pattern=r"^\d{2}-\d{2}$")
    weather_lat: float = 44.8125
    weather_lon: float = 20.4612
    weather_location: str = "Beograd"

    history_turns: int = Field(12, ge=1)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def valid_chunking(self):
        if self.chunk_overlap >= self.chunk_chars:
            raise ValueError("CHUNK_OVERLAP mora biti manji od CHUNK_CHARS.")
        if any(int(h) > 23 for h in self.quiet_hours.split("-")):
            raise ValueError("QUIET_HOURS koristi sate 00–23, npr. 22-07.")
        return self

    @property
    def embed_dim(self) -> int:
        """Dimenzija vektora zavisi od modela — baza mora da je zna unapred."""
        return (
            1536
            if self.embed_provider == "openai"
            else (384 if self.embed_local_model.endswith("-small") else 768)
        )

    @property
    def embed_model(self) -> str:
        return (
            "text-embedding-3-small" if self.embed_provider == "openai" else self.embed_local_model
        )


@lru_cache
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
