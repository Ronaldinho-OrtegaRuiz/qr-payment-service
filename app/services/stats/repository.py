"""Consultas de pagos QR para estadísticas (rango timestamptz)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings
from app.services.payments.repository import payments_table_ident


def list_payments_in_range(
    settings: Settings,
    *,
    drogueria_id: int,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Filas date/value/client con date en [start, end)."""
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")

    table = payments_table_ident()
    col_date = sql.Identifier("date")
    stmt = sql.SQL(
        """
        SELECT {}, value, client
        FROM {}
        WHERE {} >= %s AND {} < %s
          AND drogueria_id = %s
        ORDER BY {} ASC
        """
    ).format(col_date, table, col_date, col_date, col_date)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (start, end, drogueria_id))
            return [dict(r) for r in cur.fetchall()]
