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
HANDLED_LABEL = "UARB-handled"  # Gmail label the agent adds to each request once it's dealt with


class Settings(BaseSettings):
    # Strip stray spaces and newlines, e.g. from pasting a secret into GitHub. A key with a
    # trailing newline makes every Claude request fail with a confusing connection error.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", str_strip_whitespace=True)

    gmail_address: str = ""
    gmail_app_password: str = ""  # Gmail App Password, not the account password
    anthropic_api_key: str = ""
    headless: bool = True  # set HEADLESS=false to watch the browser

    @property
    def agent_address(self) -> str:
        """yourname@gmail.com -> yourname+uarb@gmail.com"""
        local, _, domain = self.gmail_address.partition("@")
        return f"{local}+{AGENT_TAG}@{domain}"


settings = Settings()
