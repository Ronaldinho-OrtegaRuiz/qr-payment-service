"""Estado compartido entre el monitor en background y POST /payments/poll-now."""

from __future__ import annotations

import asyncio


class PaymentMonitorState:
    def __init__(self) -> None:
        self.last_uid: int = 0
        self.lock = asyncio.Lock()
