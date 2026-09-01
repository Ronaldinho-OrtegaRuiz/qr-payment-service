"""Suppliers and invoices (bulk create, overdue derived on read)."""

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
    create_invoices_batch,
    get_invoice_dto,
    list_invoices_dto,
    list_suppliers_dto,
    parse_money,
    set_invoice_status,
)

router = APIRouter(tags=["invoices"])


class SupplierItem(BaseModel):
    id: int
    name: str


class InvoiceItem(BaseModel):
    id: int
    drogueria_id: int
    supplier_id: int
    supplier: str
    invoice_number: str
    invoice_date: date
    due_date: date
    amount: str
    status: Literal["pending", "paid", "overdue"]


class InvoiceCreateItem(BaseModel):
    supplier_id: int | None = Field(default=None, ge=1)
    supplier: str | None = None
    invoice_number: str
    invoice_date: date
    due_date: date
    amount: str | Decimal
    status: Literal["pending", "paid"] = "pending"

    @field_validator("invoice_number", "supplier", mode="before")
    @classmethod
    def strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: object) -> str:
        try:
            return str(parse_money(v))
        except InvoiceError as e:
            raise ValueError(e.message) from e

    @model_validator(mode="after")
    def supplier_id_or_name(self) -> InvoiceCreateItem:
        if self.supplier_id is None and not self.supplier:
            raise ValueError("Send supplier_id or supplier (name)")
        return self


class InvoiceBatchBody(BaseModel):
    drogueria_id: int = Field(ge=1)
    items: list[InvoiceCreateItem] = Field(min_length=1, max_length=50)


class InvoiceStatusBody(BaseModel):
    status: Literal["pending", "paid"]


def _http(e: InvoiceError) -> HTTPException:
    status = (
        404
        if e.code
        in {"drogueria_not_found", "supplier_not_found", "invoice_not_found"}
        else 400
    )
    return HTTPException(status_code=status, detail=e.message)


def _db_or_503() -> None:
    if not get_settings().database_url.strip():
        raise HTTPException(status_code=503, detail="Falta DATABASE_URL en .env")


@router.get("/suppliers", response_model=list[SupplierItem])
async def get_suppliers() -> list[SupplierItem]:
    _db_or_503()
    try:
        rows = await asyncio.to_thread(list_suppliers_dto, get_settings())
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return [SupplierItem(**r) for r in rows]


@router.get("/invoices", response_model=list[InvoiceItem])
async def get_invoices(
    drogueria_id: Annotated[int, Query(ge=1)],
    supplier_id: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[
        Literal["pending", "paid", "overdue"] | None, Query()
    ] = None,
    date_from: Annotated[
        date | None, Query(description="invoice_date start inclusive")
    ] = None,
    date_to: Annotated[
        date | None, Query(description="invoice_date end inclusive")
    ] = None,
) -> list[InvoiceItem]:
    _db_or_503()
    try:
        rows = await asyncio.to_thread(
            list_invoices_dto,
            get_settings(),
            drogueria_id=drogueria_id,
            supplier_id=supplier_id,
            status=status,
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
            create_invoices_batch,
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


@router.get("/invoices/{invoice_id}", response_model=InvoiceItem)
async def get_invoice(
    invoice_id: Annotated[int, Path(ge=1)],
) -> InvoiceItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(get_invoice_dto, get_settings(), invoice_id)
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return InvoiceItem(**row)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceItem)
async def patch_invoice(
    invoice_id: Annotated[int, Path(ge=1)],
    body: InvoiceStatusBody,
) -> InvoiceItem:
    _db_or_503()
    try:
        row = await asyncio.to_thread(
            set_invoice_status, get_settings(), invoice_id, body.status
        )
    except InvoiceError as e:
        raise _http(e) from e
    except ValueError as e:
        if str(e) == "missing_database_url":
            raise HTTPException(status_code=503, detail="Falta DATABASE_URL") from e
        raise
    return InvoiceItem(**row)
