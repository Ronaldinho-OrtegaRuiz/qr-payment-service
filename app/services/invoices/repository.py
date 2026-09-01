"""Acceso a proveedores y facturas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings

PROVEEDORES_TABLE = "proveedores"
FACTURAS_TABLE = "facturas"


def _require_url(settings: Settings) -> str:
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")
    return url


def _proveedores_ident() -> sql.Identifier:
    return sql.Identifier(PROVEEDORES_TABLE)


def _facturas_ident() -> sql.Identifier:
    return sql.Identifier(FACTURAS_TABLE)


def list_proveedores(settings: Settings, drogueria_id: int) -> list[dict[str, Any]]:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT id, drogueria_id, name, created_at
        FROM {}
        WHERE drogueria_id = %s
        ORDER BY name ASC
        """
    ).format(_proveedores_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id,))
            return [dict(r) for r in cur.fetchall()]


def get_proveedor(
    settings: Settings, drogueria_id: int, proveedor_id: int
) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT id, drogueria_id, name, created_at
        FROM {}
        WHERE id = %s AND drogueria_id = %s
        """
    ).format(_proveedores_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (proveedor_id, drogueria_id))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def get_or_create_proveedor(
    cur, *, drogueria_id: int, name: str
) -> dict[str, Any]:
    """Usa el cursor abierto (misma transacción). Match case-insensitive."""
    sel = sql.SQL(
        """
        SELECT id, drogueria_id, name, created_at
        FROM {}
        WHERE drogueria_id = %s AND lower(name) = lower(%s)
        """
    ).format(_proveedores_ident())
    cur.execute(sel, (drogueria_id, name))
    rec = cur.fetchone()
    if rec:
        return dict(rec)
    ins = sql.SQL(
        """
        INSERT INTO {} (drogueria_id, name)
        VALUES (%s, %s)
        RETURNING id, drogueria_id, name, created_at
        """
    ).format(_proveedores_ident())
    cur.execute(ins, (drogueria_id, name))
    created = cur.fetchone()
    if created is None:
        raise RuntimeError("get_or_create_proveedor no devolvió fila")
    return dict(created)


def insert_factura(
    cur,
    *,
    drogueria_id: int,
    proveedor_id: int,
    numero_factura: str,
    fecha_factura: date,
    fecha_vencimiento: date,
    valor: Decimal,
    estado: str,
) -> dict[str, Any]:
    stmt = sql.SQL(
        """
        INSERT INTO {} (
            drogueria_id, proveedor_id, numero_factura,
            fecha_factura, fecha_vencimiento, valor, estado
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING
            id, drogueria_id, proveedor_id, numero_factura,
            fecha_factura, fecha_vencimiento, valor, estado,
            created_at, updated_at
        """
    ).format(_facturas_ident())
    cur.execute(
        stmt,
        (
            drogueria_id,
            proveedor_id,
            numero_factura,
            fecha_factura,
            fecha_vencimiento,
            valor,
            estado,
        ),
    )
    rec = cur.fetchone()
    if rec is None:
        raise RuntimeError("insert_factura no devolvió fila")
    return dict(rec)


def list_facturas(
    settings: Settings,
    *,
    drogueria_id: int,
    proveedor_id: int | None = None,
    estado: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    p = _proveedores_ident()
    f = _facturas_ident()
    conds: list[sql.SQL] = [sql.SQL("f.drogueria_id = %s")]
    params: list[Any] = [drogueria_id]
    if proveedor_id is not None:
        conds.append(sql.SQL("f.proveedor_id = %s"))
        params.append(proveedor_id)
    if date_from is not None:
        conds.append(sql.SQL("f.fecha_factura >= %s"))
        params.append(date_from)
    if date_to is not None:
        conds.append(sql.SQL("f.fecha_factura <= %s"))
        params.append(date_to)
    where = sql.SQL(" AND ").join(conds)
    stmt = sql.SQL(
        """
        SELECT
            f.id, f.drogueria_id, f.proveedor_id, p.name AS proveedor,
            f.numero_factura, f.fecha_factura, f.fecha_vencimiento,
            f.valor, f.estado, f.created_at, f.updated_at
        FROM {} f
        JOIN {} p ON p.id = f.proveedor_id
        WHERE {}
        ORDER BY f.fecha_vencimiento ASC, f.id ASC
        """
    ).format(f, p, where)
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, params)
            return [dict(r) for r in cur.fetchall()]


def get_factura(settings: Settings, factura_id: int) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT
            f.id, f.drogueria_id, f.proveedor_id, p.name AS proveedor,
            f.numero_factura, f.fecha_factura, f.fecha_vencimiento,
            f.valor, f.estado, f.created_at, f.updated_at
        FROM {} f
        JOIN {} p ON p.id = f.proveedor_id
        WHERE f.id = %s
        """
    ).format(_facturas_ident(), _proveedores_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (factura_id,))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def update_factura_estado(
    settings: Settings, factura_id: int, estado: str
) -> dict[str, Any] | None:
    url = _require_url(settings)
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            upd = sql.SQL(
                """
                UPDATE {}
                SET estado = %s
                WHERE id = %s
                RETURNING id
                """
            ).format(_facturas_ident())
            cur.execute(upd, (estado, factura_id))
            rec = cur.fetchone()
            if rec is None:
                return None
        conn.commit()
    return get_factura(settings, factura_id)
