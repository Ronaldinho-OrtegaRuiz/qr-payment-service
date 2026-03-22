"""WebSocket: eventos de pagos nuevos."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.core.api_key import extract_api_key_from_websocket, is_valid_api_key
from app.services.payments.ws_hub import PaymentWsHub


def register_payments_websocket(app: FastAPI) -> None:
    @app.websocket("/ws/payments")
    async def ws_payments(websocket: WebSocket) -> None:
        """
        Recibe eventos JSON: {"type": "new_payment", "payment": {...}}
        cuando se inserta un pago nuevo en `payments`.
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
