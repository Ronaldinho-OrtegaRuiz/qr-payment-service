"""
Polling IMAP: monitor en background + ronda manual vía POST /payments/poll-now.

Comparten last_uid y un lock para no solapar consultas IMAP.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings, get_settings
from app.services.bancolombia.imap_mail import bootstrap_last_uid, poll_uids_after
from app.services.payments.monitor_state import PaymentMonitorState
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
    if not settings.database_url.strip():
        return {
            "ok": False,
            "message": "Falta DATABASE_URL en .env.",
            "new_count": 0,
            "new_payments": [],
            "last_uid": state.last_uid,
            "bootstrapped": False,
        }
    if not settings.gmail_account_email.strip() or not settings.app_password_gmail_account.strip():
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
        if state.last_uid == 0:
            state.last_uid = await asyncio.to_thread(
                bootstrap_last_uid,
                settings,
                from_email=settings.bancol_notifications_from,
                search_text=settings.bancol_search_phrase,
            )
            bootstrapped = True
            message = (
                f"Puntero IMAP listo (último UID conocido: {state.last_uid}). "
                "No se cargaron correos antiguos; los próximos aparecerán aquí o por WebSocket."
            )
            logger.info("Poll: bootstrap UID = %s", state.last_uid)
        else:
            entries, state.last_uid = await asyncio.to_thread(
                poll_uids_after,
                settings,
                from_email=settings.bancol_notifications_from,
                search_text=settings.bancol_search_phrase,
                last_uid=state.last_uid,
            )
            tz = get_payments_timezone()
            for entry in entries:
                row = mail_entry_to_row(entry, settings.drogueria_id, tz)
                if not row:
                    continue
                saved = await asyncio.to_thread(insert_payment_if_new, settings, row)
                if saved:
                    logger.info("Pago nuevo: %s", saved.get("message_id"))
                    new_payments.append(saved)
                    await hub.broadcast_new_payment(saved)

            if new_payments:
                message = f"Se registraron {len(new_payments)} pago(s) nuevo(s)."
            elif entries:
                message = (
                    f"Se revisaron {len(entries)} correo(s) nuevo(s); "
                    "ninguno coincidió como pago parseable o ya estaban en la BD."
                )
            else:
                message = "No había correos nuevos desde el último chequeo."

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
            try:
                await asyncio.wait_for(stop.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass
            continue

        interval = settings.payments_monitor_interval_sec
        try:
            await run_payment_poll_round(settings, hub, state)
        except Exception:
            logger.exception("Error en ciclo del monitor de pagos")

        try:
            await asyncio.wait_for(stop.wait(), timeout=float(interval))
        except asyncio.TimeoutError:
            pass
