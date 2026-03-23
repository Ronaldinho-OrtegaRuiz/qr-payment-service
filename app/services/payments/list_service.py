"""Listado paginado de pagos con filtros (Postgres)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings
from app.services.payments.repository import get_payments_timezone, payments_table_ident


def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("date"), datetime):
        out["date"] = out["date"].isoformat()
    if isinstance(out.get("value"), Decimal):
        out["value"] = str(out["value"])
    return out


def list_payments(
    settings: Settings,
    *,
    page: int,
    page_size: int,
    sort: Literal["asc", "desc"],
    on_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    value_min: Decimal | None = None,
    value_max: Decimal | None = None,
    drogueria_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Filtros de fecha interpretados en PAYMENTS_TZ (ej. America/Bogota), aplicados a la columna `date`.
    on_date tiene prioridad: ignora date_from / date_to ese día.
    """
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")

    table = payments_table_ident()
    col_date = sql.Identifier("date")
    tz = get_payments_timezone()
    conds: list[sql.SQL] = []
    params: list[Any] = []

    if on_date is not None:
        start = datetime.combine(on_date, time.min, tzinfo=tz)
        end = start + timedelta(days=1)
        conds.append(sql.SQL("{} >= %s AND {} < %s").format(col_date, col_date))
        params.extend([start, end])
    else:
        if date_from is not None:
            start = datetime.combine(date_from, time.min, tzinfo=tz)
            conds.append(sql.SQL("{} >= %s").format(col_date))
            params.append(start)
        if date_to is not None:
            end_excl = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
            conds.append(sql.SQL("{} < %s").format(col_date))
            params.append(end_excl)

    if value_min is not None:
        conds.append(sql.SQL("value >= %s"))
        params.append(value_min)
    if value_max is not None:
        conds.append(sql.SQL("value <= %s"))
        params.append(value_max)
    if drogueria_id is not None:
        conds.append(sql.SQL("drogueria_id = %s"))
        params.append(drogueria_id)

    where_clause = sql.SQL(" AND ").join(conds) if conds else sql.SQL("TRUE")
    order_dir = sql.SQL("ASC" if sort == "asc" else "DESC")
    offset = (page - 1) * page_size

    count_stmt = sql.SQL("SELECT COUNT(*)::bigint FROM {} WHERE {}").format(
        table, where_clause
    )
    select_stmt = sql.SQL(
        """
        SELECT id, drogueria_id, message_id, client, value, {}
        FROM {}
        WHERE {}
        ORDER BY {} {}
        LIMIT %s OFFSET %s
        """
    ).format(col_date, table, where_clause, col_date, order_dir)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(count_stmt, params)
            total_row = cur.fetchone()
            total = int(total_row["count"]) if total_row else 0

            cur.execute(select_stmt, [*params, page_size, offset])
            rows = cur.fetchall()

    items = [_serialize_row(dict(r)) for r in rows]
    return items, total


def list_payments_for_month(
    settings: Settings,
    *,
    month: int,
    year: int,
    drogueria_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Todos los pagos del mes calendario (1–12) en PAYMENTS_TZ, solo date y value.
    Rango: [inicio del mes, inicio del mes siguiente).
    """
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")

    tz = get_payments_timezone()
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    if month == 12:
        end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz)

    table = payments_table_ident()
    col_date = sql.Identifier("date")
    conds: list[sql.SQL] = [
        sql.SQL("{} >= %s AND {} < %s").format(col_date, col_date),
    ]
    params: list[Any] = [start, end]
    if drogueria_id is not None:
        conds.append(sql.SQL("drogueria_id = %s"))
        params.append(drogueria_id)
    where = sql.SQL(" AND ").join(conds)
    select_stmt = sql.SQL(
        "SELECT {}, value FROM {} WHERE {} ORDER BY {} ASC"
    ).format(col_date, table, where, col_date)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(select_stmt, params)
            rows = cur.fetchall()

    return [_serialize_row(dict(r)) for r in rows]
