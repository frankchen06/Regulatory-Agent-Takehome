"""Secrets come from .env; everything else is a plain constant."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

UARB_URL = "https://uarb.novascotia.ca/fmi/webd/UARB15"
ANTHROPIC_MODEL = "claude-haiku-5-5"
MAX_DOCS = 10
POLL_INTERVAL_SECONDS = 30
DOWNLOAD_DIR = Path("downloads")
DEBUG_DIR = Path("debug")

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
AGENT_TAG = "uarb"  # the agent only reads mail sent to yourname+uarb@gmail.com


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gmail_address: str = ""
    gmail_app_password: str = ""  # Gmail App Password, not the account password
    anthropic_api_key: str = ""
    allowed_senders: list[str] = []  # only these addresses get replies; empty means nobody does
    headless: bool = True  # set HEADLESS=false to watch the browser

    @property
    def agent_address(self) -> str:
        """yourname@gmail.com -> yourname+uarb@gmail.com"""
        local, _, domain = self.gmail_address.partition("@")
        return f"{local}+{AGENT_TAG}@{domain}"


settings = Settings()
