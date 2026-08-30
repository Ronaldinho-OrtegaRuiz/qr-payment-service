"""Ventas por turnos: rango de días (eslabones) y upsert de un valor."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.sales.service import SalesError, list_sales_range, save_shift_amount

router = APIRouter(tags=["sales"])


class ShiftItem(BaseModel):
    shift_no: int
    amount: str | None = None


class DaySalesDto(BaseModel):
    date: date
    shifts: list[ShiftItem]
    total: str


class SalesRangeDto(BaseModel):
    drogueria_id: int
    shift_count: int
    date_from: date
    date_to: date
    range_total: str
    days: list[DaySalesDto]


class ShiftAmountBody(BaseModel):
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


def _http_from_sales_error(e: SalesError) -> HTTPException:
    status = 404 if e.code == "drogueria_not_found" else 400
    return HTTPException(status_code=status, detail=e.message)


@router.get("/sales", response_model=SalesRangeDto)
async def get_sales_range(
    drogueria_id: Annotated[int, Query(ge=1)],
    date_from: Annotated[date, Query(description="Inicio inclusive (YYYY-MM-DD)")],
    date_to: Annotated[date, Query(description="Fin inclusive (YYYY-MM-DD)")],
) -> SalesRangeDto:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")
    try:
        payload = await asyncio.to_thread(
            list_sales_range,
            settings,
            drogueria_id=drogueria_id,
            date_from=date_from,
            date_to=date_to,
        )
    except SalesError as e:
        raise _http_from_sales_error(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return SalesRangeDto(**payload)


@router.put(
    "/sales/{drogueria_id}/{sale_date}/{shift_no}",
    response_model=DaySalesDto,
)
async def put_shift_sale(
    drogueria_id: Annotated[int, Path(ge=1)],
    sale_date: date,
    shift_no: Annotated[int, Path(ge=1, le=6)],
    body: ShiftAmountBody,
) -> DaySalesDto:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")
    try:
        day = await asyncio.to_thread(
            save_shift_amount,
            settings,
            drogueria_id=drogueria_id,
            sale_date=sale_date,
            shift_no=shift_no,
            amount=body.amount,
        )
    except SalesError as e:
        raise _http_from_sales_error(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return DaySalesDto(**day)
