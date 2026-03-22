import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse

from app.api_key import (
    extract_api_key_from_request,
    extract_api_key_from_websocket,
    is_valid_api_key,
)
from app.config import get_settings
from app.routers.payments import router as payments_list_router
from app.services.imap_service import test_imap_connection
from app.services.payment_monitor import payment_monitor_loop, run_payment_poll_round
from app.services.payment_monitor_state import PaymentMonitorState
from app.services.payment_ws_hub import PaymentWsHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Solo documentación OpenAPI/Swagger (sin esto el navegador no puede cargar /openapi.json al abrir /docs).
_DOCS_PUBLIC_PATHS = frozenset({"/docs", "/openapi.json", "/redoc"})


def _path_is_public_docs(path: str) -> bool:
    if path in _DOCS_PUBLIC_PATHS:
        return True
    return path.startswith("/docs/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.payment_hub = PaymentWsHub()
    app.state.payment_monitor_state = PaymentMonitorState()
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
            "Monitor de pagos activo (cada %ss, frase=%r)",
            s.payments_monitor_interval_sec,
            s.bancol_search_phrase,
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


app = FastAPI(
    title="Sistema verificación pagos QR",
    description="API para verificación de pagos vía correo (IMAP), QR y WebSocket.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(payments_list_router)


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "ApiKeyAuth"
    ] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Misma clave que la variable de entorno API_KEY.",
    }
    openapi_schema["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


@app.middleware("http")
async def require_api_key_middleware(request: Request, call_next):
    if request.method == "GET" and request.url.path == "/":
        return await call_next(request)
    if _path_is_public_docs(request.url.path):
        return await call_next(request)

    settings = get_settings()
    expected = settings.api_key
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"detail": "API_KEY no está configurada en el servidor."},
        )
    provided = extract_api_key_from_request(request)
    if not is_valid_api_key(provided, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "API key inválida o ausente. Usa el header X-API-Key o Authorization: Bearer <clave>."},
        )
    return await call_next(request)


@app.get("/")
def root(request: Request) -> RedirectResponse:
    q = request.url.query
    target = "/docs" + (f"?{q}" if q else "")
    return RedirectResponse(url=target, status_code=307)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/payments/poll-now")
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


@app.get("/imap/test")
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


@app.websocket("/ws/payments")
async def ws_payments(websocket: WebSocket) -> None:
    """
    Recibe eventos JSON: {"type": "new_payment", "payment": {...}}
    cuando se inserta un pago nuevo en `payments` (misma lógica que la carga masiva).
    """
    settings = get_settings()
    expected = settings.api_key
    if not expected:
        await websocket.close(code=1011)
        return
    provided = extract_api_key_from_websocket(websocket)
    if not is_valid_api_key(provided, expected):
        await websocket.close(code=1008)
        return

    hub: PaymentWsHub = websocket.app.state.payment_hub
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
