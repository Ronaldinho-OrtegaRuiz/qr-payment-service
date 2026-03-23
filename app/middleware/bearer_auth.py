"""Autenticación simple con token en memoria (sin JWT).

Flujo:
  - POST /login genera un token y lo guarda en `app.state.auth_tokens` (set).
  - Middleware valida `Authorization: Bearer <token>` en cada request.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


_PUBLIC_PATHS = frozenset({"/login", "/docs", "/openapi.json", "/redoc"})


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    if path.startswith("/docs/"):
        return True
    # Redirección a /docs para no romper uso interno.
    if path == "/":
        return True
    return False


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def setup_bearer_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_token_middleware(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if _is_public(request.url.path):
            return await call_next(request)

        tokens: set[str] = getattr(request.app.state, "auth_tokens", set())
        token = _extract_bearer_token(request)
        if not token or token not in tokens:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )
        return await call_next(request)

