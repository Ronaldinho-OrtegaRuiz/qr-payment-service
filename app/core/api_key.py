"""Validación de API_KEY (header, Bearer o query para WS)."""

from __future__ import annotations

import secrets

from fastapi import Request
from starlette.websockets import WebSocket


def extract_api_key_from_request(request: Request) -> str | None:
    h = request.headers.get("x-api-key")
    if h and h.strip():
        return h.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    q = request.query_params.get("api_key")
    if q and q.strip():
        return q.strip()
    return None


def extract_api_key_from_websocket(websocket: WebSocket) -> str | None:
    h = websocket.headers.get("x-api-key")
    if h and h.strip():
        return h.strip()
    auth = websocket.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    q = websocket.query_params.get("api_key")
    if q and q.strip():
        return q.strip()
    return None


def is_valid_api_key(provided: str | None, expected: str) -> bool:
    if not expected:
        return False
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)
