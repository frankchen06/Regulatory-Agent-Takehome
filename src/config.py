"""Secrets come from .env; everything else is a plain constant."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

UARB_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
ANTHROPIC_MODEL = "claude-haiku-5-5"
MAX_DOCS = 10
POLL_INTERVAL_SECONDS = 30
DOWNLOAD_DIR = Path("downloads")
DEBUG_DIR = Path("debug")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_address: str = ""
    gmail_app_password: str = ""  # Gmail App Password, not the account password
    anthropic_api_key: str = ""
    headless: bool = True  # set HEADLESS=false to watch the browser


settings = Settings()
