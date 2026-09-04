"""Access to employees and shift_assignments."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.config import Settings

EMPLOYEES_TABLE = "employees"
ASSIGNMENTS_TABLE = "shift_assignments"


def _require_url(settings: Settings) -> str:
    url = (settings.database_url or "").strip()
    if not url:
        raise ValueError("missing_database_url")
    return url


def require_url(settings: Settings) -> str:
    return _require_url(settings)


def _employees_ident() -> sql.Identifier:
    return sql.Identifier(EMPLOYEES_TABLE)


def _assignments_ident() -> sql.Identifier:
    return sql.Identifier(ASSIGNMENTS_TABLE)


def list_employees(settings: Settings, *, q: str | None = None) -> list[dict[str, Any]]:
    url = _require_url(settings)
    needle = (q or "").strip()
    if needle:
        stmt = sql.SQL(
            "SELECT id, name, created_at FROM {} WHERE name ILIKE %s ORDER BY name ASC"
        ).format(_employees_ident())
        params: tuple[Any, ...] = (f"%{needle}%",)
    else:
        stmt = sql.SQL(
            "SELECT id, name, created_at FROM {} ORDER BY name ASC"
        ).format(_employees_ident())
        params = ()
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, params)
            return [dict(r) for r in cur.fetchall()]


def get_employee(settings: Settings, employee_id: int) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL("SELECT id, name, created_at FROM {} WHERE id = %s").format(
        _employees_ident()
    )
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (employee_id,))
            rec = cur.fetchone()
            return dict(rec) if rec else None


def insert_employee(settings: Settings, name: str) -> dict[str, Any]:
    url = _require_url(settings)
    stmt = sql.SQL(
        "INSERT INTO {} (name) VALUES (%s) RETURNING id, name, created_at"
    ).format(_employees_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (name,))
            rec = cur.fetchone()
        conn.commit()
    if rec is None:
        raise RuntimeError("insert_employee returned no row")
    return dict(rec)


def update_employee_name(
    settings: Settings, employee_id: int, name: str
) -> dict[str, Any] | None:
    url = _require_url(settings)
    stmt = sql.SQL(
        "UPDATE {} SET name = %s WHERE id = %s RETURNING id, name, created_at"
    ).format(_employees_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (name, employee_id))
            rec = cur.fetchone()
        conn.commit()
    return dict(rec) if rec else None


def list_assignments(
    settings: Settings,
    *,
    drogueria_id: int,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        SELECT
            a.id, a.drogueria_id, a.work_date, a.shift_no,
            a.employee_id, e.name AS employee
        FROM {} a
        JOIN {} e ON e.id = a.employee_id
        WHERE a.drogueria_id = %s AND a.work_date >= %s AND a.work_date <= %s
        ORDER BY a.work_date ASC, a.shift_no ASC
        """
    ).format(_assignments_ident(), _employees_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, date_from, date_to))
            return [dict(r) for r in cur.fetchall()]


def list_assignments_with_sales(
    settings: Settings,
    *,
    drogueria_id: int,
    date_from: date,
    date_to: date,
) -> list[dict[str, Any]]:
    url = _require_url(settings)
    sales = sql.Identifier("shift_sales")
    stmt = sql.SQL(
        """
        SELECT
            a.employee_id, e.name AS employee,
            a.work_date, a.shift_no, s.amount
        FROM {} a
        JOIN {} e ON e.id = a.employee_id
        LEFT JOIN {} s
          ON s.drogueria_id = a.drogueria_id
         AND s.sale_date = a.work_date
         AND s.shift_no = a.shift_no
        WHERE a.drogueria_id = %s AND a.work_date >= %s AND a.work_date <= %s
        ORDER BY a.work_date ASC, a.shift_no ASC
        """
    ).format(_assignments_ident(), _employees_ident(), sales)
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, date_from, date_to))
            return [dict(r) for r in cur.fetchall()]


def upsert_assignment(
    settings: Settings,
    *,
    drogueria_id: int,
    work_date: date,
    shift_no: int,
    employee_id: int,
) -> dict[str, Any]:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        INSERT INTO {} (drogueria_id, work_date, shift_no, employee_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (drogueria_id, work_date, shift_no)
        DO UPDATE SET employee_id = EXCLUDED.employee_id
        RETURNING id, drogueria_id, work_date, shift_no, employee_id
        """
    ).format(_assignments_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, work_date, shift_no, employee_id))
            rec = cur.fetchone()
        conn.commit()
    if rec is None:
        raise RuntimeError("upsert_assignment returned no row")
    return dict(rec)


def delete_assignment(
    settings: Settings,
    *,
    drogueria_id: int,
    work_date: date,
    shift_no: int,
) -> bool:
    url = _require_url(settings)
    stmt = sql.SQL(
        """
        DELETE FROM {}
        WHERE drogueria_id = %s AND work_date = %s AND shift_no = %s
        RETURNING id
        """
    ).format(_assignments_ident())
    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(stmt, (drogueria_id, work_date, shift_no))
            rec = cur.fetchone()
        conn.commit()
    return rec is not None
