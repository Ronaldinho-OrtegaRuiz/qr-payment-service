"""API del buscador de competencia (proceso aparte del de pagos).

Local:
    uvicorn app.competitor_main:app --host 127.0.0.1 --port 8001
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.services.competitors.gate import GATE, QUEUED_MSG, STARTED_MSG
from app.services.competitors.runner import iter_competitor_slices, search_competitors

app = FastAPI(
    title="Buscador precios competencia",
    description="Servicio aparte del de pagos. Scraping con Playwright.",
    version="0.3.0",
)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(s.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _settings_run():
    return get_settings()


def _site_list(sites: str | None) -> list[str] | None:
    if not sites or not sites.strip():
        return None
    return [p.strip() for p in sites.split(",") if p.strip()]


def _produce_search(
    q: str,
    wanted: list[str] | None,
    put: Callable,
    cancelled: Callable[[], bool],
) -> None:
    """put(('queued'|'started'|'meta'|'slice', dict)); termina con put(None)."""
    settings = _settings_run()
    started = False
    try:
        active, waiting = GATE.snapshot()
        if active or waiting:
            put(
                (
                    "queued",
                    {"ahead": waiting + (1 if active else 0), "message": QUEUED_MSG},
                )
            )

        def _on_wait(ahead: int) -> None:
            put(("queued", {"ahead": ahead, "message": QUEUED_MSG}))

        if not GATE.wait_turn(on_wait=_on_wait, cancelled=cancelled):
            return
        started = True
        if cancelled():
            return
        put(("started", {"message": STARTED_MSG}))
        for kind, payload in iter_competitor_slices(
            q,
            limit=settings.competitor_limit,
            concurrency=settings.competitor_concurrency,
            sites=wanted,
        ):
            if cancelled():
                return
            put((kind, payload))
    finally:
        if started:
            GATE.release()
        put(None)


@app.get("/health")
def health() -> dict[str, str]:
    active, waiting = GATE.snapshot()
    return {"status": "ok", "service": "competitors", "busy": active, "waiting": waiting}


@app.get("/competitors/search")
def competitors_search(
    q: Annotated[str, Query(min_length=2, max_length=80, description="Texto del buscador")],
    sites: Annotated[
        str | None,
        Query(description="Opcional: la_economia,la_rebaja. Si no, los 6."),
    ] = None,
) -> dict:
    """Espera turno en la cola y luego todos los sitios."""
    settings = _settings_run()
    if not GATE.wait_turn():
        return {"q": q, "q_site": "", "slices": [], "error": "cancelado"}
    try:
        return search_competitors(
            q,
            limit=settings.competitor_limit,
            concurrency=settings.competitor_concurrency,
            sites=_site_list(sites),
        )
    finally:
        GATE.release()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/competitors/search/stream")
async def competitors_search_stream(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    sites: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    """SSE: queued → started → meta → slice… → done."""
    wanted = _site_list(sites)
    loop = asyncio.get_running_loop()
    mailbox: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
    cancelled = {"v": False}

    def put(item: tuple[str, dict] | None) -> None:
        loop.call_soon_threadsafe(mailbox.put_nowait, item)

    threading.Thread(
        target=_produce_search,
        args=(q, wanted, put, lambda: cancelled["v"]),
        daemon=True,
    ).start()

    async def _events():
        try:
            while True:
                item = await mailbox.get()
                if item is None:
                    yield _sse("done", {"ok": True})
                    return
                kind, payload = item
                yield _sse(kind, payload)
        finally:
            cancelled["v"] = True

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/competitors/search/ws")
async def competitors_search_ws(websocket: WebSocket) -> None:
    """Mismos eventos: type=queued|started|meta|slice|done."""
    await websocket.accept()
    q = (websocket.query_params.get("q") or "").strip()
    if len(q) < 2 or len(q) > 80:
        await websocket.send_json({"type": "error", "error": "q inválida"})
        await websocket.close()
        return
    wanted = _site_list(websocket.query_params.get("sites"))
    loop = asyncio.get_running_loop()
    mailbox: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
    cancelled = {"v": False}

    def put(item: tuple[str, dict] | None) -> None:
        loop.call_soon_threadsafe(mailbox.put_nowait, item)

    threading.Thread(
        target=_produce_search,
        args=(q, wanted, put, lambda: cancelled["v"]),
        daemon=True,
    ).start()
    try:
        while True:
            item = await mailbox.get()
            if item is None:
                await websocket.send_json({"type": "done", "ok": True})
                break
            kind, payload = item
            if kind == "slice":
                await websocket.send_json({"type": "slice", "slice": payload})
            else:
                await websocket.send_json({"type": kind, **payload})
    except WebSocketDisconnect:
        cancelled["v"] = True
        return
    cancelled["v"] = True
    await websocket.close()


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
