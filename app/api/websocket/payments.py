"""WebSocket: eventos de pagos nuevos (requiere Authorization Bearer token)."""

from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.services.payments.ws_hub import PaymentWsHub


def register_payments_websocket(app: FastAPI) -> None:
    @app.websocket("/ws/payments")
    async def ws_payments(websocket: WebSocket) -> None:
        """
        Recibe eventos JSON: {"type": "new_payment", "payment": {...}}
        cuando se inserta un pago nuevo en `payments`.
        """
        auth = websocket.headers.get("authorization") or ""
        token = None
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip() or None
        if not token:
            token = websocket.query_params.get("token") or None

        tokens: set[str] = getattr(websocket.app.state, "auth_tokens", set())
        if not token or token not in tokens:
            await websocket.close(code=1008)
            return

        hub: PaymentWsHub = websocket.app.state.payment_hub
        await hub.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)
