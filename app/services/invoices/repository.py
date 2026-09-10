"""Access to suppliers and invoices."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings

SUPPLIERS_TABLE = "suppliers"
INVOICES_TABLE = "invoices"


def _require_url(settings: Settings) -> str:
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")
    return url


def require_url(settings: Settings) -> str:
    return _require_url(settings)


def _suppliers_ident() -> sql.Identifier:
    return sql.Identifier(SUPPLIERS_TABLE)


def _invoices_ident() -> sql.Identifier:
    return sql.Identifier(INVOICES_TABLE)


def list_suppliers(
    settings: Settings, *, q: str | None = None
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    needle = (q or "").strip()
    if needle:
        stmt = sql.SQL(
            "SELECT id, name, created_at FROM {} WHERE name ILIKE %s ORDER BY name ASC"
        ).format(_suppliers_ident())
        params: tuple[Any, ...] = (f"%{needle}%",)
    else:
        stmt = sql.SQL(
            "SELECT id, name, created_at FROM {} ORDER BY name ASC"
        ).format(_suppliers_ident())
        params = ()
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, params)
            return [dict(r) for r in cur.fetchall()]


def get_or_create_supplier(cur, *, name: str) -> dict[str, Any]:
    sel = sql.SQL(
        """
        SELECT id, name, created_at
        FROM {}
        WHERE lower(name) = lower(%s)
        """
    ).format(_suppliers_ident())
    cur.execute(sel, (name,))
    rec = cur.fetchone()
    if rec:
        return dict(rec)
    ins = sql.SQL(
        """
        INSERT INTO {} (name)
        VALUES (%s)
        RETURNING id, name, created_at
        """
    ).format(_suppliers_ident())
    cur.execute(ins, (name,))
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("get_or_create_supplier returned no row")
    return dict(created)


def get_supplier_by_id(cur, *, supplier_id: int) -> dict[str, Any] | None:
    stmt = sql.SQL(
        "SELECT id, name, created_at FROM {} WHERE id = %s"
    ).format(_suppliers_ident())
    cur.execute(stmt, (supplier_id,))
    rec = cur.fetchone()
    return dict(rec) if rec else None


def insert_invoice(
    cur,
    *,
    drogueria_id: int,
    supplier_id: int,
    invoice_number: str,
    invoice_date: date,
    due_date: date,
    amount: Decimal,
    status: str,
) -> dict[str, Any]:
    stmt = sql.SQL(
        """
        INSERT INTO {} (
            drogueria_id, supplier_id, invoice_number,
            invoice_date, due_date, amount, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING
            id, drogueria_id, supplier_id, invoice_number,
            invoice_date, due_date, amount, status,
            created_at, updated_at
        """
    ).format(_invoices_ident())
    cur.execute(
        stmt,
        (
            drogueria_id,
            supplier_id,
            invoice_number,
            invoice_date,
            due_date,
            amount,
            status,
        ),
    )
    rec = cur.fetchone()
    if rec is None:
        raise RuntimeError("insert_invoice returned no row")
    return dict(rec)


def list_invoices(
    settings: Settings,
    *,
    drogueria_id: int,
    supplier_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    conds: list[sql.SQL] = [sql.SQL("i.drogueria_id = %s")]
    params: list[Any] = [drogueria_id]
    if supplier_id is not None:
        conds.append(sql.SQL("i.supplier_id = %s"))
        params.append(supplier_id)
    if date_from is not None:
        conds.append(sql.SQL("i.invoice_date >= %s"))
        params.append(date_from)
    if date_to is not None:
        conds.append(sql.SQL("i.invoice_date <= %s"))
        params.append(date_to)
    where = sql.SQL(" AND ").join(conds)
    stmt = sql.SQL(
        """
        SELECT
            i.id, i.drogueria_id, i.supplier_id, s.name AS supplier,
            i.invoice_number, i.invoice_date, i.due_date,
            i.amount, i.status, i.created_at, i.updated_at
        FROM {} i
        JOIN {} s ON s.id = i.supplier_id
        WHERE {}
        ORDER BY i.due_date ASC, i.id ASC
        """
    ).format(_invoices_ident(), _suppliers_ident(), where)
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, params)
            return [dict(r) for r in cur.fetchall()]


def get_invoice(settings: Settings, invoice_id: int) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT
            i.id, i.drogueria_id, i.supplier_id, s.name AS supplier,
            i.invoice_number, i.invoice_date, i.due_date,
            i.amount, i.status, i.created_at, i.updated_at
        FROM {} i
        JOIN {} s ON s.id = i.supplier_id
        WHERE i.id = %s
        """
    ).format(_invoices_ident(), _suppliers_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (invoice_id,))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def update_invoice(
    settings: Settings,
    invoice_id: int,
    *,
    status: str | None = None,
    amount: Decimal | None = None,
    supplier_id: int | None = None,
    due_date: date | None = None,
) -> dict[str, Any] | None:
    sets: list[sql.SQL] = []
    params: list[Any] = []
    if status is not None:
        sets.append(sql.SQL("status = %s"))
        params.append(status)
    if amount is not None:
        sets.append(sql.SQL("amount = %s"))
        params.append(amount)
    if supplier_id is not None:
        sets.append(sql.SQL("supplier_id = %s"))
        params.append(supplier_id)
    if due_date is not None:
        sets.append(sql.SQL("due_date = %s"))
        params.append(due_date)
    if not sets:
        return get_invoice(settings, invoice_id)
    params.append(invoice_id)
    url = _require_url(settings)
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            upd = sql.SQL("UPDATE {} SET {} WHERE id = %s RETURNING id").format(
                _invoices_ident(),
                sql.SQL(", ").join(sets),
            )
            cur.execute(upd, params)
            rec = cur.fetchone()
            if rec is None:
                return None
        conn.commit()
    return get_invoice(settings, invoice_id)


def list_open_invoices(
    settings: Settings, *, drogueria_id: int
) -> list[dict[str, Any]]:
    """Stored status pending (overdue is derived on read)."""
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT
            i.id, i.drogueria_id, i.supplier_id, s.name AS supplier,
            i.invoice_number, i.invoice_date, i.due_date,
            i.amount, i.status, i.created_at, i.updated_at
        FROM {} i
        JOIN {} s ON s.id = i.supplier_id
        WHERE i.drogueria_id = %s AND i.status = 'pending'
        ORDER BY i.due_date ASC, i.id ASC
        """
    ).format(_invoices_ident(), _suppliers_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id,))
            return [dict(r) for r in cur.fetchall()]
