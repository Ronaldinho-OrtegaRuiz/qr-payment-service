"""Invoices: bulk create, supplier by id or name, overdue derived on read."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from app.config import Settings
from app.services.invoices import repository as repo
from app.services.payments.repository import get_payments_timezone
from app.services.sales.repository import get_drogueria

MAX_BATCH = 50
STORED_STATUSES = frozenset({"pending", "paid"})
VISIBLE_STATUSES = frozenset({"pending", "paid", "overdue"})


class InvoiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_money(raw: Any) -> Decimal:
    """Accepts 150000.99 or 150000,99."""
    if isinstance(raw, Decimal):
        val = raw
    elif isinstance(raw, int):
        val = Decimal(raw)
    elif isinstance(raw, float):
        val = Decimal(str(raw))
    else:
        s = str(raw).strip().replace(" ", "")
        if not s:
            raise InvoiceError("invalid_amount", "amount is empty")
        if s.count(",") == 1 and "." not in s:
            s = s.replace(",", ".")
        try:
            val = Decimal(s)
        except InvalidOperation as e:
            raise InvoiceError("invalid_amount", "invalid amount") from e
    if val < 0:
        raise InvoiceError("invalid_amount", "amount cannot be negative")
    return val.quantize(Decimal("0.01"))


def resolve_status(stored: str, due_date: date, today: date) -> str:
    if stored == "paid":
        return "paid"
    if due_date <= today:
        return "overdue"
    return "pending"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"unexpected date: {type(value)!r}")


def _money_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _today() -> date:
    return datetime.now(get_payments_timezone()).date()


def _dto(row: dict[str, Any], today: date) -> dict[str, Any]:
    stored = str(row["status"])
    due = _as_date(row["due_date"])
    amount = row["amount"]
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return {
        "id": int(row["id"]),
        "drogueria_id": int(row["drogueria_id"]),
        "supplier_id": int(row["supplier_id"]),
        "supplier": row["supplier"],
        "invoice_number": row["invoice_number"],
        "invoice_date": _as_date(row["invoice_date"]),
        "due_date": due,
        "amount": _money_str(amount),
        "status": resolve_status(stored, due, today),
    }


def _require_drogueria(settings: Settings, drogueria_id: int) -> None:
    if get_drogueria(settings, drogueria_id) is None:
        raise InvoiceError("drogueria_not_found", "Drogueria not found")


def list_suppliers_dto(
    settings: Settings, *, q: str | None = None
) -> list[dict[str, Any]]:
    rows = repo.list_suppliers(settings, q=q)
    return [{"id": int(r["id"]), "name": r["name"]} for r in rows]


def create_invoices_batch(
    settings: Settings,
    *,
    drogueria_id: int,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        raise InvoiceError("empty_batch", "Send at least one invoice")
    if len(items) > MAX_BATCH:
        raise InvoiceError("batch_too_long", f"Maximum {MAX_BATCH} invoices per batch")

    _require_drogueria(settings, drogueria_id)
    today = _today()
    url = repo.require_url(settings)
    created: list[dict[str, Any]] = []

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for i, item in enumerate(items):
                try:
                    created.append(
                        _insert_one(cur, drogueria_id=drogueria_id, item=item, today=today)
                    )
                except InvoiceError as e:
                    raise InvoiceError(e.code, f"Item {i + 1}: {e.message}") from e
                except pg_errors.UniqueViolation as e:
                    raise InvoiceError(
                        "duplicate_invoice",
                        f"Item {i + 1}: invoice number already exists for that supplier",
                    ) from e
                except pg_errors.CheckViolation as e:
                    raise InvoiceError(
                        "invalid_invoice",
                        f"Item {i + 1}: invalid dates or amount",
                    ) from e
        conn.commit()
    return created


def _insert_one(
    cur, *, drogueria_id: int, item: dict[str, Any], today: date
) -> dict[str, Any]:
    supplier_id = item.get("supplier_id")
    name = (item.get("supplier") or "").strip()
    if supplier_id is not None:
        rec = repo.get_supplier_by_id(cur, supplier_id=int(supplier_id))
        if rec is None:
            raise InvoiceError("supplier_not_found", "Supplier not found")
        sid = int(rec["id"])
        sname = rec["name"]
    elif name:
        rec = repo.get_or_create_supplier(cur, name=name)
        sid = int(rec["id"])
        sname = rec["name"]
    else:
        raise InvoiceError(
            "missing_supplier",
            "Send supplier_id or supplier (name)",
        )

    number = str(item.get("invoice_number") or "").strip()
    if not number:
        raise InvoiceError("invalid_number", "invoice_number is empty")

    invoice_date = item["invoice_date"]
    due_date = item["due_date"]
    if due_date < invoice_date:
        raise InvoiceError(
            "invalid_dates",
            "due_date cannot be before invoice_date",
        )

    status = str(item.get("status") or "pending").strip().lower()
    if status == "overdue":
        status = "pending"
    if status not in STORED_STATUSES:
        raise InvoiceError("invalid_status", "status must be pending or paid")

    amount = parse_money(item.get("amount"))
    row = repo.insert_invoice(
        cur,
        drogueria_id=drogueria_id,
        supplier_id=sid,
        invoice_number=number,
        invoice_date=invoice_date,
        due_date=due_date,
        amount=amount,
        status=status,
    )
    row["supplier"] = sname
    return _dto(row, today)


def list_invoices_dto(
    settings: Settings,
    *,
    drogueria_id: int,
    supplier_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    _require_drogueria(settings, drogueria_id)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvoiceError("invalid_range", "date_from cannot be after date_to")
    if status is not None and status not in VISIBLE_STATUSES:
        raise InvoiceError(
            "invalid_status",
            "status must be pending, paid or overdue",
        )

    today = _today()
    rows = repo.list_invoices(
        settings,
        drogueria_id=drogueria_id,
        supplier_id=supplier_id,
        date_from=date_from,
        date_to=date_to,
    )
    out = [_dto(r, today) for r in rows]
    if status is not None:
        out = [x for x in out if x["status"] == status]
    return out


def get_invoice_dto(settings: Settings, invoice_id: int) -> dict[str, Any]:
    row = repo.get_invoice(settings, invoice_id)
    if row is None:
        raise InvoiceError("invoice_not_found", "Invoice not found")
    return _dto(row, _today())


def update_invoice_fields(
    settings: Settings,
    invoice_id: int,
    *,
    status: str | None = None,
    amount: Any = None,
) -> dict[str, Any]:
    stored_status: str | None = None
    if status is not None:
        stored_status = status.strip().lower()
        if stored_status == "overdue":
            raise InvoiceError(
                "invalid_status",
                "overdue is assigned automatically; set paid or pending",
            )
        if stored_status not in STORED_STATUSES:
            raise InvoiceError("invalid_status", "status must be pending or paid")
    parsed_amount: Decimal | None = None
    if amount is not None:
        parsed_amount = parse_money(amount)
    if stored_status is None and parsed_amount is None:
        raise InvoiceError("empty_patch", "Send status and/or amount")
    row = repo.update_invoice(
        settings, invoice_id, status=stored_status, amount=parsed_amount
    )
    if row is None:
        raise InvoiceError("invoice_not_found", "Invoice not found")
    return _dto(row, _today())
