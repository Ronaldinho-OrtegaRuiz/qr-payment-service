import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.routers.payments import router as payments_list_router
from app.services.imap_service import test_imap_connection
from app.services.payment_monitor import payment_monitor_loop, run_payment_poll_round
from app.services.payment_monitor_state import PaymentMonitorState
from app.services.payment_ws_hub import PaymentWsHub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=307)


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
    hub: PaymentWsHub = websocket.app.state.payment_hub
    await hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
