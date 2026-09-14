"""Estadísticas de pagos Nequi por droguería (mes / año)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.services.nequi import repository as nequi_repo
from app.services.payments.repository import get_payments_timezone
from app.services.sales import repository as sales_repo
from app.services.stats.service import (
    ZERO,
    StatsError,
    _extreme_months,
    _index_payments,
    _money,
    _month_totals_qr,
    _pct,
    _qr_kpis_month,
    _qr_series_month,
    _ratio,
    build_month_window,
    build_prev_month_window,
    build_year_window,
)


def get_nequi_month_stats(
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

    rows = nequi_repo.list_in_range(
        settings,
        drogueria_id=drogueria_id,
        start=prev.start,
        end=window.end,
    )
    buckets = _index_payments(rows, tz)
    kpis = _qr_kpis_month(buckets, window.kpi_dates, buckets, prev.kpi_dates)
    return {
        "period": "month",
        "year": year,
        "month": month,
        "drogueria_id": drogueria_id,
        "divisor_days": len(window.kpi_dates),
        "kpis": kpis,
        "series": _qr_series_month(buckets, window.series_dates),
    }


def get_nequi_year_stats(
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
    if year == today.year:
        prev.kpi_months = list(window.kpi_months)

    rows = nequi_repo.list_in_range(
        settings,
        drogueria_id=drogueria_id,
        start=prev.start,
        end=window.end,
    )
    buckets = _index_payments(rows, tz)

    vals, counts, _ = _month_totals_qr(buckets, year, window.series_months)
    prev_vals, prev_counts, _ = _month_totals_qr(buckets, year - 1, prev.kpi_months)

    count = sum(counts[m] for m in window.kpi_months)
    total = sum((vals[m] for m in window.kpi_months), ZERO)
    prev_count = sum(prev_counts.get(m, 0) for m in prev.kpi_months)
    prev_total = sum((prev_vals.get(m, ZERO) for m in prev.kpi_months), ZERO)

    clients: set[str] = set()
    for d, b in buckets.items():
        if d.year == year and d.month in window.kpi_months:
            clients |= b.clients

    divisor = len(window.kpi_months) or 1
    worst, best = _extreme_months(window.kpi_months, vals)

    series = [
        {
            "month": m,
            "count": counts[m],
            "value": _money(vals[m]),
        }
        for m in window.series_months
    ]

    return {
        "period": "year",
        "year": year,
        "drogueria_id": drogueria_id,
        "divisor_months": divisor,
        "kpis": {
            "payments_count": count,
            "total_value": _money(total),
            "avg_payments_per_month": _ratio(Decimal(count) / Decimal(divisor)),
            "avg_value_per_month": _money(total / Decimal(divisor)),
            "avg_value_per_payment": _money(total / Decimal(count)) if count else None,
            "best_month": best,
            "worst_month": worst,
            "unique_clients": len(clients),
            "vs_previous": {
                "payments_pct": _pct(Decimal(count), Decimal(prev_count)),
                "value_pct": _pct(total, prev_total),
            },
        },
        "series": series,
    }
