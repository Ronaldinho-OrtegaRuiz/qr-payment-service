"""Salud, redirección, IMAP de prueba y poll manual."""

from __future__ import annotations

import secrets

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from app.config import get_settings
from app.services.imap.client import test_imap_connection
from app.services.payments.monitor import run_payment_poll_round
from app.services.payments.monitor_state import PaymentMonitorState
from app.services.payments.ws_hub import PaymentWsHub

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)


@router.get("/")
def root(request: Request) -> RedirectResponse:
    q = request.url.query
    target = "/docs" + (f"?{q}" if q else "")
    return RedirectResponse(url=target, status_code=307)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class LoginBody(BaseModel):
    username: str
    password: str

    @field_validator("username", "password", mode="before")
    @classmethod
    def strip_fields(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


@router.post("/login", openapi_extra={"security": []})
async def login(request: Request, body: LoginBody) -> dict:
    """
    Login interno simple.

    Devuelve un token en memoria con un formato para usar así:
      Authorization: Bearer <token>
    """
    settings = get_settings()
    if not settings.login_users:
        raise HTTPException(
            status_code=503,
            detail="Sin usuarios de login: define ADMIN_USER/ADMIN_PASSWORD y/o BASIC_USER/BASIC_PASSWORD en .env.",
        )
    expected = settings.login_users.get(body.username)
    if expected is None or body.password != expected:
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")

    token = secrets.token_hex(32)
    tokens: set[str] = getattr(request.app.state, "auth_tokens", set())
    tokens.add(token)
    request.app.state.auth_tokens = tokens
    return {"token": token}


@router.post("/payments/poll-now")
async def payments_poll_now(request: Request) -> dict:
    """
    Consulta IMAP ya mismo (misma lógica que el monitor): inserta pagos nuevos y notifica WebSocket.
    Sirve para un botón “Actualizar” aunque el intervalo automático sea largo (ej. 1 min).
    """
    settings = get_settings()
    state: PaymentMonitorState = request.app.state.payment_monitor_state
    hub: PaymentWsHub = request.app.state.payment_hub
    logger.info(
        "[payments/poll-now] invocado manualmente | last_uid=%s",
        state.last_uid,
    )
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
