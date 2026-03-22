"""Inserción de pagos en Postgres (misma forma que el script de carga masiva)."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings


def _payments_table_ident() -> sql.Identifier:
    t = (os.getenv("PAYMENTS_TABLE") or "payments").strip()
    if not t or not all(c.isalnum() or c == "_" for c in t):
        raise ValueError("PAYMENTS_TABLE inválido")
    return sql.Identifier(t)


def get_payments_timezone() -> ZoneInfo:
    name = (os.getenv("PAYMENTS_TZ") or "America/Bogota").strip()
    return ZoneInfo(name)


def _valor_a_decimal(s: str | None) -> Decimal | None:
    if s is None or not str(s).strip():
        return None
    clean = str(s).replace(",", "").strip()
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def _fecha_hora_a_timestamptz(
    fecha: str | None, hora: str | None, tz: ZoneInfo
) -> datetime | None:
    if not fecha or not hora:
        return None
    try:
        d = datetime.strptime(fecha.strip(), "%d/%m/%Y").date()
        t = datetime.strptime(hora.strip(), "%H:%M").time()
        return datetime.combine(d, t).replace(tzinfo=tz)
    except ValueError:
        return None


def mail_entry_to_row(entry: dict, drogueria_id: int, tz: ZoneInfo) -> dict[str, Any] | None:
    if not entry.get("parse_ok"):
        return None
    mid = (entry.get("message_id") or "").strip()
    if not mid:
        return None
    client_name = (entry.get("nombre_cliente") or "").strip()
    if not client_name:
        return None
    val = _valor_a_decimal(entry.get("valor"))
    if val is None:
        return None
    dt = _fecha_hora_a_timestamptz(entry.get("fecha"), entry.get("hora"), tz)
    if dt is None:
        return None
    return {
        "drogueria_id": drogueria_id,
        "message_id": mid,
        "client": client_name,
        "value": val,
        "date": dt,
    }


def insert_payment_if_new(settings: Settings, row: dict[str, Any]) -> dict[str, Any] | None:
    """
    INSERT ... ON CONFLICT (message_id) DO NOTHING RETURNING *.
    Si la fila es nueva, devuelve dict serializable para WebSocket; si ya existía, None.
    """
    url = (settings.database_url or "").strip()
    if not url:
        return None

    table = _payments_table_ident()
    col_date = sql.Identifier("date")
    stmt = sql.SQL(
        """
        INSERT INTO {} (drogueria_id, message_id, client, value, {})
        VALUES (%(drogueria_id)s, %(message_id)s, %(client)s, %(value)s, %(date)s)
        ON CONFLICT (message_id) DO NOTHING
        RETURNING id, drogueria_id, message_id, client, value, {}
        """
    ).format(table, col_date, col_date)

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, row)
            rec = cur.fetchone()
        conn.commit()

    if not rec:
        return None
    out = dict(rec)
    if isinstance(out.get("date"), datetime):
        out["date"] = out["date"].isoformat()
    if isinstance(out.get("value"), Decimal):
        out["value"] = str(out["value"])
    return out
