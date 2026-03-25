"""Lectura de correos Bancolombia por IMAP (texto del mensaje + cabeceras para el parser)."""

from __future__ import annotations

import email
import imaplib
import logging
import re
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from email.message import Message

from app.config import Settings
from app.services.bancolombia.parser import parse_bancolombia_pago_text
from app.services.imap.client import imap_connect_and_login

logger = logging.getLogger(__name__)


def html_to_searchable_text(html: str) -> str:
    t = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style.*?>.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())


def message_best_text(msg: Message) -> str:
    if msg.is_multipart():
        plain: str | None = None
        html: str | None = None
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    ch = part.get_content_charset() or "utf-8"
                    plain = payload.decode(ch, errors="replace")
                    break
            if ctype == "text/html" and html is None:
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    ch = part.get_content_charset() or "utf-8"
                    html = payload.decode(ch, errors="replace")
        if plain:
            return plain
        if html:
            return html_to_searchable_text(html)
        return ""
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        ch = msg.get_content_charset() or "utf-8"
        raw = payload.decode(ch, errors="replace")
    else:
        raw = str(payload or "")
    if msg.get_content_type() == "text/html":
        return html_to_searchable_text(raw)
    return raw


def _imap_escape_atom(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _or_text_criteria(phrases: Sequence[str]) -> str:
    cleaned = [_imap_escape_atom(p.strip()) for p in phrases if p and p.strip()]
    if not cleaned:
        return 'TEXT ""'
    if len(cleaned) == 1:
        return f'TEXT "{cleaned[0]}"'
    clause = f'TEXT "{cleaned[0]}"'
    for p in cleaned[1:]:
        clause = f'(OR {clause} TEXT "{p}")'
    return clause


def imap_search_criteria(
    *,
    since_year: int,
    from_email: str,
    contains_text_phrases: Sequence[str],
    min_uid_exclusive: int | None = None,
) -> str:
    since = f"1-Jan-{since_year}"
    text_part = _or_text_criteria(contains_text_phrases)
    from_esc = _imap_escape_atom(from_email)
    inner = f"SINCE {since} FROM \"{from_esc}\" {text_part}"
    if min_uid_exclusive is not None and min_uid_exclusive >= 0:
        lo = min_uid_exclusive + 1
        return f"(UID {lo}:* {inner})"
    return f"({inner})"


def mail_to_entry(uid: str, msg: Message, search_phrases: Sequence[str]) -> dict:
    subject = msg.get("Subject", "") or ""
    date_hdr = msg.get("Date", "") or ""
    message_id = (msg.get("Message-ID") or "").strip()
    body = message_best_text(msg)
    combined = f"{subject}\n{body}"
    parsed = parse_bancolombia_pago_text(combined)
    entry: dict = {
        "uid": uid,
        "message_id": message_id,
        "subject": subject,
        "date_header": date_hdr,
        "parse_ok": parsed is not None,
        "keyword_in_subject": (
            bool([p for p in search_phrases if p and str(p).strip()])
            and any(
                str(p).strip().upper() in subject.upper()
                for p in search_phrases
                if p and str(p).strip()
            )
        ),
    }
    if parsed:
        entry["drogueria"] = parsed.drogueria
        entry["nombre_cliente"] = parsed.nombre_cliente
        entry["valor"] = parsed.valor
        entry["fecha"] = parsed.fecha
        entry["hora"] = parsed.hora
    else:
        entry["raw_snippet"] = combined[:400].replace("\n", " ").strip()
    return entry


def fetch_rfc822_message(client: imaplib.IMAP4_SSL, uid: bytes) -> Message | None:
    st, fetch_data = client.fetch(uid, "(RFC822)")
    if st != "OK" or not fetch_data:
        return None
    raw = None
    for item in fetch_data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            raw = item[1]
            break
    if not raw:
        return None
    return email.message_from_bytes(raw)


def poll_uids_after(
    settings: Settings,
    *,
    from_email: str,
    search_phrases: Sequence[str],
    last_uid: int,
) -> tuple[list[dict], int]:
    """
    Busca correos que cumplen criterio con UID > last_uid.
    Devuelve (lista de entradas tipo JSON fetch, nuevo_last_uid).
    """
    if not settings.gmail_account_email.strip() or not settings.app_password_gmail_account.strip():
        raise RuntimeError("Faltan credenciales IMAP en .env")

    year = datetime.now(timezone.utc).year
    criteria = imap_search_criteria(
        since_year=year,
        from_email=from_email,
        contains_text_phrases=search_phrases,
        min_uid_exclusive=last_uid,
    )

    entries: list[dict] = []
    new_last = last_uid

    t0 = time.perf_counter()
    logger.info(
        "[IMAP poll_uids_after] inicio last_uid=%s criterio=%r frases=%s",
        last_uid,
        criteria,
        list(search_phrases),
    )

    t_conn = time.perf_counter()
    client = imap_connect_and_login(settings)
    logger.info(
        "[IMAP poll_uids_after] conectado + login en %.0f ms",
        (time.perf_counter() - t_conn) * 1000,
    )
    try:
        t_sel = time.perf_counter()
        client.select("INBOX", readonly=True)
        logger.info(
            "[IMAP poll_uids_after] SELECT INBOX en %.0f ms",
            (time.perf_counter() - t_sel) * 1000,
        )

        t_search = time.perf_counter()
        status, data = client.search(None, criteria)
        search_ms = (time.perf_counter() - t_search) * 1000
        if status != "OK" or not data or not data[0]:
            uids: list[bytes] = []
            logger.info(
                "[IMAP poll_uids_after] SEARCH status=%s uids=0 en %.0f ms",
                status,
                search_ms,
            )
        else:
            uids = data[0].split()
            logger.info(
                "[IMAP poll_uids_after] SEARCH status=%s uids=%d en %.0f ms",
                status,
                len(uids),
                search_ms,
            )

        for uid in sorted(uids, key=lambda u: int(u.decode())):
            uid_int = int(uid.decode())
            t_fetch = time.perf_counter()
            msg = fetch_rfc822_message(client, uid)
            fetch_ms = (time.perf_counter() - t_fetch) * 1000
            if msg is None:
                logger.warning(
                    "[IMAP poll_uids_after] UID %s FETCH falló o vacío (%.0f ms)",
                    uid_int,
                    fetch_ms,
                )
                continue
            entry = mail_to_entry(uid.decode(), msg, search_phrases)
            subj = (entry.get("subject") or "")[:120]
            logger.info(
                "[IMAP poll_uids_after] UID %s FETCH OK %.0f ms | parse_ok=%s keyword_in_subject=%s | subject=%r",
                uid_int,
                fetch_ms,
                entry.get("parse_ok"),
                entry.get("keyword_in_subject"),
                subj,
            )
            entries.append(entry)
            new_last = max(new_last, uid_int)
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass

    total_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "[IMAP poll_uids_after] fin entries=%d new_last_uid=%s total %.0f ms",
        len(entries),
        new_last,
        total_ms,
    )

    return entries, new_last


