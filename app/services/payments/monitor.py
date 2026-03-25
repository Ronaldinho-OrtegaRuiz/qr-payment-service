"""
Polling IMAP: monitor en background + ronda manual vía POST /payments/poll-now.

Comparten last_uid y un lock para no solapar consultas IMAP.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import Settings, get_settings
from app.services.bancolombia.imap_mail import bootstrap_last_uid, poll_uids_after
from app.services.payments.monitor_state import PaymentMonitorState
from app.services.payments.drogueria_routing import resolve_drogueria_id_for_entry
from app.services.payments.repository import (
    get_payments_timezone,
    insert_payment_if_new,
    mail_entry_to_row,
)
from app.services.payments.ws_hub import PaymentWsHub

logger = logging.getLogger(__name__)


async def run_payment_poll_round(
    settings: Settings,
    hub: PaymentWsHub,
    state: PaymentMonitorState,
) -> dict:
    """
    Una pasada: bootstrap si last_uid==0; si no, busca correos nuevos, inserta y notifica WS.
    Devuelve JSON para el endpoint (sin excepciones de negocio).
    """
    t_round = time.perf_counter()
    logger.info(
        "[payment poll] === ronda inicio | last_uid=%s bancol_from=%r frases=%s",
        state.last_uid,
        settings.bancol_notifications_from,
        list(settings.bancol_search_phrases),
    )

    if not settings.database_url.strip():
        logger.warning("[payment poll] abort: falta DATABASE_URL")
        return {
            "ok": False,
            "message": "Falta DATABASE_URL en .env.",
            "new_count": 0,
            "new_payments": [],
            "last_uid": state.last_uid,
            "bootstrapped": False,
        }
    if not settings.gmail_account_email.strip() or not settings.app_password_gmail_account.strip():
        logger.warning("[payment poll] abort: faltan credenciales IMAP")
        return {
            "ok": False,
            "message": "Faltan GMAIL_ACCOUNT_EMAIL o APP_PASSWORD_GMAIL_ACCOUNT en .env.",
            "new_count": 0,
            "new_payments": [],
            "last_uid": state.last_uid,
            "bootstrapped": False,
        }

    new_payments: list[dict] = []
    bootstrapped = False
    message = ""

    async with state.lock:
        logger.info("[payment poll] lock adquirido | last_uid=%s", state.last_uid)
        if state.last_uid == 0:
            logger.info("[payment poll] rama: bootstrap (last_uid era 0)")
            t_bs = time.perf_counter()
            state.last_uid = await asyncio.to_thread(
                bootstrap_last_uid,
                settings,
                from_email=settings.bancol_notifications_from,
                search_phrases=settings.bancol_search_phrases,
            )
            logger.info(
                "[payment poll] bootstrap terminado en %.0f ms → last_uid=%s",
                (time.perf_counter() - t_bs) * 1000,
                state.last_uid,
            )
            bootstrapped = True
            message = (
                f"Puntero IMAP listo (último UID conocido: {state.last_uid}). "
                "No se cargaron correos antiguos; los próximos aparecerán aquí o por WebSocket."
            )
        else:
            prev_uid = state.last_uid
            logger.info("[payment poll] rama: poll_uids_after desde last_uid=%s", prev_uid)
            t_imap = time.perf_counter()
            entries, state.last_uid = await asyncio.to_thread(
                poll_uids_after,
                settings,
                from_email=settings.bancol_notifications_from,
                search_phrases=settings.bancol_search_phrases,
                last_uid=state.last_uid,
            )
            logger.info(
                "[payment poll] IMAP thread listo en %.0f ms | entries=%d last_uid %s → %s",
                (time.perf_counter() - t_imap) * 1000,
                len(entries),
                prev_uid,
                state.last_uid,
            )
            tz = get_payments_timezone()
            for i, entry in enumerate(entries):
                uid = entry.get("uid")
                logger.info(
                    "[payment poll] procesando entry %d/%s uid=%s parse_ok=%s",
                    i + 1,
                    len(entries),
                    uid,
                    entry.get("parse_ok"),
                )
                did = resolve_drogueria_id_for_entry(settings, entry)
                logger.info(
                    "[payment poll] uid=%s drogueria_id resuelto=%s",
                    uid,
                    did,
                )
                row = mail_entry_to_row(entry, did, tz)
                if not row:
                    logger.info(
                        "[payment poll] uid=%s sin fila (parser/validación); se omite insert",
                        uid,
                    )
                    continue
                t_db = time.perf_counter()
                saved = await asyncio.to_thread(insert_payment_if_new, settings, row)
                logger.info(
                    "[payment poll] uid=%s insert_payment_if_new en %.0f ms | nuevo=%s",
                    uid,
                    (time.perf_counter() - t_db) * 1000,
                    bool(saved),
                )
                if saved:
                    logger.info(
                        "[payment poll] pago nuevo message_id=%s → broadcast WS",
                        saved.get("message_id"),
                    )
                    new_payments.append(saved)
                    await hub.broadcast_new_payment(saved)
                    logger.info("[payment poll] broadcast WS enviado para uid=%s", uid)

            if new_payments:
                message = f"Se registraron {len(new_payments)} pago(s) nuevo(s)."
            elif entries:
                message = (
                    f"Se revisaron {len(entries)} correo(s) nuevo(s); "
                    "ninguno coincidió como pago parseable o ya estaban en la BD."
                )
            else:
                message = "No había correos nuevos desde el último chequeo."

    logger.info(
        "[payment poll] === ronda fin en %.0f ms | ok bootstrapped=%s new_count=%s last_uid=%s | %s",
        (time.perf_counter() - t_round) * 1000,
        bootstrapped,
        len(new_payments),
        state.last_uid,
        message[:200] if message else "",
    )

    return {
        "ok": True,
        "bootstrapped": bootstrapped,
        "message": message,
        "new_count": len(new_payments),
        "new_payments": new_payments,
        "last_uid": state.last_uid,
    }


async def payment_monitor_loop(
    hub: PaymentWsHub,
    stop: asyncio.Event,
    state: PaymentMonitorState,
) -> None:
    while not stop.is_set():
        settings = get_settings()
        if not settings.payments_monitor_enabled or not settings.database_url.strip():
            logger.info(
                "[payment monitor_loop] inactivo (enabled=%s db=%s); espera 60s",
                settings.payments_monitor_enabled,
                bool(settings.database_url.strip()),
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
            continue

        interval = settings.payments_monitor_interval_sec
        logger.info(
            "[payment monitor_loop] ciclo: ejecutar ronda (intervalo siguiente=%ss)",
            interval,
        )
        try:
            await run_payment_poll_round(settings, hub, state)
        except Exception:
            logger.exception("Error en ciclo del monitor de pagos")

        logger.info(
            "[payment monitor_loop] esperando %ss hasta próxima ronda",
            interval,
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
