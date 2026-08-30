"""Catálogo de droguerías: listado y número de turnos."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.sales import repository as sales_repo
from app.services.sales.service import (
    MAX_SHIFT_COUNT,
    MIN_SHIFT_COUNT,
    SalesError,
    set_shift_count,
)

router = APIRouter(tags=["droguerias"])


class DrogueriaItem(BaseModel):
    id: int
    name: str
    shift_count: int


class ShiftCountBody(BaseModel):
    shift_count: int = Field(ge=MIN_SHIFT_COUNT, le=MAX_SHIFT_COUNT)


def _http_from_sales_error(e: SalesError) -> HTTPException:
    status = 404 if e.code == "drogueria_not_found" else 400
    return HTTPException(status_code=status, detail=e.message)


@router.get("/droguerias", response_model=list[DrogueriaItem])
async def get_droguerias() -> list[DrogueriaItem]:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")
    try:
        rows = await asyncio.to_thread(sales_repo.list_droguerias, settings)
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [DrogueriaItem(**r) for r in rows]


@router.patch(
    "/droguerias/{drogueria_id}",
    response_model=DrogueriaItem,
)
async def patch_drogueria_shift_count(
    drogueria_id: Annotated[int, Path(ge=1)],
    body: ShiftCountBody,
) -> DrogueriaItem:
    settings = get_settings()
    if not settings.database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")
    try:
        row = await asyncio.to_thread(
            set_shift_count, settings, drogueria_id, body.shift_count
        )
    except SalesError as e:
        raise _http_from_sales_error(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return DrogueriaItem(**row)
