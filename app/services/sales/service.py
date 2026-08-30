"""Armado de DTOs de ventas por turnos (totales calculados, no persistidos)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.services.sales import repository as repo

MAX_RANGE_DAYS = 92
MIN_SHIFT_COUNT = 1
MAX_SHIFT_COUNT = 6


class SalesError(ValueError):
    """Error de negocio con código estable para mapear HTTP."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _amount_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"sale_date inesperado: {type(value)!r}")


def _day_dto(
    sale_date: date,
    shift_count: int,
    amounts: dict[int, Decimal],
) -> dict[str, Any]:
    shifts: list[dict[str, Any]] = []
    total = Decimal("0.00")
    for n in range(1, shift_count + 1):
        amt = amounts.get(n)
        if amt is None:
            shifts.append({"shift_no": n, "amount": None})
        else:
            q = amt.quantize(Decimal("0.01"))
            shifts.append({"shift_no": n, "amount": _amount_str(q)})
            total += q
    return {
        "date": sale_date,
        "shifts": shifts,
        "total": _amount_str(total),
    }


def _index_amounts(rows: list[dict[str, Any]]) -> dict[date, dict[int, Decimal]]:
    out: dict[date, dict[int, Decimal]] = {}
    for row in rows:
        d = _as_date(row["sale_date"])
        out.setdefault(d, {})[int(row["shift_no"])] = Decimal(str(row["amount"]))
    return out


def list_sales_range(
    settings: Settings,
    *,
    drogueria_id: int,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    if date_from > date_to:
        raise SalesError("invalid_range", "date_from no puede ser posterior a date_to")
    span = (date_to - date_from).days + 1
    if span > MAX_RANGE_DAYS:
        raise SalesError(
            "range_too_long",
            f"El rango no puede superar {MAX_RANGE_DAYS} días",
        )

    drogueria = repo.get_drogueria(settings, drogueria_id)
    if drogueria is None:
        raise SalesError("drogueria_not_found", "Droguería no encontrada")

    shift_count = int(drogueria["shift_count"])
    rows = repo.list_shift_sales_in_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=date_from,
        date_to=date_to,
    )
    by_day = _index_amounts(rows)

    days: list[dict[str, Any]] = []
    range_total = Decimal("0.00")
    cursor = date_from
    while cursor <= date_to:
        day = _day_dto(cursor, shift_count, by_day.get(cursor, {}))
        range_total += Decimal(day["total"])
        days.append(day)
        cursor += timedelta(days=1)

    return {
        "drogueria_id": drogueria_id,
        "shift_count": shift_count,
        "date_from": date_from,
        "date_to": date_to,
        "range_total": _amount_str(range_total),
        "days": days,
    }


def save_shift_amount(
    settings: Settings,
    *,
    drogueria_id: int,
    sale_date: date,
    shift_no: int,
    amount: Decimal,
) -> dict[str, Any]:
    if amount < 0:
        raise SalesError("invalid_amount", "El valor no puede ser negativo")

    drogueria = repo.get_drogueria(settings, drogueria_id)
    if drogueria is None:
        raise SalesError("drogueria_not_found", "Droguería no encontrada")

    shift_count = int(drogueria["shift_count"])
    if shift_no < 1 or shift_no > shift_count:
        raise SalesError(
            "invalid_shift",
            f"shift_no debe estar entre 1 y {shift_count}",
        )

    repo.upsert_shift_sale(
        settings,
        drogueria_id=drogueria_id,
        sale_date=sale_date,
        shift_no=shift_no,
        amount=amount.quantize(Decimal("0.01")),
    )
    return list_sales_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=sale_date,
        date_to=sale_date,
    )["days"][0]


def set_shift_count(
    settings: Settings, drogueria_id: int, shift_count: int
) -> dict[str, Any]:
    if shift_count < MIN_SHIFT_COUNT or shift_count > MAX_SHIFT_COUNT:
        raise SalesError(
            "invalid_shift_count",
            f"shift_count debe estar entre {MIN_SHIFT_COUNT} y {MAX_SHIFT_COUNT}",
        )
    updated = repo.update_shift_count(settings, drogueria_id, shift_count)
    if updated is None:
        raise SalesError("drogueria_not_found", "Droguería no encontrada")
    return updated
