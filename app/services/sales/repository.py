"""Acceso a droguerías y shift_sales."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings

DROGUERIAS_TABLE = "droguerías"
SHIFT_SALES_TABLE = "shift_sales"


def _droguerias_ident() -> sql.Identifier:
    return sql.Identifier(DROGUERIAS_TABLE)


def _shift_sales_ident() -> sql.Identifier:
    return sql.Identifier(SHIFT_SALES_TABLE)


def _require_url(settings: Settings) -> str:
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")
    return url


def list_droguerias(settings: Settings) -> list[dict[str, Any]]:
    url = _require_url(settings)
    stmt = sql.SQL(
        "SELECT id, name, shift_count FROM {} ORDER BY id"
    ).format(_droguerias_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt)
            return [dict(r) for r in cur.fetchall()]


def get_drogueria(settings: Settings, drogueria_id: int) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        "SELECT id, name, shift_count FROM {} WHERE id = %s"
    ).format(_droguerias_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id,))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def update_shift_count(
    settings: Settings, drogueria_id: int, shift_count: int
) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        UPDATE {}
        SET shift_count = %s
        WHERE id = %s
        RETURNING id, name, shift_count
        """
    ).format(_droguerias_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (shift_count, drogueria_id))
            rec = cur.fetchone()
        conn.commit()
    return dict(rec) if rec else None


def list_shift_sales_in_range(
    settings: Settings,
    *,
    drogueria_id: int,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT drogueria_id, sale_date, shift_no, amount
        FROM {}
        WHERE drogueria_id = %s
          AND sale_date >= %s
          AND sale_date <= %s
        ORDER BY sale_date ASC, shift_no ASC
        """
    ).format(_shift_sales_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, date_from, date_to))
            return [dict(r) for r in cur.fetchall()]


def upsert_shift_sale(
    settings: Settings,
    *,
    drogueria_id: int,
    sale_date: date,
    shift_no: int,
    amount: Decimal,
) -> dict[str, Any]:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        INSERT INTO {} (drogueria_id, sale_date, shift_no, amount)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (drogueria_id, sale_date, shift_no)
        DO UPDATE SET amount = EXCLUDED.amount
        RETURNING id, drogueria_id, sale_date, shift_no, amount, created_at, updated_at
        """
    ).format(_shift_sales_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, sale_date, shift_no, amount))
            rec = cur.fetchone()
        conn.commit()
    if rec is None:
        raise RuntimeError("upsert_shift_sale no devolvió fila")
    return dict(rec)
