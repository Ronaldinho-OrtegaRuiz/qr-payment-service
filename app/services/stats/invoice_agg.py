"""Invoice stats blocks for GET /stats (period + snapshot)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.services.invoices.service import resolve_status
from app.services.stats.service import (
    ZERO,
    MonthWindow,
    YearWindow,
    _as_date,
    _extreme_months,
    _money,
    _pct,
)

TOP_MONTH = 8
TOP_YEAR = 10


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _visible(row: dict[str, Any], today: date) -> str:
    return resolve_status(str(row["status"]), _as_date(row["due_date"]), today)


@dataclass
class SupplierAgg:
    supplier_id: int
    supplier: str
    issued_count: int = 0
    issued_total: Decimal = field(default_factory=lambda: ZERO)
    paid_total: Decimal = field(default_factory=lambda: ZERO)
    open_total: Decimal = field(default_factory=lambda: ZERO)
    overdue_total: Decimal = field(default_factory=lambda: ZERO)

    def as_dto(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "supplier": self.supplier,
            "issued_count": self.issued_count,
            "issued_total": _money(self.issued_total),
            "paid_total": _money(self.paid_total),
            "open_total": _money(self.open_total),
            "overdue_total": _money(self.overdue_total),
        }


def _supplier_map(rows: list[dict[str, Any]], today: date) -> dict[int, SupplierAgg]:
    out: dict[int, SupplierAgg] = {}
    for row in rows:
        sid = int(row["supplier_id"])
        agg = out.get(sid)
        if agg is None:
            agg = SupplierAgg(supplier_id=sid, supplier=str(row["supplier"]))
            out[sid] = agg
        amt = _dec(row["amount"])
        vis = _visible(row, today)
        agg.issued_count += 1
        agg.issued_total += amt
        if vis == "paid":
            agg.paid_total += amt
        else:
            agg.open_total += amt
            if vis == "overdue":
                agg.overdue_total += amt
    return out


def _top_suppliers(aggs: dict[int, SupplierAgg], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(aggs.values(), key=lambda a: a.issued_total, reverse=True)
    return [a.as_dto() for a in ranked[:limit] if a.issued_total > 0]


def _period_kpis(
    rows: list[dict[str, Any]],
    prev_rows: list[dict[str, Any]],
    today: date,
) -> dict[str, Any]:
    issued_count = len(rows)
    issued_total = ZERO
    paid_count = 0
    paid_total = ZERO
    open_count = 0
    open_total = ZERO
    overdue_count = 0
    overdue_total = ZERO
    for row in rows:
        amt = _dec(row["amount"])
        vis = _visible(row, today)
        issued_total += amt
        if vis == "paid":
            paid_count += 1
            paid_total += amt
        else:
            open_count += 1
            open_total += amt
            if vis == "overdue":
                overdue_count += 1
                overdue_total += amt
    prev_count = len(prev_rows)
    prev_total = sum((_dec(r["amount"]) for r in prev_rows), ZERO)
    return {
        "issued_count": issued_count,
        "issued_total": _money(issued_total),
        "avg_amount": _money(issued_total / Decimal(issued_count)) if issued_count else None,
        "paid_count": paid_count,
        "paid_total": _money(paid_total),
        "open_count": open_count,
        "open_total": _money(open_total),
        "overdue_count": overdue_count,
        "overdue_total": _money(overdue_total),
        "vs_previous": {
            "count_pct": _pct(Decimal(issued_count), Decimal(prev_count)),
            "value_pct": _pct(issued_total, prev_total),
        },
    }


def _snapshot(open_rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    open_now = ZERO
    overdue_now = ZERO
    open_n = 0
    overdue_n = 0
    due_7d = ZERO
    due_7d_n = 0
    aging = {
        "not_due": {"count": 0, "total": ZERO},
        "d1_7": {"count": 0, "total": ZERO},
        "d8_30": {"count": 0, "total": ZERO},
        "d31_plus": {"count": 0, "total": ZERO},
    }
    by_sup: dict[int, SupplierAgg] = {}
    horizon = today + timedelta(days=7)

    for row in open_rows:
        amt = _dec(row["amount"])
        due = _as_date(row["due_date"])
        vis = _visible(row, today)
        sid = int(row["supplier_id"])
        agg = by_sup.get(sid)
        if agg is None:
            agg = SupplierAgg(supplier_id=sid, supplier=str(row["supplier"]))
            by_sup[sid] = agg
        agg.open_total += amt
        open_n += 1
        open_now += amt
        if vis == "overdue":
            overdue_n += 1
            overdue_now += amt
            agg.overdue_total += amt
            days = (today - due).days
            if days <= 7:
                bucket = "d1_7"
            elif days <= 30:
                bucket = "d8_30"
            else:
                bucket = "d31_plus"
        else:
            bucket = "not_due"
            if due <= horizon:
                due_7d_n += 1
                due_7d += amt
        aging[bucket]["count"] += 1
        aging[bucket]["total"] += amt

    ranked = sorted(by_sup.values(), key=lambda a: a.open_total, reverse=True)
    return {
        "open_now_count": open_n,
        "open_now_total": _money(open_now),
        "overdue_now_count": overdue_n,
        "overdue_now_total": _money(overdue_now),
        "due_7d_count": due_7d_n,
        "due_7d_total": _money(due_7d),
        "aging": {
            k: {"count": v["count"], "total": _money(v["total"])} for k, v in aging.items()
        },
        "by_supplier_open": [
            {
                "supplier_id": a.supplier_id,
                "supplier": a.supplier,
                "open_total": _money(a.open_total),
                "overdue_total": _money(a.overdue_total),
            }
            for a in ranked[:TOP_MONTH]
            if a.open_total > 0
        ],
    }


def _in_dates(row: dict[str, Any], dates: set[date]) -> bool:
    return _as_date(row["invoice_date"]) in dates


def build_month_invoice_block(
    *,
    period_rows: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
    window: MonthWindow,
    prev: MonthWindow,
    today: date,
) -> dict[str, Any]:
    kpi_set = set(window.kpi_dates)
    prev_set = set(prev.kpi_dates)
    current = [r for r in period_rows if _in_dates(r, kpi_set)]
    previous = [r for r in period_rows if _in_dates(r, prev_set)]
    kpis = _period_kpis(current, previous, today)
    kpis["by_supplier"] = _top_suppliers(_supplier_map(current, today), TOP_MONTH)

    by_day: dict[date, tuple[int, Decimal]] = defaultdict(lambda: (0, ZERO))
    for row in current:
        d = _as_date(row["invoice_date"])
        c, t = by_day[d]
        by_day[d] = (c + 1, t + _dec(row["amount"]))
    series = []
    for d in window.series_dates:
        c, t = by_day.get(d, (0, ZERO))
        series.append({"date": d, "count": c, "amount": _money(t)})

    return {
        "kpis": kpis,
        "series": series,
        "snapshot": _snapshot(open_rows, today),
    }


def build_year_invoice_block(
    *,
    period_rows: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
    window: YearWindow,
    prev: YearWindow,
    today: date,
) -> dict[str, Any]:
    def in_year_months(row: dict[str, Any], year: int, months: list[int]) -> bool:
        d = _as_date(row["invoice_date"])
        return d.year == year and d.month in months

    current = [
        r for r in period_rows if in_year_months(r, window.year, window.kpi_months)
    ]
    previous = [
        r for r in period_rows if in_year_months(r, prev.year, prev.kpi_months)
    ]
    kpis = _period_kpis(current, previous, today)
    kpis["by_supplier"] = _top_suppliers(_supplier_map(current, today), TOP_YEAR)

    month_count = {m: 0 for m in window.series_months}
    month_amt = {m: ZERO for m in window.series_months}
    for row in period_rows:
        d = _as_date(row["invoice_date"])
        if d.year != window.year:
            continue
        month_count[d.month] = month_count.get(d.month, 0) + 1
        month_amt[d.month] = month_amt.get(d.month, ZERO) + _dec(row["amount"])

    worst, best = _extreme_months(window.kpi_months, month_amt)
    kpis["best_month"] = best
    kpis["worst_month"] = worst
    kpis["avg_issued_per_month"] = _money(
        _dec(kpis["issued_total"]) / Decimal(len(window.kpi_months) or 1)
    )

    series = [
        {
            "month": m,
            "count": month_count[m],
            "amount": _money(month_amt[m]),
        }
        for m in window.series_months
    ]
    return {
        "kpis": kpis,
        "series": series,
        "snapshot": _snapshot(open_rows, today),
    }
