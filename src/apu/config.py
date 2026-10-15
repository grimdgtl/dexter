"""Konfiguracija iz .env-a, sa tipovima i proverom pri pokretanju.

U staroj verziji je config.js ručno čitao process.env. Ovde pydantic-settings
radi isto, ali pukne odmah pri startu ako nešto obavezno fali ili ima pogrešan
tip — umesto da bot padne tek kad prvi put zatreba ta vrednost.
"""

from functools import lru_cache
from typing import Literal

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

    database_url: str = "postgresql://apu:apu@localhost:5432/apu"

    embed_provider: Literal["openai", "local"] = "openai"
    openai_api_key: str | None = None

    transcribe_provider: Literal["openai", "local"] = "openai"
    whisper_local_model: str = "small"

    timezone: str = "Europe/Belgrade"
    weather_lat: float = 44.8125
    weather_lon: float = 20.4612
    weather_location: str = "Beograd"

    history_turns: int = 12
    log_level: str = "INFO"

    @property
    def embed_dim(self) -> int:
        """Dimenzija vektora zavisi od modela — baza mora da je zna unapred."""
        return 1536 if self.embed_provider == "openai" else 384


@lru_cache
def settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
