"""Fábrica de la aplicación FastAPI (lifespan, rutas, middleware)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.openapi import setup_openapi_security
from app.api.routes import register_http_routes
from app.api.websocket.payments import register_payments_websocket
from app.config import get_settings
from app.middleware.bearer_auth import setup_bearer_auth_middleware
from app.services.payments.monitor import payment_monitor_loop
from app.services.payments.monitor_state import PaymentMonitorState
from app.services.payments.ws_hub import PaymentWsHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.payment_hub = PaymentWsHub()
    app.state.payment_monitor_state = PaymentMonitorState()
    app.state.auth_tokens = set()
    stop = asyncio.Event()
    task: asyncio.Task | None = None
    s = get_settings()
    if s.payments_monitor_enabled and s.database_url.strip():
        task = asyncio.create_task(
            payment_monitor_loop(
                app.state.payment_hub,
                stop,
                app.state.payment_monitor_state,
            ),
            name="payment_imap_monitor",
        )
        logger.info(
            "Monitor de pagos activo (cada %ss, IMAP TEXT OR=%s, droguerías id=%s / secundaria=%s si match %r)",
            s.payments_monitor_interval_sec,
            s.bancol_search_phrases,
            s.drogueria_id,
            s.drogueria_secondary_id,
            s.drogueria_secondary_match,
        )
    else:
        logger.info(
            "Monitor de pagos desactivado (PAYMENTS_MONITOR_ENABLED / DATABASE_URL / Gmail)."
        )
    yield
    stop.set()
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sistema verificación pagos QR",
        description="API para verificación de pagos vía correo (IMAP), QR y WebSocket.",
        version="0.2.0",
        lifespan=lifespan,
    )

    register_http_routes(app)
    register_payments_websocket(app)
    setup_openapi_security(app)
    setup_bearer_auth_middleware(app)

    return app
