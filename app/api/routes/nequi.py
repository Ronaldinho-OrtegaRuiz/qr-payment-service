"""Nequi payments API: phone ingest + frontend list/assign."""

from __future__ import annotations

import asyncio
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.nequi.service import (
    NequiError,
    assign_nequi,
    ingest_batch,
    list_nequi,
)

router = APIRouter(tags=["nequi"])


class NequiItem(BaseModel):
    id: int
    client: str
    value: str
    notified_at: str
    drogueria_id: int | None = None
    notification_key: str
    raw_text: str = ""
    device_id: str | None = None
    assigned_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NequiListResponse(BaseModel):
    items: list[NequiItem]
    total: int
    page: int
    page_size: int
    pages: int


class NequiIngestItem(BaseModel):
    client: str
    value: str | Decimal | float | int
    notified_at: datetime | int | float | str
    notification_key: str
    raw_text: str = ""
    device_id: str | None = None

    @field_validator("client", "notification_key", mode="before")
    @classmethod
    def strip_req(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class NequiIngestBody(BaseModel):
    items: list[NequiIngestItem] = Field(min_length=1, max_length=100)


class NequiAssignBody(BaseModel):
    drogueria_id: int | None = Field(default=None, ge=1)


def _http(e: NequiError) -> HTTPException:
    status = (
        404
        if e.code in {"drogueria_not_found", "nequi_not_found"}
        else 400
    )
    return HTTPException(status_code=status, detail=e.message)


def _db_or_503() -> None:
    if not get_settings().database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")


def _check_device_key(request: Request, x_nequi_device_key: str | None) -> None:
    expected = get_settings().nequi_device_key
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Falta NEQUI_DEVICE_KEY en el servidor",
        )
    got = (x_nequi_device_key or "").strip()
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="Invalid device key")


@router.post("/nequi-payments/ingest")
async def post_nequi_ingest(
    request: Request,
    body: NequiIngestBody,
    x_nequi_device_key: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    """Ingest from phone app (device key). Idempotent by notification_key."""
    _db_or_503()
    _check_device_key(request, x_nequi_device_key)
    items = [x.model_dump() for x in body.items]
    try:
        return await asyncio.to_thread(ingest_batch, get_settings(), items)
    except NequiError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise


@router.get("/nequi-payments", response_model=NequiListResponse)
async def get_nequi_payments(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    assigned: Annotated[
        Literal["true", "false", "all"] | None,
        Query(description="true=con droguería, false=sin asignar, all=todas"),
    ] = "all",
    drogueria_id: Annotated[int | None, Query(ge=1)] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> NequiListResponse:
    """Lista unificada (sin forzar Ricky/Yessi). Filtros opcionales."""
    _db_or_503()
    try:
        payload = await asyncio.to_thread(
            list_nequi,
            get_settings(),
            assigned=assigned,
            drogueria_id=drogueria_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except NequiError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return NequiListResponse(**payload)


@router.patch("/nequi-payments/{payment_id}", response_model=NequiItem)
async def patch_nequi_payment(
    payment_id: Annotated[int, Path(ge=1)],
    body: NequiAssignBody,
) -> NequiItem:
    """Asigna o quita droguería (null = desasignar)."""
    _db_or_503()
    try:
        row = await asyncio.to_thread(
            assign_nequi,
            get_settings(),
            payment_id,
            body.drogueria_id,
        )
    except NequiError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return NequiItem(**row)
