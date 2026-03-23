"""Listado de pagos con filtros y paginación."""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.payments.list_service import list_payments, list_payments_for_month
from app.services.payments.repository import get_payments_timezone

# Rutas completas (sin prefix + path "") para evitar choques de matching con subpaths.
router = APIRouter(tags=["payments"])


class PaymentItem(BaseModel):
    id: int
    drogueria_id: int
    message_id: str | None = None
    client: str
    value: str
    date: str


class PaymentListResponse(BaseModel):
    items: list[PaymentItem]
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)


class PaymentMonthRow(BaseModel):
    date: str
    value: str


@router.get("/payments/by-month", response_model=list[PaymentMonthRow])
async def get_payments_by_month(
    month: Annotated[
        int,
        Query(ge=1, le=12, description="Mes: 1=enero … 12=diciembre (calendario PAYMENTS_TZ)"),
    ],
    year: Annotated[
        int | None,
        Query(ge=1900, le=2100, description="Año; si omites, año actual en PAYMENTS_TZ"),
    ] = None,
    drogueria_id: Annotated[int | None, Query(description="Filtrar por droguería")] = None,
) -> list[PaymentMonthRow]:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")

    tz = get_payments_timezone()
    y = year if year is not None else datetime.now(tz).year

    try:
        rows = await asyncio.to_thread(
            list_payments_for_month,
            settings,
            month=month,
            year=y,
            drogueria_id=drogueria_id,
        )
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise HTTPException(status_code=400, detail=str(e)) from e

    return [PaymentMonthRow(**x) for x in rows]


@router.get("/payments", response_model=PaymentListResponse)
async def get_payments_list(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    sort: Annotated[
        Literal["asc", "desc"],
        Query(description="Orden por fecha del pago (columna date)"),
    ] = "desc",
    on_date: Annotated[
        date | None,
        Query(description="Día concreto (YYYY-MM-DD) en PAYMENTS_TZ; anula date_from/date_to"),
    ] = None,
    date_from: Annotated[
        date | None,
        Query(description="Inicio de rango inclusive (YYYY-MM-DD) en PAYMENTS_TZ"),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(description="Fin de rango inclusive (YYYY-MM-DD) en PAYMENTS_TZ"),
    ] = None,
    value_min: Annotated[Decimal | None, Query(description="Valor mínimo (numeric)")] = None,
    value_max: Annotated[Decimal | None, Query(description="Valor máximo (numeric)")] = None,
    drogueria_id: Annotated[int | None, Query()] = None,
) -> PaymentListResponse:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")

    try:
        items, total = await asyncio.to_thread(
            list_payments,
            settings,
            page=page,
            page_size=page_size,
            sort=sort,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            value_min=value_min,
            value_max=value_max,
            drogueria_id=drogueria_id,
        )
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise HTTPException(status_code=400, detail=str(e)) from e

    pages = (total + page_size - 1) // page_size if total else 0
    return PaymentListResponse(
        items=[PaymentItem(**x) for x in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
