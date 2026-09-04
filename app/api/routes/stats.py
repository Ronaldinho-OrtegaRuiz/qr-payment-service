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


class ExtremeShift(BaseModel):
    shift_no: int
    value: str


class ExtremeShiftDay(BaseModel):
    shift_no: int
    date: date
    value: str


class ExtremeShiftMonth(BaseModel):
    shift_no: int
    month: int
    value: str


class ShiftMonthKpi(BaseModel):
    shift_no: int
    total: str
    avg: str | None = None
    filled_days: int
    best_day: ExtremeDay | None = None
    worst_day: ExtremeDay | None = None


class ShiftYearKpi(BaseModel):
    shift_no: int
    total: str
    avg: str | None = None
    filled_days: int
    best_month: ExtremeMonth | None = None
    worst_month: ExtremeMonth | None = None


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
    best_shift: ExtremeShift | None = None
    worst_shift: ExtremeShift | None = None
    best_shift_day: ExtremeShiftDay | None = None
    worst_shift_day: ExtremeShiftDay | None = None
    by_shift: list[ShiftMonthKpi]
    vs_previous: VsPreviousDto


class CompareDto(BaseModel):
    qr_total: str
    sales_total: str
    delta: str
    qr_share: str | None = None
    invoices_issued: str
    invoices_open_now: str


class InvoiceVsPreviousDto(BaseModel):
    count_pct: str | None = None
    value_pct: str | None = None


class SupplierPeriodKpi(BaseModel):
    supplier_id: int
    supplier: str
    issued_count: int
    issued_total: str
    paid_total: str
    open_total: str
    overdue_total: str


class SupplierOpenKpi(BaseModel):
    supplier_id: int
    supplier: str
    open_total: str
    overdue_total: str


class AgingBucket(BaseModel):
    count: int
    total: str


class InvoiceAgingDto(BaseModel):
    not_due: AgingBucket
    d1_7: AgingBucket
    d8_30: AgingBucket
    d31_plus: AgingBucket


class InvoiceSnapshotDto(BaseModel):
    open_now_count: int
    open_now_total: str
    overdue_now_count: int
    overdue_now_total: str
    due_7d_count: int
    due_7d_total: str
    aging: InvoiceAgingDto
    by_supplier_open: list[SupplierOpenKpi]


class InvoiceMonthKpis(BaseModel):
    issued_count: int
    issued_total: str
    avg_amount: str | None = None
    paid_count: int
    paid_total: str
    open_count: int
    open_total: str
    overdue_count: int
    overdue_total: str
    vs_previous: InvoiceVsPreviousDto
    by_supplier: list[SupplierPeriodKpi]


class InvoiceDayPoint(BaseModel):
    date: date
    count: int
    amount: str


class InvoiceMonthBlock(BaseModel):
    kpis: InvoiceMonthKpis
    series: list[InvoiceDayPoint]
    snapshot: InvoiceSnapshotDto


class InvoiceYearKpis(BaseModel):
    issued_count: int
    issued_total: str
    avg_amount: str | None = None
    avg_issued_per_month: str
    paid_count: int
    paid_total: str
    open_count: int
    open_total: str
    overdue_count: int
    overdue_total: str
    best_month: ExtremeMonth | None = None
    worst_month: ExtremeMonth | None = None
    vs_previous: InvoiceVsPreviousDto
    by_supplier: list[SupplierPeriodKpi]


class InvoiceYearPoint(BaseModel):
    month: int
    count: int
    amount: str


class InvoiceYearBlock(BaseModel):
    kpis: InvoiceYearKpis
    series: list[InvoiceYearPoint]
    snapshot: InvoiceSnapshotDto


class QrMonthBlock(BaseModel):
    kpis: QrMonthKpis
    series: list[QrDayPoint]


class SalesMonthBlock(BaseModel):
    kpis: SalesMonthKpis
    series: list[SalesDayPoint]


class ExtremeEmployee(BaseModel):
    employee_id: int
    employee: str
    value: str


class ExtremeEmployeeDay(BaseModel):
    employee_id: int
    employee: str
    date: date
    value: str


class ExtremeEmployeeMonth(BaseModel):
    employee_id: int
    employee: str
    month: int
    value: str


class EmployeeMonthKpi(BaseModel):
    employee_id: int
    employee: str
    assigned_shifts: int
    covered_shifts: int
    total: str
    avg: str | None = None
    best_day: ExtremeDay | None = None
    worst_day: ExtremeDay | None = None


class EmployeeMonthKpis(BaseModel):
    assigned_shifts: int
    covered_shifts: int
    total_value: str
    best_employee: ExtremeEmployee | None = None
    worst_employee: ExtremeEmployee | None = None
    best_employee_day: ExtremeEmployeeDay | None = None
    worst_employee_day: ExtremeEmployeeDay | None = None
    by_employee: list[EmployeeMonthKpi]


class EmployeeMonthBlock(BaseModel):
    kpis: EmployeeMonthKpis


class EmployeeYearKpi(BaseModel):
    employee_id: int
    employee: str
    assigned_shifts: int
    covered_shifts: int
    total: str
    avg: str | None = None
    best_month: ExtremeMonth | None = None
    worst_month: ExtremeMonth | None = None


class EmployeeYearKpis(BaseModel):
    assigned_shifts: int
    covered_shifts: int
    total_value: str
    best_employee: ExtremeEmployee | None = None
    worst_employee: ExtremeEmployee | None = None
    best_employee_month: ExtremeEmployeeMonth | None = None
    worst_employee_month: ExtremeEmployeeMonth | None = None
    by_employee: list[EmployeeYearKpi]


class EmployeeYearBlock(BaseModel):
    kpis: EmployeeYearKpis


class MonthStatsDto(BaseModel):
    period: Literal["month"]
    year: int
    month: int
    drogueria_id: int
    shift_count: int
    divisor_days: int
    qr: QrMonthBlock
    sales: SalesMonthBlock
    invoices: InvoiceMonthBlock
    employees: EmployeeMonthBlock
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
    best_shift: ExtremeShift | None = None
    worst_shift: ExtremeShift | None = None
    best_shift_month: ExtremeShiftMonth | None = None
    worst_shift_month: ExtremeShiftMonth | None = None
    by_shift: list[ShiftYearKpi]
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
    invoices: InvoiceYearBlock
    employees: EmployeeYearBlock
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
