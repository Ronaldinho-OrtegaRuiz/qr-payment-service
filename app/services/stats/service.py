"""Estadísticas QR y caja: ventanas de calendario y agregación."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from app.services.invoices import repository as invoices_repo
from app.services.payments.repository import get_payments_timezone
from app.services.sales import repository as sales_repo
from app.services.stats import repository as payments_repo

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
HUNDREDTH = Decimal("0.01")


class StatsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _ratio(value: Decimal) -> str:
    return str(value.quantize(HUNDREDTH, rounding=ROUND_HALF_UP))


def _pct(current: Decimal, previous: Decimal) -> str | None:
    if previous == 0:
        return None
    return _ratio((current - previous) / previous * Decimal("100"))


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"fecha inesperada: {type(value)!r}")


def _local_day(value: Any, tz: ZoneInfo) -> date:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=tz)
        return dt.astimezone(tz).date()
    if isinstance(value, date):
        return value
    raise TypeError(f"date inesperado: {type(value)!r}")


def _month_end_exclusive(year: int, month: int, tz: ZoneInfo) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=tz)
    return datetime(year, month + 1, 1, tzinfo=tz)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


@dataclass
class DayBucket:
    count: int = 0
    value: Decimal = field(default_factory=lambda: ZERO)
    clients: set[str] = field(default_factory=set)
    shifts: dict[int, Decimal] = field(default_factory=dict)

    @property
    def sales_total(self) -> Decimal:
        return sum(self.shifts.values(), ZERO)


@dataclass
class MonthWindow:
    year: int
    month: int
    start: datetime
    end: datetime
    series_dates: list[date]
    kpi_dates: list[date]

    @property
    def first(self) -> date:
        return self.series_dates[0]

    @property
    def last(self) -> date:
        return self.series_dates[-1]


def build_month_window(year: int, month: int, today: date, tz: ZoneInfo) -> MonthWindow:
    last_n = calendar.monthrange(year, month)[1]
    first = date(year, month, 1)
    last = date(year, month, last_n)
    series = [first + timedelta(days=i) for i in range(last_n)]
    if year == today.year and month == today.month:
        kpi_until = today
    else:
        kpi_until = last
    kpi = [d for d in series if d <= kpi_until]
    return MonthWindow(
        year=year,
        month=month,
        start=datetime(year, month, 1, tzinfo=tz),
        end=_month_end_exclusive(year, month, tz),
        series_dates=series,
        kpi_dates=kpi,
    )


def build_prev_month_window(current: MonthWindow, today: date, tz: ZoneInfo) -> MonthWindow:
    py, pm = _shift_month(current.year, current.month, -1)
    prev = build_month_window(py, pm, today, tz)
    # Mes en curso: comparar 1…hoy contra 1…mismo día del mes previo (capped).
    if current.year == today.year and current.month == today.month:
        cap = min(today.day, len(prev.series_dates))
        prev.kpi_dates = prev.series_dates[:cap]
    return prev


@dataclass
class YearWindow:
    year: int
    start: datetime
    end: datetime
    series_months: list[int]
    kpi_months: list[int]


def build_year_window(year: int, today: date, tz: ZoneInfo) -> YearWindow:
    if year == today.year:
        kpi_months = list(range(1, today.month + 1))
    else:
        kpi_months = list(range(1, 13))
    return YearWindow(
        year=year,
        start=datetime(year, 1, 1, tzinfo=tz),
        end=datetime(year + 1, 1, 1, tzinfo=tz),
        series_months=list(range(1, 13)),
        kpi_months=kpi_months,
    )


def _index_payments(
    rows: list[dict[str, Any]], tz: ZoneInfo
) -> dict[date, DayBucket]:
    out: dict[date, DayBucket] = {}
    for row in rows:
        d = _local_day(row["date"], tz)
        b = out.setdefault(d, DayBucket())
        b.count += 1
        b.value += Decimal(str(row["value"]))
        client = (row.get("client") or "").strip()
        if client:
            b.clients.add(client)
    return out


def _index_sales(rows: list[dict[str, Any]]) -> dict[date, DayBucket]:
    out: dict[date, DayBucket] = {}
    for row in rows:
        d = _as_date(row["sale_date"])
        b = out.setdefault(d, DayBucket())
        b.shifts[int(row["shift_no"])] = Decimal(str(row["amount"]))
    return out


def _extreme_days(
    dates: list[date], buckets: dict[date, DayBucket], *, sales: bool
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    scored: list[tuple[date, Decimal]] = []
    for d in dates:
        b = buckets.get(d)
        val = (b.sales_total if sales else (b.value if b else ZERO)) if b else ZERO
        if val > 0:
            scored.append((d, val))
    if not scored:
        return None, None
    mn = min(scored, key=lambda x: x[1])
    mx = max(scored, key=lambda x: x[1])
    return (
        {"date": mn[0], "value": _money(mn[1])},
        {"date": mx[0], "value": _money(mx[1])},
    )


def _extreme_months(
    months: list[int],
    values: dict[int, Decimal],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    scored = [(m, values[m]) for m in months if values.get(m, ZERO) > 0]
    if not scored:
        return None, None
    mn = min(scored, key=lambda x: x[1])
    mx = max(scored, key=lambda x: x[1])
    return (
        {"month": mn[0], "value": _money(mn[1])},
        {"month": mx[0], "value": _money(mx[1])},
    )


def _extreme_shifts(
    shift_totals: list[Decimal],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    scored = [(i + 1, t) for i, t in enumerate(shift_totals) if t > 0]
    if not scored:
        return None, None
    mn = min(scored, key=lambda x: x[1])
    mx = max(scored, key=lambda x: x[1])
    return (
        {"shift_no": mn[0], "value": _money(mn[1])},
        {"shift_no": mx[0], "value": _money(mx[1])},
    )


def _pick_shift_slot(
    slots: list[tuple[int, dict[str, Any]]],
    *,
    pick_max: bool,
) -> dict[str, Any] | None:
    if not slots:
        return None
    chosen = max(slots, key=lambda x: Decimal(x[1]["value"])) if pick_max else min(
        slots, key=lambda x: Decimal(x[1]["value"])
    )
    shift_no, point = chosen
    return {"shift_no": shift_no, **point}


def _extreme_shift_days(
    dates: list[date],
    buckets: dict[date, DayBucket],
    shift_no: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    scored: list[tuple[date, Decimal]] = []
    for d in dates:
        b = buckets.get(d)
        amt = b.shifts.get(shift_no) if b else None
        if amt is not None and amt > 0:
            scored.append((d, amt))
    if not scored:
        return None, None
    mn = min(scored, key=lambda x: x[1])
    mx = max(scored, key=lambda x: x[1])
    return (
        {"date": mn[0], "value": _money(mn[1])},
        {"date": mx[0], "value": _money(mx[1])},
    )


def _qr_kpis_month(
    buckets: dict[date, DayBucket],
    kpi_dates: list[date],
    prev_buckets: dict[date, DayBucket],
    prev_kpi_dates: list[date],
) -> dict[str, Any]:
    divisor = len(kpi_dates) or 1
    count = 0
    total = ZERO
    clients: set[str] = set()
    days_with = 0
    for d in kpi_dates:
        b = buckets.get(d)
        if not b or b.count == 0:
            continue
        days_with += 1
        count += b.count
        total += b.value
        clients |= b.clients

    prev_count = 0
    prev_total = ZERO
    for d in prev_kpi_dates:
        b = prev_buckets.get(d)
        if not b:
            continue
        prev_count += b.count
        prev_total += b.value

    min_day, max_day = _extreme_days(kpi_dates, buckets, sales=False)
    avg_pay = Decimal(count) / Decimal(divisor)
    return {
        "payments_count": count,
        "total_value": _money(total),
        "avg_payments_per_day": _ratio(avg_pay),
        "avg_value_per_day": _money(total / Decimal(divisor)),
        "avg_value_per_payment": _money(total / Decimal(count)) if count else None,
        "min_day": min_day,
        "max_day": max_day,
        "days_with_sales": days_with,
        "days_empty": max(0, len(kpi_dates) - days_with),
        "unique_clients": len(clients),
        "vs_previous": {
            "payments_pct": _pct(Decimal(count), Decimal(prev_count)),
            "value_pct": _pct(total, prev_total),
        },
    }


def _sales_kpis_month(
    buckets: dict[date, DayBucket],
    kpi_dates: list[date],
    prev_buckets: dict[date, DayBucket],
    prev_kpi_dates: list[date],
    shift_count: int,
) -> dict[str, Any]:
    divisor = len(kpi_dates) or 1
    total = ZERO
    days_filled = 0
    shift_totals = [ZERO] * shift_count
    shift_filled = [0] * shift_count
    for d in kpi_dates:
        b = buckets.get(d)
        day_total = b.sales_total if b else ZERO
        if day_total > 0:
            days_filled += 1
            total += day_total
        if b:
            for n in range(1, shift_count + 1):
                amt = b.shifts.get(n)
                if amt is not None and amt > 0:
                    shift_totals[n - 1] += amt
                    shift_filled[n - 1] += 1

    prev_total = ZERO
    for d in prev_kpi_dates:
        b = prev_buckets.get(d)
        if b:
            prev_total += b.sales_total

    min_day, max_day = _extreme_days(kpi_dates, buckets, sales=True)
    worst_shift, best_shift = _extreme_shifts(shift_totals)
    by_shift = []
    best_slots: list[tuple[int, dict[str, Any]]] = []
    worst_slots: list[tuple[int, dict[str, Any]]] = []
    for n in range(1, shift_count + 1):
        filled = shift_filled[n - 1]
        t = shift_totals[n - 1]
        worst_day, best_day = _extreme_shift_days(kpi_dates, buckets, n)
        by_shift.append(
            {
                "shift_no": n,
                "total": _money(t),
                "avg": _money(t / Decimal(filled)) if filled else None,
                "filled_days": filled,
                "best_day": best_day,
                "worst_day": worst_day,
            }
        )
        if best_day:
            best_slots.append((n, best_day))
        if worst_day:
            worst_slots.append((n, worst_day))
    return {
        "total_value": _money(total),
        "avg_value_per_day": _money(total / Decimal(divisor)),
        "min_day": min_day,
        "max_day": max_day,
        "days_filled": days_filled,
        "days_empty": max(0, len(kpi_dates) - days_filled),
        "best_shift": best_shift,
        "worst_shift": worst_shift,
        "best_shift_day": _pick_shift_slot(best_slots, pick_max=True),
        "worst_shift_day": _pick_shift_slot(worst_slots, pick_max=False),
        "by_shift": by_shift,
        "vs_previous": {
            "value_pct": _pct(total, prev_total),
        },
    }


def _compare(
    qr_total: str,
    sales_total: str,
    *,
    invoices_issued: str,
    invoices_open_now: str,
) -> dict[str, Any]:
    q = Decimal(qr_total)
    s = Decimal(sales_total)
    share = _ratio(q / s) if s > 0 else None
    return {
        "qr_total": qr_total,
        "sales_total": sales_total,
        "delta": _money(s - q),
        "qr_share": share,
        "invoices_issued": invoices_issued,
        "invoices_open_now": invoices_open_now,
    }


def _qr_series_month(
    buckets: dict[date, DayBucket], dates: list[date]
) -> list[dict[str, Any]]:
    out = []
    for d in dates:
        b = buckets.get(d)
        out.append(
            {
                "date": d,
                "count": b.count if b else 0,
                "value": _money(b.value if b else ZERO),
            }
        )
    return out


def _sales_series_month(
    buckets: dict[date, DayBucket], dates: list[date], shift_count: int
) -> list[dict[str, Any]]:
    out = []
    for d in dates:
        b = buckets.get(d)
        shifts = []
        for n in range(1, shift_count + 1):
            amt = b.shifts.get(n) if b else None
            shifts.append(
                {
                    "shift_no": n,
                    "amount": _money(amt) if amt is not None else None,
                }
            )
        out.append(
            {
                "date": d,
                "total": _money(b.sales_total if b else ZERO),
                "shifts": shifts,
            }
        )
    return out


def get_month_stats(
    settings: Settings,
    *,
    drogueria_id: int,
    year: int,
    month: int,
) -> dict[str, Any]:
    drogueria = sales_repo.get_drogueria(settings, drogueria_id)
    if drogueria is None:
        raise StatsError("drogueria_not_found", "Droguería no encontrada")

    tz = get_payments_timezone()
    today = datetime.now(tz).date()
    window = build_month_window(year, month, today, tz)
    prev = build_prev_month_window(window, today, tz)
    shift_count = int(drogueria["shift_count"])

    pay_rows = payments_repo.list_payments_in_range(
        settings,
        drogueria_id=drogueria_id,
        start=prev.start,
        end=window.end,
    )
    sale_rows = sales_repo.list_shift_sales_in_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=prev.first,
        date_to=window.last,
    )
    pay = _index_payments(pay_rows, tz)
    sales = _index_sales(sale_rows)

    from app.services.stats.invoice_agg import build_month_invoice_block

    inv_period = invoices_repo.list_invoices(
        settings,
        drogueria_id=drogueria_id,
        date_from=prev.first,
        date_to=window.last,
    )
    inv_open = invoices_repo.list_open_invoices(
        settings, drogueria_id=drogueria_id
    )
    invoices = build_month_invoice_block(
        period_rows=inv_period,
        open_rows=inv_open,
        window=window,
        prev=prev,
        today=today,
    )

    qr_kpis = _qr_kpis_month(pay, window.kpi_dates, pay, prev.kpi_dates)
    sales_kpis = _sales_kpis_month(
        sales, window.kpi_dates, sales, prev.kpi_dates, shift_count
    )
    return {
        "period": "month",
        "year": year,
        "month": month,
        "drogueria_id": drogueria_id,
        "shift_count": shift_count,
        "divisor_days": len(window.kpi_dates),
        "qr": {
            "kpis": qr_kpis,
            "series": _qr_series_month(pay, window.series_dates),
        },
        "sales": {
            "kpis": sales_kpis,
            "series": _sales_series_month(sales, window.series_dates, shift_count),
        },
        "invoices": invoices,
        "compare": _compare(
            qr_kpis["total_value"],
            sales_kpis["total_value"],
            invoices_issued=invoices["kpis"]["issued_total"],
            invoices_open_now=invoices["snapshot"]["open_now_total"],
        ),
    }


def _month_totals_qr(
    buckets: dict[date, DayBucket], year: int, months: list[int]
) -> tuple[dict[int, Decimal], dict[int, int], set[str]]:
    values: dict[int, Decimal] = {m: ZERO for m in months}
    counts: dict[int, int] = {m: 0 for m in months}
    clients: set[str] = set()
    for d, b in buckets.items():
        if d.year != year or d.month not in values:
            continue
        values[d.month] += b.value
        counts[d.month] += b.count
        clients |= b.clients
    return values, counts, clients


def _month_totals_sales(
    buckets: dict[date, DayBucket], year: int, months: list[int]
) -> dict[int, Decimal]:
    values: dict[int, Decimal] = {m: ZERO for m in months}
    for d, b in buckets.items():
        if d.year != year or d.month not in values:
            continue
        values[d.month] += b.sales_total
    return values


def get_year_stats(
    settings: Settings,
    *,
    drogueria_id: int,
    year: int,
) -> dict[str, Any]:
    drogueria = sales_repo.get_drogueria(settings, drogueria_id)
    if drogueria is None:
        raise StatsError("drogueria_not_found", "Droguería no encontrada")

    tz = get_payments_timezone()
    today = datetime.now(tz).date()
    window = build_year_window(year, today, tz)
    prev = build_year_window(year - 1, today, tz)
    # Año en curso: YTD vs YTD (mismos meses del año previo).
    if year == today.year:
        prev.kpi_months = list(window.kpi_months)
    shift_count = int(drogueria["shift_count"])

    pay_rows = payments_repo.list_payments_in_range(
        settings,
        drogueria_id=drogueria_id,
        start=prev.start,
        end=window.end,
    )
    sale_rows = sales_repo.list_shift_sales_in_range(
        settings,
        drogueria_id=drogueria_id,
        date_from=date(year - 1, 1, 1),
        date_to=date(year, 12, 31),
    )
    pay = _index_payments(pay_rows, tz)
    sales = _index_sales(sale_rows)

    from app.services.stats.invoice_agg import build_year_invoice_block

    inv_period = invoices_repo.list_invoices(
        settings,
        drogueria_id=drogueria_id,
        date_from=date(year - 1, 1, 1),
        date_to=date(year, 12, 31),
    )
    inv_open = invoices_repo.list_open_invoices(
        settings, drogueria_id=drogueria_id
    )
    invoices = build_year_invoice_block(
        period_rows=inv_period,
        open_rows=inv_open,
        window=window,
        prev=prev,
        today=today,
    )

    qr_vals, qr_counts, _ = _month_totals_qr(pay, year, window.series_months)
    prev_qr_vals, prev_qr_counts, _ = _month_totals_qr(pay, year - 1, prev.kpi_months)
    sales_vals = _month_totals_sales(sales, year, window.series_months)
    prev_sales_vals = _month_totals_sales(sales, year - 1, prev.kpi_months)

    qr_count = sum(qr_counts[m] for m in window.kpi_months)
    qr_total = sum((qr_vals[m] for m in window.kpi_months), ZERO)
    prev_qr_count = sum(prev_qr_counts.get(m, 0) for m in prev.kpi_months)
    prev_qr_total = sum((prev_qr_vals.get(m, ZERO) for m in prev.kpi_months), ZERO)

    clients: set[str] = set()
    for d, b in pay.items():
        if d.year == year and d.month in window.kpi_months:
            clients |= b.clients

    sales_total = sum((sales_vals[m] for m in window.kpi_months), ZERO)
    prev_sales_total = sum(
        (prev_sales_vals.get(m, ZERO) for m in prev.kpi_months), ZERO
    )

    divisor = len(window.kpi_months) or 1
    worst_qr, best_qr = _extreme_months(window.kpi_months, qr_vals)
    worst_s, best_s = _extreme_months(window.kpi_months, sales_vals)

    shift_totals = [ZERO] * shift_count
    shift_filled = [0] * shift_count
    shift_month_vals: list[dict[int, Decimal]] = [
        {m: ZERO for m in window.kpi_months} for _ in range(shift_count)
    ]
    for d, b in sales.items():
        if d.year != year or d.month not in window.kpi_months:
            continue
        for n in range(1, shift_count + 1):
            amt = b.shifts.get(n)
            if amt is not None and amt > 0:
                shift_totals[n - 1] += amt
                shift_filled[n - 1] += 1
                shift_month_vals[n - 1][d.month] += amt

    worst_shift, best_shift = _extreme_shifts(shift_totals)
    by_shift = []
    best_slots: list[tuple[int, dict[str, Any]]] = []
    worst_slots: list[tuple[int, dict[str, Any]]] = []
    for n in range(1, shift_count + 1):
        filled = shift_filled[n - 1]
        t = shift_totals[n - 1]
        worst_m, best_m = _extreme_months(window.kpi_months, shift_month_vals[n - 1])
        by_shift.append(
            {
                "shift_no": n,
                "total": _money(t),
                "avg": _money(t / Decimal(filled)) if filled else None,
                "filled_days": filled,
                "best_month": best_m,
                "worst_month": worst_m,
            }
        )
        if best_m:
            best_slots.append((n, best_m))
        if worst_m:
            worst_slots.append((n, worst_m))

    qr_kpis = {
        "payments_count": qr_count,
        "total_value": _money(qr_total),
        "avg_payments_per_month": _ratio(Decimal(qr_count) / Decimal(divisor)),
        "avg_value_per_month": _money(qr_total / Decimal(divisor)),
        "avg_value_per_payment": _money(qr_total / Decimal(qr_count)) if qr_count else None,
        "best_month": best_qr,
        "worst_month": worst_qr,
        "unique_clients": len(clients),
        "vs_previous": {
            "payments_pct": _pct(Decimal(qr_count), Decimal(prev_qr_count)),
            "value_pct": _pct(qr_total, prev_qr_total),
        },
    }
    sales_kpis = {
        "total_value": _money(sales_total),
        "avg_value_per_month": _money(sales_total / Decimal(divisor)),
        "best_month": best_s,
        "worst_month": worst_s,
        "best_shift": best_shift,
        "worst_shift": worst_shift,
        "best_shift_month": _pick_shift_slot(best_slots, pick_max=True),
        "worst_shift_month": _pick_shift_slot(worst_slots, pick_max=False),
        "by_shift": by_shift,
        "vs_previous": {"value_pct": _pct(sales_total, prev_sales_total)},
    }

    qr_series = [
        {
            "month": m,
            "count": qr_counts[m],
            "value": _money(qr_vals[m]),
        }
        for m in window.series_months
    ]
    sales_series = [
        {"month": m, "value": _money(sales_vals[m])} for m in window.series_months
    ]

    return {
        "period": "year",
        "year": year,
        "drogueria_id": drogueria_id,
        "shift_count": shift_count,
        "divisor_months": divisor,
        "qr": {"kpis": qr_kpis, "series": qr_series},
        "sales": {"kpis": sales_kpis, "series": sales_series},
        "invoices": invoices,
        "compare": _compare(
            qr_kpis["total_value"],
            sales_kpis["total_value"],
            invoices_issued=invoices["kpis"]["issued_total"],
            invoices_open_now=invoices["snapshot"]["open_now_total"],
        ),
    }
