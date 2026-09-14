"""Nequi payments: ingest from phone app, list, assign drogueria."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from psycopg import errors as pg_errors

from app.config import Settings
from app.services.nequi import repository as repo
from app.services.payments.repository import get_payments_timezone
from app.services.sales.repository import get_drogueria


class NequiError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _as_dt(value: Any, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value
    if isinstance(value, (int, float)):
        # epoch millis or seconds
        n = float(value)
        if n > 1e12:
            n = n / 1000.0
        return datetime.fromtimestamp(n, tz=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    raise NequiError("invalid_notified_at", "notified_at invalid")


def _money(raw: Any) -> Decimal:
    if isinstance(raw, Decimal):
        v = raw
    else:
        s = str(raw or "").strip().replace(",", "")
        try:
            v = Decimal(s)
        except InvalidOperation as e:
            raise NequiError("invalid_value", "value invalid") from e
    if v < 0:
        raise NequiError("invalid_value", "value must be >= 0")
    return v.quantize(Decimal("0.01"))


def _dto(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("value"), Decimal):
        out["value"] = str(out["value"])
    for k in ("notified_at", "assigned_at", "created_at", "updated_at"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


def ingest_one(settings: Settings, item: dict[str, Any]) -> dict[str, Any]:
    client = str(item.get("client") or "").strip()
    if not client:
        raise NequiError("invalid_client", "client is required")
    key = str(item.get("notification_key") or "").strip()
    if not key:
        raise NequiError("invalid_key", "notification_key is required")
    raw = str(item.get("raw_text") or "").strip()
    device_id = (str(item.get("device_id") or "").strip() or None)
    value = _money(item.get("value"))
    tz = get_payments_timezone()
    notified_at = _as_dt(item.get("notified_at"), tz)

    try:
        saved = repo.insert_if_new(
            settings,
            client=client,
            value=value,
            notified_at=notified_at,
            notification_key=key,
            raw_text=raw,
            device_id=device_id,
        )
    except pg_errors.UniqueViolation:
        saved = None

    if saved is None:
        return {"created": False, "item": None, "notification_key": key}
    return {"created": True, "item": _dto(saved), "notification_key": key}


def ingest_batch(settings: Settings, items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise NequiError("empty_batch", "Send at least one item")
    if len(items) > 100:
        raise NequiError("batch_too_long", "Maximum 100 items")
    results = []
    created = 0
    for item in items:
        r = ingest_one(settings, item)
        if r["created"]:
            created += 1
        results.append(r)
    return {"ok": True, "created_count": created, "results": results}


def list_nequi(
    settings: Settings,
    *,
    assigned: str | None,
    drogueria_id: int | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if assigned is not None and assigned not in {"true", "false", "all"}:
        raise NequiError("invalid_assigned", "assigned must be true, false or all")
    filt = None if assigned in (None, "all") else assigned
    rows, total = repo.list_payments(
        settings,
        assigned=filt,
        drogueria_id=drogueria_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": [_dto(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def assign_nequi(
    settings: Settings,
    payment_id: int,
    drogueria_id: int | None,
) -> dict[str, Any]:
    if drogueria_id is not None:
        if get_drogueria(settings, drogueria_id) is None:
            raise NequiError("drogueria_not_found", "Drogueria not found")
    row = repo.assign_drogueria(settings, payment_id, drogueria_id)
    if row is None:
        raise NequiError("nequi_not_found", "Nequi payment not found")
    return _dto(row)


def delete_nequi(settings: Settings, payment_id: int) -> None:
    if not repo.delete_payment(settings, payment_id):
        raise NequiError("nequi_not_found", "Nequi payment not found")
