"""Acceso a nequi_payments."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings

NEQUI_TABLE = "nequi_payments"


def _require_url(settings: Settings) -> str:
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")
    return url


def _table() -> sql.Identifier:
    return sql.Identifier(NEQUI_TABLE)


def insert_if_new(
    settings: Settings,
    *,
    client: str,
    value: Decimal,
    notified_at: datetime,
    notification_key: str,
    raw_text: str,
    device_id: str | None,
) -> dict[str, Any] | None:
    """INSERT ... ON CONFLICT DO NOTHING. Returns row if inserted, else None."""
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        INSERT INTO {} (
          client, value, notified_at, notification_key, raw_text, device_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (notification_key) DO NOTHING
        RETURNING
          id, client, value, notified_at, drogueria_id, notification_key,
          raw_text, device_id, assigned_at, created_at, updated_at
        """
    ).format(_table())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                stmt,
                (client, value, notified_at, notification_key, raw_text, device_id),
            )
            rec = cur.fetchone()
        conn.commit()
    return dict(rec) if rec else None


def get_by_id(settings: Settings, payment_id: int) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT
          id, client, value, notified_at, drogueria_id, notification_key,
          raw_text, device_id, assigned_at, created_at, updated_at
        FROM {}
        WHERE id = %s
        """
    ).format(_table())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (payment_id,))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def list_payments(
    settings: Settings,
    *,
    assigned: str | None,
    drogueria_id: int | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    url = _require_url(settings)
    where: list[sql.SQL] = []
    params: list[Any] = []

    if assigned == "false":
        where.append(sql.SQL("drogueria_id IS NULL"))
    elif assigned == "true":
        where.append(sql.SQL("drogueria_id IS NOT NULL"))

    if drogueria_id is not None:
        where.append(sql.SQL("drogueria_id = %s"))
        params.append(drogueria_id)

    if date_from is not None:
        where.append(sql.SQL("notified_at::date >= %s"))
        params.append(date_from)
    if date_to is not None:
        where.append(sql.SQL("notified_at::date <= %s"))
        params.append(date_to)

    where_sql = sql.SQL(" AND ").join(where) if where else sql.SQL("TRUE")
    offset = (page - 1) * page_size

    count_stmt = sql.SQL("SELECT count(*) AS n FROM {} WHERE {}").format(
        _table(), where_sql
    )
    list_stmt = sql.SQL(
        """
        SELECT
          id, client, value, notified_at, drogueria_id, notification_key,
          raw_text, device_id, assigned_at, created_at, updated_at
        FROM {}
        WHERE {}
        ORDER BY notified_at DESC, id DESC
        LIMIT %s OFFSET %s
        """
    ).format(_table(), where_sql)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(count_stmt, params)
            total = int(cur.fetchone()["n"])
            cur.execute(list_stmt, [*params, page_size, offset])
            rows = [dict(r) for r in cur.fetchall()]
    return rows, total


def assign_drogueria(
    settings: Settings,
    payment_id: int,
    drogueria_id: int | None,
) -> dict[str, Any] | None:
    url = _require_url(settings)
    if drogueria_id is None:
        stmt = sql.SQL(
            """
            UPDATE {}
            SET drogueria_id = NULL, assigned_at = NULL
            WHERE id = %s
            RETURNING
              id, client, value, notified_at, drogueria_id, notification_key,
              raw_text, device_id, assigned_at, created_at, updated_at
            """
        ).format(_table())
        params: tuple[Any, ...] = (payment_id,)
    else:
        stmt = sql.SQL(
            """
            UPDATE {}
            SET drogueria_id = %s, assigned_at = now()
            WHERE id = %s
            RETURNING
              id, client, value, notified_at, drogueria_id, notification_key,
              raw_text, device_id, assigned_at, created_at, updated_at
            """
        ).format(_table())
        params = (drogueria_id, payment_id)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, params)
            rec = cur.fetchone()
        conn.commit()
    return dict(rec) if rec else None


def delete_payment(settings: Settings, payment_id: int) -> bool:
    url = _require_url(settings)
    stmt = sql.SQL("DELETE FROM {} WHERE id = %s RETURNING id").format(_table())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (payment_id,))
            rec = cur.fetchone()
        conn.commit()
    return rec is not None


def list_in_range(
    settings: Settings,
    *,
    drogueria_id: int,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Filas notified_at/value/client con notified_at en [start, end) y drogueria asignada."""
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT notified_at AS date, value, client
        FROM {}
        WHERE notified_at >= %s AND notified_at < %s
          AND drogueria_id = %s
        ORDER BY notified_at ASC
        """
    ).format(_table())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (start, end, drogueria_id))
            return [dict(r) for r in cur.fetchall()]
