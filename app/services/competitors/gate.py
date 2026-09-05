"""Una búsqueda a la vez. Las demás esperan en cola FIFO."""

from __future__ import annotations

import threading
from collections.abc import Callable

QUEUED_MSG = "Hay gente buscando. Tu búsqueda va en seguida."
STARTED_MSG = "Cargando…"


class SearchGate:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._active = False
        self._waiters: list[threading.Event] = []

    def snapshot(self) -> tuple[bool, int]:
        with self._cond:
            return self._active, len(self._waiters)

    def wait_turn(
        self,
        on_wait: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        """
        Bloquea hasta que toque el turno. on_wait(ahead) ~cada 1.5s.
        ahead=1 significa que hay una búsqueda corriendo (y 0 más en cola delante).
        Devuelve False si se canceló antes de entrar.
        """
        ev = threading.Event()
        with self._cond:
            if not self._active and not self._waiters:
                self._active = True
                return True
            self._waiters.append(ev)
        try:
            while not ev.wait(timeout=1.5):
                if cancelled and cancelled():
                    self._drop(ev)
                    return False
                if on_wait:
                    on_wait(self._ahead(ev))
            if cancelled and cancelled():
                self.release()
                return False
            return True
        except Exception:
            self._drop(ev)
            raise

    def _ahead(self, ev: threading.Event) -> int:
        with self._cond:
            try:
                return self._waiters.index(ev) + (1 if self._active else 0)
            except ValueError:
                return 1 if self._active else 0

    def _drop(self, ev: threading.Event) -> None:
        with self._cond:
            if ev in self._waiters:
                self._waiters.remove(ev)
                return
        if ev.is_set():
            self.release()

    def release(self) -> None:
        with self._cond:
            self._active = False
            if self._waiters:
                nxt = self._waiters.pop(0)
                self._active = True
                nxt.set()


GATE = SearchGate()
