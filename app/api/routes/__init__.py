"""Registro de rutas HTTP."""

from __future__ import annotations

from fastapi import FastAPI


def register_http_routes(app: FastAPI) -> None:
    from app.api.routes.payments import router as payments_router
    from app.api.routes.system import router as system_router

    app.include_router(payments_router)
    app.include_router(system_router)
