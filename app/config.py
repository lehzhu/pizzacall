from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    public_base_url: str = "http://127.0.0.1:8000"
    log_dir: Path = Field(default=Path("logs"))
    artifact_dir: Path = Field(default=Path("artifacts"))

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    deepgram_api_key: str | None = None
    cartesia_api_key: str | None = None
    groq_api_key: str | None = None

    groq_model: str = "llama-3.3-70b-versatile"
    cartesia_voice_id: str = "694f9389-aac1-45b6-b726-9d9369183238"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    return settings

