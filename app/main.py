from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.services.imap_service import test_imap_connection

app = FastAPI(
    title="Sistema verificación pagos QR",
    description="API para verificación de pagos vía correo (IMAP) y QR.",
    version="0.1.0",
)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
