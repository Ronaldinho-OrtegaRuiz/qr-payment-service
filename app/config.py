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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    s = str(raw).strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    return s in ("1", "true", "yes", "on", "si", "sí")


@dataclass(frozen=True)
class Settings:
    api_key: str
    gmail_account_email: str
    app_password_gmail_account: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    database_url: str = ""
    bancol_notifications_from: str = "alertasynotificaciones@an.notificacionesbancolombia.com"
    bancol_search_phrase: str = "DROGUERIA RICKY"
    drogueria_id: int = 1
    payments_monitor_interval_sec: int = 10
    payments_monitor_enabled: bool = False


def get_settings() -> Settings:
    # utf-8-sig evita que un BOM al inicio del .env rompa la primera variable (p. ej. GMAIL_ACCOUNT_EMAIL).
    load_dotenv(_ENV_FILE, override=True, encoding="utf-8-sig")
    db_url = (
        os.getenv("DATABASE_URL", "").strip()
        or os.getenv("SUPABASE_DATABASE_URL", "").strip()
    )
    monitor_default = bool(db_url and os.getenv("GMAIL_ACCOUNT_EMAIL", "").strip())
    return Settings(
        api_key=(os.getenv("API_KEY", "") or "").strip(),
        gmail_account_email=os.getenv("GMAIL_ACCOUNT_EMAIL", "").strip(),
        app_password_gmail_account=os.getenv("APP_PASSWORD_GMAIL_ACCOUNT", "")
        .replace(" ", "")
        .strip(),
        imap_host=(os.getenv("IMAP_HOST", "imap.gmail.com") or "imap.gmail.com").strip(),
        imap_port=_int_env("IMAP_PORT", 993),
        database_url=db_url,
        bancol_notifications_from=(
            os.getenv("BANCOL_IMAP_FROM", "").strip()
            or "alertasynotificaciones@an.notificacionesbancolombia.com"
        ),
        bancol_search_phrase=(
            os.getenv("BANCOL_SEARCH_PHRASE", "").strip() or "DROGUERIA RICKY"
        ),
        drogueria_id=_int_env("DROGUERIA_ID", 1),
        payments_monitor_interval_sec=max(
            5, _int_env("PAYMENTS_MONITOR_INTERVAL_SEC", 10)
        ),
        payments_monitor_enabled=_bool_env("PAYMENTS_MONITOR_ENABLED", monitor_default),
    )
