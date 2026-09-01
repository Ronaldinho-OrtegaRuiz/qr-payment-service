"""Proveedores y facturas (lote, vencida automática)."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings
from app.services.invoices.service import (
    InvoiceError,
    create_facturas_batch,
    get_factura_dto,
    list_facturas_dto,
    list_proveedores_dto,
    parse_money,
    set_factura_estado,
)

router = APIRouter(tags=["invoices"])


class ProveedorItem(BaseModel):
    id: int
    drogueria_id: int
    name: str


class InvoiceItem(BaseModel):
    id: int
    drogueria_id: int
    proveedor_id: int
    proveedor: str
    numero_factura: str
    fecha_factura: date
    fecha_vencimiento: date
    valor: str
    estado: Literal["pendiente", "pagada", "vencida"]


class InvoiceCreateItem(BaseModel):
    proveedor_id: int | None = Field(default=None, ge=1)
    proveedor: str | None = None
    numero_factura: str
    fecha_factura: date
    fecha_vencimiento: date
    valor: str | Decimal
    estado: Literal["pendiente", "pagada"] = "pendiente"

    @field_validator("numero_factura", "proveedor", mode="before")
    @classmethod
    def strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("valor", mode="before")
    @classmethod
    def parse_valor(cls, v: object) -> str:
        try:
            return str(parse_money(v))
        except InvoiceError as e:
            raise ValueError(e.message) from e

    @model_validator(mode="after")
    def proveedor_id_or_name(self) -> InvoiceCreateItem:
        has_id = self.proveedor_id is not None
        has_name = bool(self.proveedor)
        if not has_id and not has_name:
            raise ValueError("Manda proveedor_id o proveedor (nombre)")
        return self


class InvoiceBatchBody(BaseModel):
    drogueria_id: int = Field(ge=1)
    items: list[InvoiceCreateItem] = Field(min_length=1, max_length=50)


class InvoiceEstadoBody(BaseModel):
    estado: Literal["pendiente", "pagada"]


def _http(e: InvoiceError) -> HTTPException:
    status = 404 if e.code in {"drogueria_not_found", "proveedor_not_found", "factura_not_found"} else 400
    return HTTPException(status_code=status, detail=e.message)


def _db_or_503() -> None:
    if not get_settings().database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")


@router.get("/proveedores", response_model=list[ProveedorItem])
async def get_proveedores(
    drogueria_id: Annotated[int, Query(ge=1)],
) -> list[ProveedorItem]:
    _db_or_503()
    try:
        rows = await asyncio.to_thread(
            list_proveedores_dto, get_settings(), drogueria_id
        )
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [ProveedorItem(**r) for r in rows]


@router.get("/invoices", response_model=list[InvoiceItem])
async def get_invoices(
    drogueria_id: Annotated[int, Query(ge=1)],
    proveedor_id: Annotated[int | None, Query(ge=1)] = None,
    estado: Annotated[
        Literal["pendiente", "pagada", "vencida"] | None, Query()
    ] = None,
    date_from: Annotated[
        date | None, Query(description="fecha_factura inicio inclusive")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="fecha_factura fin inclusive")
    ] = None,
) -> list[InvoiceItem]:
    _db_or_503()
    try:
        rows = await asyncio.to_thread(
            list_facturas_dto,
            get_settings(),
            drogueria_id=drogueria_id,
            proveedor_id=proveedor_id,
            estado=estado,
            date_from=date_from,
            date_to=date_to,
        )
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [InvoiceItem(**r) for r in rows]


@router.post("/invoices", response_model=list[InvoiceItem])
async def post_invoices(body: InvoiceBatchBody) -> list[InvoiceItem]:
    _db_or_503()
    items: list[dict[str, Any]] = [x.model_dump() for x in body.items]
    try:
        rows = await asyncio.to_thread(
            create_facturas_batch,
            get_settings(),
            drogueria_id=body.drogueria_id,
            items=items,
        )
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [InvoiceItem(**r) for r in rows]


@router.get("/invoices/{factura_id}", response_model=InvoiceItem)
async def get_invoice(
    factura_id: Annotated[int, Path(ge=1)],
) -> InvoiceItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(get_factura_dto, get_settings(), factura_id)
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return InvoiceItem(**row)


@router.patch("/invoices/{factura_id}", response_model=InvoiceItem)
async def patch_invoice(
    factura_id: Annotated[int, Path(ge=1)],
    body: InvoiceEstadoBody,
) -> InvoiceItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(
            set_factura_estado, get_settings(), factura_id, body.estado
        )
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return InvoiceItem(**row)
