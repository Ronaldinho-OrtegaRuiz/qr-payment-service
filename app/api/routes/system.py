"""Salud, redirección, IMAP de prueba y poll manual."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.services.imap.client import test_imap_connection
from app.services.payments.monitor import run_payment_poll_round
from app.services.payments.monitor_state import PaymentMonitorState
from app.services.payments.ws_hub import PaymentWsHub

router = APIRouter(tags=["system"])


@router.get("/")
def root(request: Request) -> RedirectResponse:
    q = request.url.query
    target = "/docs" + (f"?{q}" if q else "")
    return RedirectResponse(url=target, status_code=307)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/payments/poll-now")
async def payments_poll_now(request: Request) -> dict:
    """
    Consulta IMAP ya mismo (misma lógica que el monitor): inserta pagos nuevos y notifica WebSocket.
    Sirve para un botón “Actualizar” aunque el intervalo automático sea largo (ej. 1 min).
    """
    settings = get_settings()
    state: PaymentMonitorState = request.app.state.payment_monitor_state
    hub: PaymentWsHub = request.app.state.payment_hub
    result = await run_payment_poll_round(settings, hub, state)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "Error"))
    return result


@router.get("/imap/test")
def imap_test() -> dict:
    """
    Prueba login IMAP contra Gmail usando credenciales del .env (python-dotenv).
    No expone credenciales en la respuesta.
    """
    settings = get_settings()
    result = test_imap_connection(settings)
    body: dict = {
        "ok": result.ok,
        "message": result.message,
    }
    if result.inbox_message_count is not None:
        body["inbox_message_count"] = result.inbox_message_count
    return body