def bootstrap_last_uid(
    settings: Settings,
    *,
    from_email: str,
    search_phrases: Sequence[str],
) -> int:
    """Mayor UID que cumple el criterio (sin devolver mensajes). Evita insertar histórico al arrancar."""
    year = datetime.now(timezone.utc).year
    criteria = imap_search_criteria(
        since_year=year,
        from_email=from_email,
        contains_text_phrases=search_phrases,
        min_uid_exclusive=None,
    )
    t0 = time.perf_counter()
    logger.info(
        "[IMAP bootstrap_last_uid] inicio criterio=%r frases=%s",
        criteria,
        list(search_phrases),
    )
    client = imap_connect_and_login(settings)
    try:
        client.select("INBOX", readonly=True)
        status, data = client.search(None, criteria)
        if status != "OK" or not data or not data[0]:
            logger.info(
                "[IMAP bootstrap_last_uid] SEARCH sin resultados status=%s en %.0f ms",
                status,
                (time.perf_counter() - t0) * 1000,
            )
            return 0
        uids = [int(u.decode()) for u in data[0].split()]
        m = max(uids) if uids else 0
        logger.info(
            "[IMAP bootstrap_last_uid] SEARCH uids coincidentes=%d max_uid=%s total %.0f ms",
            len(uids),
            m,
            (time.perf_counter() - t0) * 1000,
        )
        return m
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass
