"""Estadísticas de QR y ventas: mes o año, series + KPIs."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config import get_settings
from app.services.payments.repository import get_payments_timezone
from app.services.stats.service import StatsError, get_month_stats, get_year_stats

router = APIRouter(tags=["stats"])


class ExtremeDay(BaseModel):
    date: date
    value: str


class ExtremeMonth(BaseModel):
    month: int
    value: str


class VsPreviousDto(BaseModel):
    payments_pct: str | None = None
    value_pct: str | None = None


class QrDayPoint(BaseModel):
    date: date
    count: int
    value: str


class SalesShiftPoint(BaseModel):
    shift_no: int
    amount: str | None = None


class SalesDayPoint(BaseModel):
    date: date
    total: str
    shifts: list[SalesShiftPoint]


class ShiftKpi(BaseModel):
    shift_no: int
    total: str
    avg: str | None = None
    filled_days: int


class QrMonthKpis(BaseModel):
    payments_count: int
    total_value: str
    avg_payments_per_day: str
    avg_value_per_day: str
    avg_value_per_payment: str | None = None
    min_day: ExtremeDay | None = None
    max_day: ExtremeDay | None = None
    days_with_sales: int
    days_empty: int
    unique_clients: int
    vs_previous: VsPreviousDto


class SalesMonthKpis(BaseModel):
    total_value: str
    avg_value_per_day: str
    min_day: ExtremeDay | None = None
    max_day: ExtremeDay | None = None
    days_filled: int
    days_empty: int
    by_shift: list[ShiftKpi]
    vs_previous: VsPreviousDto


class CompareDto(BaseModel):
    qr_total: str
    sales_total: str
    delta: str
    qr_share: str | None = None


class QrMonthBlock(BaseModel):
    kpis: QrMonthKpis
    series: list[QrDayPoint]


class SalesMonthBlock(BaseModel):
    kpis: SalesMonthKpis
    series: list[SalesDayPoint]


class MonthStatsDto(BaseModel):
    period: Literal["month"]
    year: int
    month: int
    drogueria_id: int
    shift_count: int
    divisor_days: int
    qr: QrMonthBlock
    sales: SalesMonthBlock
    compare: CompareDto


class QrYearPoint(BaseModel):
    month: int
    count: int
    value: str


class SalesYearPoint(BaseModel):
    month: int
    value: str


class QrYearKpis(BaseModel):
    payments_count: int
    total_value: str
    avg_payments_per_month: str
    avg_value_per_month: str
    avg_value_per_payment: str | None = None
    best_month: ExtremeMonth | None = None
    worst_month: ExtremeMonth | None = None
    unique_clients: int
    vs_previous: VsPreviousDto


class SalesYearKpis(BaseModel):
    total_value: str
    avg_value_per_month: str
    best_month: ExtremeMonth | None = None
    worst_month: ExtremeMonth | None = None
    by_shift: list[ShiftKpi]
    vs_previous: VsPreviousDto


class QrYearBlock(BaseModel):
    kpis: QrYearKpis
    series: list[QrYearPoint]


class SalesYearBlock(BaseModel):
    kpis: SalesYearKpis
    series: list[SalesYearPoint]


class YearStatsDto(BaseModel):
    period: Literal["year"]
    year: int
    drogueria_id: int
    shift_count: int
    divisor_months: int
    qr: QrYearBlock
    sales: SalesYearBlock
    compare: CompareDto


def _http_from_stats_error(e: StatsError) -> HTTPException:
    status = 404 if e.code == "drogueria_not_found" else 400
    return HTTPException(status_code=status, detail=e.message)


@router.get(
    "/stats",
    response_model=MonthStatsDto | YearStatsDto,
    response_model_exclude_unset=False,
)
async def get_stats(
    drogueria_id: Annotated[int, Query(ge=1)],
    period: Annotated[Literal["month", "year"], Query()],
    year: Annotated[
        int | None,
        Query(ge=1900, le=2100, description="Año; default: actual en PAYMENTS_TZ"),
    ] = None,
    month: Annotated[
        int | None,
        Query(ge=1, le=12, description="Requerido si period=month; default: mes actual"),
    ] = None,
) -> MonthStatsDto | YearStatsDto:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")

    tz = get_payments_timezone()
    today = datetime.now(tz).date()
    y = year if year is not None else today.year

    try:
        if period == "month":
            m = month if month is not None else today.month
            payload = await asyncio.to_thread(
                get_month_stats,
                settings,
                drogueria_id=drogueria_id,
                year=y,
                month=m,
            )
            return MonthStatsDto(**payload)
        payload = await asyncio.to_thread(
            get_year_stats,
            settings,
            drogueria_id=drogueria_id,
            year=y,
        )
        return YearStatsDto(**payload)
    except StatsError as e:
        raise _http_from_stats_error(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
