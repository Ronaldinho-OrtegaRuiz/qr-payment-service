"""Cliente HTTP compartido (sin navegador)."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 18


def fetch(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    accept: str = "application/json,text/html,*/*",
    headers: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """GET. Devuelve (status, content_type, body)."""
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "es-CO,es;q=0.9",
    }
    if headers:
        req_headers.update(headers)
    req = Request(url, headers=req_headers, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            status = getattr(resp, "status", 200)
            return status, ctype, raw.decode("utf-8", errors="replace")
    except HTTPError as e:
        raw = e.read() if e.fp else b""
        ctype = (e.headers.get("Content-Type") if e.headers else "") or ""
        return e.code, ctype.split(";")[0].strip(), raw.decode("utf-8", errors="replace")
    except URLError as e:
        raise RuntimeError(f"sin conexión: {e.reason}") from e


def fetch_json(url: str, **kwargs) -> tuple[int, object]:
    status, _ctype, body = fetch(url, accept="application/json,*/*", **kwargs)
    if not body.strip():
        return status, None
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, None


def quote_path(value: str) -> str:
    return quote(value.strip(), safe="")
