"""Employees catalog and schedule cells (only saved days exist)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from psycopg import errors as pg_errors

from app.config import Settings
from app.services.sales.repository import get_drogueria
from app.services.schedule import repository as repo

MAX_RANGE_DAYS = 92
MAX_BATCH = 100


class ScheduleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"unexpected date: {type(value)!r}")


def _require_drogueria(settings: Settings, drogueria_id: int) -> dict[str, Any]:
    drogueria = get_drogueria(settings, drogueria_id)
    if drogueria is None:
        raise ScheduleError("drogueria_not_found", "Drogueria not found")
    return drogueria


def _normalize_name(raw: Any) -> str:
    return str(raw or "").strip()


def list_employees_dto(
    settings: Settings, *, q: str | None = None
) -> list[dict[str, Any]]:
    return [
        {"id": int(r["id"]), "name": r["name"]}
        for r in repo.list_employees(settings, q=q)
    ]


def create_employee(settings: Settings, name: str) -> dict[str, Any]:
    clean = _normalize_name(name)
    if not clean:
        raise ScheduleError("invalid_name", "name is empty")
    try:
        rec = repo.insert_employee(settings, clean)
    except pg_errors.UniqueViolation as e:
        raise ScheduleError(
            "duplicate_employee", "employee name already exists"
        ) from e
    return {"id": int(rec["id"]), "name": rec["name"]}


def rename_employee(
    settings: Settings, employee_id: int, name: str
) -> dict[str, Any]:
    clean = _normalize_name(name)
    if not clean:
        raise ScheduleError("invalid_name", "name is empty")
    try:
        rec = repo.update_employee_name(settings, employee_id, clean)
    except pg_errors.UniqueViolation as e:
        raise ScheduleError(
            "duplicate_employee", "employee name already exists"
        ) from e
    if rec is None:
        raise ScheduleError("employee_not_found", "Employee not found")
    return {"id": int(rec["id"]), "name": rec["name"]}


def _check_range(date_from: date, date_to: date) -> None:
    if date_from > date_to:
        raise ScheduleError("invalid_range", "date_from cannot be after date_to")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise ScheduleError(
            "range_too_long",
            f"Range cannot exceed {MAX_RANGE_DAYS} days",
        )


def _check_shift(shift_no: int, shift_count: int) -> None:
    if shift_no < 1 or shift_no > shift_count:
        raise ScheduleError(
            "invalid_shift",
            f"shift_no must be between 1 and {shift_count}",
        )


def list_schedule_range(
    settings: Settings,
    *,
    drogueria_id: int,
    date_from: date,
    date_to: date,
) -> dict[str, Any]:
    drogueria = _require_drogueria(settings, drogueria_id)
    _check_range(date_from, date_to)
    shift_count = int(drogueria["shift_count"])
    rows = repo.list_assignments(
        settings,
        drogueria_id=drogueria_id,
        date_from=date_from,
        date_to=date_to,
    )
    by_day: dict[date, dict[int, dict[str, Any]]] = {}
    for row in rows:
        d = _as_date(row["work_date"])
        by_day.setdefault(d, {})[int(row["shift_no"])] = {
            "employee_id": int(row["employee_id"]),
            "employee": row["employee"],
        }

    days: list[dict[str, Any]] = []
    cursor = date_from
    while cursor <= date_to:
        slots = by_day.get(cursor, {})
        shifts = []
        for n in range(1, shift_count + 1):
            cell = slots.get(n)
            if cell:
                shifts.append(
                    {
                        "shift_no": n,
                        "employee_id": cell["employee_id"],
                        "employee": cell["employee"],
                    }
                )
            else:
                shifts.append(
                    {"shift_no": n, "employee_id": None, "employee": None}
                )
        days.append({"date": cursor, "shifts": shifts})
        cursor += timedelta(days=1)

    return {
        "drogueria_id": drogueria_id,
        "shift_count": shift_count,
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
    }


def _day_after_write(
    settings: Settings, *, drogueria_id: int, work_date: date
) -> dict[str, Any]:
    payload = list_schedule_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=work_date,
        date_to=work_date,
    )
    return payload["days"][0]


def assign_shift(
    settings: Settings,
    *,
    drogueria_id: int,
    work_date: date,
    shift_no: int,
    employee_id: int,
) -> dict[str, Any]:
    drogueria = _require_drogueria(settings, drogueria_id)
    _check_shift(shift_no, int(drogueria["shift_count"]))
    if repo.get_employee(settings, employee_id) is None:
        raise ScheduleError("employee_not_found", "Employee not found")
    try:
        repo.upsert_assignment(
            settings,
            drogueria_id=drogueria_id,
            work_date=work_date,
            shift_no=shift_no,
            employee_id=employee_id,
        )
    except pg_errors.ForeignKeyViolation as e:
        raise ScheduleError("employee_not_found", "Employee not found") from e
    return _day_after_write(
        settings, drogueria_id=drogueria_id, work_date=work_date
    )


def clear_shift(
    settings: Settings,
    *,
    drogueria_id: int,
    work_date: date,
    shift_no: int,
) -> dict[str, Any]:
    drogueria = _require_drogueria(settings, drogueria_id)
    _check_shift(shift_no, int(drogueria["shift_count"]))
    repo.delete_assignment(
        settings,
        drogueria_id=drogueria_id,
        work_date=work_date,
        shift_no=shift_no,
    )
    return _day_after_write(
        settings, drogueria_id=drogueria_id, work_date=work_date
    )


def save_schedule_batch(
    settings: Settings,
    *,
    drogueria_id: int,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    if not items:
        raise ScheduleError("empty_batch", "Send at least one item")
    if len(items) > MAX_BATCH:
        raise ScheduleError("batch_too_long", f"Maximum {MAX_BATCH} items")
    drogueria = _require_drogueria(settings, drogueria_id)
    shift_count = int(drogueria["shift_count"])
    dates: list[date] = []
    for i, item in enumerate(items):
        work_date = item["work_date"]
        shift_no = int(item["shift_no"])
        _check_shift(shift_no, shift_count)
        employee_id = item.get("employee_id")
        try:
            if employee_id is None:
                repo.delete_assignment(
                    settings,
                    drogueria_id=drogueria_id,
                    work_date=work_date,
                    shift_no=shift_no,
                )
            else:
                if repo.get_employee(settings, int(employee_id)) is None:
                    raise ScheduleError(
                        "employee_not_found",
                        f"Item {i + 1}: employee not found",
                    )
                repo.upsert_assignment(
                    settings,
                    drogueria_id=drogueria_id,
                    work_date=work_date,
                    shift_no=shift_no,
                    employee_id=int(employee_id),
                )
        except ScheduleError:
            raise
        except pg_errors.ForeignKeyViolation as e:
            raise ScheduleError(
                "employee_not_found",
                f"Item {i + 1}: employee not found",
            ) from e
        dates.append(work_date)
    return list_schedule_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=min(dates),
        date_to=max(dates),
    )
