import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gmail_account_email: str
    app_password_gmail_account: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    database_url: str = ""


def get_settings() -> Settings:
    # utf-8-sig evita que un BOM al inicio del .env rompa la primera variable (p. ej. GMAIL_ACCOUNT_EMAIL).
    load_dotenv(_ENV_FILE, override=True, encoding="utf-8-sig")
    return Settings(
        gmail_account_email=os.getenv("GMAIL_ACCOUNT_EMAIL", "").strip(),
        app_password_gmail_account=os.getenv("APP_PASSWORD_GMAIL_ACCOUNT", "")
        .replace(" ", "")
        .strip(),
        imap_host=(os.getenv("IMAP_HOST", "imap.gmail.com") or "imap.gmail.com").strip(),
        imap_port=_int_env("IMAP_PORT", 993),
        database_url=(
            os.getenv("DATABASE_URL", "").strip()
            or os.getenv("SUPABASE_DATABASE_URL", "").strip()
        ),
    )
