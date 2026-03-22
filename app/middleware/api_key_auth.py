"""Exige API_KEY en HTTP (excepto documentación OpenAPI y redirección raíz)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.api_key import extract_api_key_from_request, is_valid_api_key

_DOCS_PUBLIC_PATHS = frozenset({"/docs", "/openapi.json", "/redoc"})


def _path_is_public_docs(path: str) -> bool:
    if path in _DOCS_PUBLIC_PATHS:
        return True
    return path.startswith("/docs/")


def setup_api_key_middleware(app: FastAPI) -> None:
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
                content={
                    "detail": (
                        "API key inválida o ausente. Usa el header X-API-Key "
                        "o Authorization: Bearer <clave>."
                    )
                },
            )
        return await call_next(request)
