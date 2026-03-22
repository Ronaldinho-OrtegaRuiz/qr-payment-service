import imaplib
from dataclasses import dataclass

from app.config import Settings


def imap_connect_and_login(settings: Settings) -> imaplib.IMAP4_SSL:
    """Misma conexión y login que usa /imap/test (host, puerto, usuario, contraseña)."""
    client = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    client.login(
        settings.gmail_account_email.strip(),
        settings.app_password_gmail_account.strip(),
    )
    return client


@dataclass
class ImapTestResult:
    ok: bool
    message: str
    inbox_message_count: int | None = None


def test_imap_connection(settings: Settings) -> ImapTestResult:
    if not settings.gmail_account_email.strip():
        return ImapTestResult(
            ok=False,
            message="Falta GMAIL_ACCOUNT_EMAIL en .env",
        )
    if not settings.app_password_gmail_account.strip():
        return ImapTestResult(
            ok=False,
            message="Falta APP_PASSWORD_GMAIL_ACCOUNT en .env",
        )

    try:
        client = imap_connect_and_login(settings)
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            client.logout()
            return ImapTestResult(
                ok=False,
                message="No se pudo abrir INBOX (readonly)",
            )
        status, data = client.status("INBOX", "(MESSAGES)")
        count: int | None = None
        if status == "OK" and data and data[0]:
            # b'INBOX (MESSAGES 123)'
            raw = data[0].decode(errors="replace")
            if "MESSAGES" in raw:
                try:
                    count = int(raw.split("MESSAGES")[-1].strip().rstrip(")"))
                except ValueError:
                    count = None
        client.logout()
        return ImapTestResult(
            ok=True,
            message="Conexión IMAP correcta (login y lectura de INBOX)",
            inbox_message_count=count,
        )
    except imaplib.IMAP4.error as e:
        err_text = (
            e.args[0].decode(errors="replace")
            if e.args and isinstance(e.args[0], bytes)
            else str(e)
        )
        message = f"Error IMAP: {err_text}"
        if "AUTHENTICATIONFAILED" in err_text.upper():
            message += (
                " — Comprueba: email completo en .env (GMAIL_ACCOUNT_EMAIL); "
                "contraseña de aplicación de 16 caracteres (no la contraseña normal); "
                "verificación en 2 pasos activada; IMAP habilitado en Gmail."
            )
        return ImapTestResult(ok=False, message=message)
    except OSError as e:
        return ImapTestResult(
            ok=False,
            message=f"Error de red o SSL: {e!s}",
        )
