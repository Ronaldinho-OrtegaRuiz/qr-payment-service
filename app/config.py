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


def _cors_origins() -> tuple[str, ...]:
    raw = (os.getenv("CORS_ORIGINS") or "").strip()
    if raw:
        return tuple(o.strip() for o in raw.split(",") if o.strip())
    return (
        "http://localhost:3000",
        "https://drogueriasortegaqrs.vercel.app",
    )


def _bancol_search_phrases() -> tuple[str, ...]:
    multi = (os.getenv("BANCOL_SEARCH_PHRASES") or "").strip()
    if multi:
        parts = tuple(p.strip() for p in multi.split(",") if p.strip())
        if parts:
            return parts
    one = (os.getenv("BANCOL_SEARCH_PHRASE") or "").strip()
    if one:
        return (one,)
    return ("DROGUERIA RICKY", "yessi")


def _login_users_map() -> dict[str, str]:
    """Usuarios permitidos para POST /login: par ADMIN_* y par BASIC_* (cada uno opcional)."""
    out: dict[str, str] = {}
    u = (os.getenv("ADMIN_USER", "") or "").strip()
    p = (os.getenv("ADMIN_PASSWORD", "") or "").strip()
    if u and p:
        out[u] = p
    u2 = (os.getenv("BASIC_USER", "") or "").strip()
    p2 = (os.getenv("BASIC_PASSWORD", "") or "").strip()
    if u2 and p2:
        out[u2] = p2
    return out


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
    login_users: dict[str, str]
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    database_url: str = ""
    bancol_notifications_from: str = "alertasynotificaciones@an.notificacionesbancolombia.com"
    bancol_search_phrases: tuple[str, ...] = ("DROGUERIA RICKY", "yessi")
    drogueria_id: int = 1
    drogueria_secondary_id: int = 2
    drogueria_secondary_match: str = "yessi"
    payments_monitor_interval_sec: int = 10
    payments_monitor_enabled: bool = False
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "https://drogueriasortegaqrs.vercel.app",
    )


def get_settings() -> Settings:
    # utf-8-sig evita que un BOM al inicio del .env rompa la primera variable (p. ej. GMAIL_ACCOUNT_EMAIL).
    # override=False: en Railway/Render/etc. las variables del panel no las pisa un .env del repo o de la imagen.
    load_dotenv(_ENV_FILE, override=False, encoding="utf-8-sig")
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
        login_users=_login_users_map(),
        imap_host=(os.getenv("IMAP_HOST", "imap.gmail.com") or "imap.gmail.com").strip(),
        imap_port=_int_env("IMAP_PORT", 993),
        database_url=db_url,
        bancol_notifications_from=(
            os.getenv("BANCOL_IMAP_FROM", "").strip()
            or "alertasynotificaciones@an.notificacionesbancolombia.com"
        ),
        bancol_search_phrases=_bancol_search_phrases(),
        drogueria_id=_int_env("DROGUERIA_ID", 1),
        drogueria_secondary_id=_int_env("DROGUERIA_SECONDARY_ID", 2),
        drogueria_secondary_match=(
            os.getenv("DROGUERIA_SECONDARY_MATCH", "").strip() or "yessi"
        ),
        payments_monitor_interval_sec=max(
            5, _int_env("PAYMENTS_MONITOR_INTERVAL_SEC", 10)
        ),
        payments_monitor_enabled=_bool_env("PAYMENTS_MONITOR_ENABLED", monitor_default),
        cors_origins=_cors_origins(),
    )
