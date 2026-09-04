"""Employee stats from schedule assignments joined to shift_sales."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.stats.service import (
    ZERO,
    MonthWindow,
    YearWindow,
    _as_date,
    _extreme_months,
    _money,
    _pick_shift_slot,
)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass
class EmpAgg:
    employee_id: int
    employee: str
    assigned: int = 0
    covered: int = 0
    total: Decimal = field(default_factory=lambda: ZERO)
    slots: list[tuple[date, Decimal]] = field(default_factory=list)

    def add(self, work_date: date, amount: Decimal | None) -> None:
        self.assigned += 1
        if amount is not None and amount > 0:
            self.covered += 1
            self.total += amount
            self.slots.append((work_date, amount))


def _extreme_emp_days(
    slots: list[tuple[date, Decimal]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not slots:
        return None, None
    mn = min(slots, key=lambda x: x[1])
    mx = max(slots, key=lambda x: x[1])
    return (
        {"date": mn[0], "value": _money(mn[1])},
        {"date": mx[0], "value": _money(mx[1])},
    )


def _index_rows(
    rows: list[dict[str, Any]], dates: set[date]
) -> dict[int, EmpAgg]:
    out: dict[int, EmpAgg] = {}
    for row in rows:
        d = _as_date(row["work_date"])
        if d not in dates:
            continue
        eid = int(row["employee_id"])
        agg = out.get(eid)
        if agg is None:
            agg = EmpAgg(employee_id=eid, employee=str(row["employee"]))
            out[eid] = agg
        agg.add(d, _dec(row["amount"]))
    return out


def _employee_dtos(aggs: dict[int, EmpAgg]) -> list[dict[str, Any]]:
    ranked = sorted(aggs.values(), key=lambda a: a.total, reverse=True)
    out = []
    for a in ranked:
        worst, best = _extreme_emp_days(a.slots)
        out.append(
            {
                "employee_id": a.employee_id,
                "employee": a.employee,
                "assigned_shifts": a.assigned,
                "covered_shifts": a.covered,
                "total": _money(a.total),
                "avg": _money(a.total / Decimal(a.covered)) if a.covered else None,
                "best_day": best,
                "worst_day": worst,
            }
        )
    return out


def _employee_totals_slots(
    aggs: dict[int, EmpAgg],
) -> tuple[
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
]:
    totals: list[tuple[int, dict[str, Any]]] = []
    best_days: list[tuple[int, dict[str, Any]]] = []
    worst_days: list[tuple[int, dict[str, Any]]] = []
    for a in aggs.values():
        if a.total > 0:
            totals.append(
                (
                    a.employee_id,
                    {"value": _money(a.total), "employee": a.employee},
                )
            )
        worst, best = _extreme_emp_days(a.slots)
        if best:
            best_days.append((a.employee_id, {**best, "employee": a.employee}))
        if worst:
            worst_days.append((a.employee_id, {**worst, "employee": a.employee}))
    return totals, best_days, worst_days


def _named_slot(slot: dict[str, Any] | None) -> dict[str, Any] | None:
    if slot is None:
        return None
    return {
        "employee_id": slot["shift_no"],
        "employee": slot["employee"],
        **{k: v for k, v in slot.items() if k not in {"shift_no", "employee"}},
    }


def _pick_employee_slot(
    slots: list[tuple[int, dict[str, Any]]],
    *,
    pick_max: bool,
) -> dict[str, Any] | None:
    raw = _pick_shift_slot(slots, pick_max=pick_max)
    return _named_slot(raw)


def build_month_employee_block(
    *,
    rows: list[dict[str, Any]],
    window: MonthWindow,
) -> dict[str, Any]:
    kpi_set = set(window.kpi_dates)
    aggs = _index_rows(rows, kpi_set)
    by_employee = _employee_dtos(aggs)
    totals, best_days, worst_days = _employee_totals_slots(aggs)
    assigned = sum(a.assigned for a in aggs.values())
    covered = sum(a.covered for a in aggs.values())
    total = sum((a.total for a in aggs.values()), ZERO)
    return {
        "kpis": {
            "assigned_shifts": assigned,
            "covered_shifts": covered,
            "total_value": _money(total),
            "best_employee": _pick_employee_slot(totals, pick_max=True),
            "worst_employee": _pick_employee_slot(totals, pick_max=False),
            "best_employee_day": _pick_employee_slot(best_days, pick_max=True),
            "worst_employee_day": _pick_employee_slot(worst_days, pick_max=False),
            "by_employee": by_employee,
        }
    }


def build_year_employee_block(
    *,
    rows: list[dict[str, Any]],
    window: YearWindow,
) -> dict[str, Any]:
    aggs: dict[int, EmpAgg] = {}
    month_vals: dict[int, dict[int, Decimal]] = {}
    for row in rows:
        d = _as_date(row["work_date"])
        if d.year != window.year or d.month not in window.kpi_months:
            continue
        eid = int(row["employee_id"])
        agg = aggs.get(eid)
        if agg is None:
            agg = EmpAgg(employee_id=eid, employee=str(row["employee"]))
            aggs[eid] = agg
            month_vals[eid] = {m: ZERO for m in window.kpi_months}
        amt = _dec(row["amount"])
        agg.add(d, amt)
        if amt is not None and amt > 0:
            month_vals[eid][d.month] += amt

    ranked = sorted(aggs.values(), key=lambda a: a.total, reverse=True)
    by_employee = []
    totals: list[tuple[int, dict[str, Any]]] = []
    best_months: list[tuple[int, dict[str, Any]]] = []
    worst_months: list[tuple[int, dict[str, Any]]] = []
    for a in ranked:
        worst_m, best_m = _extreme_months(window.kpi_months, month_vals[a.employee_id])
        by_employee.append(
            {
                "employee_id": a.employee_id,
                "employee": a.employee,
                "assigned_shifts": a.assigned,
                "covered_shifts": a.covered,
                "total": _money(a.total),
                "avg": _money(a.total / Decimal(a.covered)) if a.covered else None,
                "best_month": best_m,
                "worst_month": worst_m,
            }
        )
        if a.total > 0:
            totals.append(
                (a.employee_id, {"value": _money(a.total), "employee": a.employee})
            )
        if best_m:
            best_months.append((a.employee_id, {**best_m, "employee": a.employee}))
        if worst_m:
            worst_months.append((a.employee_id, {**worst_m, "employee": a.employee}))

    assigned = sum(a.assigned for a in aggs.values())
    covered = sum(a.covered for a in aggs.values())
    total = sum((a.total for a in aggs.values()), ZERO)
    return {
        "kpis": {
            "assigned_shifts": assigned,
            "covered_shifts": covered,
            "total_value": _money(total),
            "best_employee": _pick_employee_slot(totals, pick_max=True),
            "worst_employee": _pick_employee_slot(totals, pick_max=False),
            "best_employee_month": _pick_employee_slot(best_months, pick_max=True),
            "worst_employee_month": _pick_employee_slot(worst_months, pick_max=False),
            "by_employee": by_employee,
        }
    }
