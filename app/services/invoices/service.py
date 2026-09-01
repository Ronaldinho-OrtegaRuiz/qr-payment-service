"""Facturas: lote, proveedor por id o nombre, estado vencida al leer."""

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
STORED_STATES = frozenset({"pendiente", "pagada"})
VISIBLE_STATES = frozenset({"pendiente", "pagada", "vencida"})


class InvoiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_money(raw: Any) -> Decimal:
    """Acepta 150000.99 o 150000,99 (coma decimal)."""
    if isinstance(raw, Decimal):
        val = raw
    elif isinstance(raw, int):
        val = Decimal(raw)
    elif isinstance(raw, float):
        val = Decimal(str(raw))
    else:
        s = str(raw).strip().replace(" ", "")
        if not s:
            raise InvoiceError("invalid_amount", "valor vacío")
        if s.count(",") == 1 and "." not in s:
            s = s.replace(",", ".")
        try:
            val = Decimal(s)
        except InvalidOperation as e:
            raise InvoiceError("invalid_amount", "valor inválido") from e
    if val < 0:
        raise InvoiceError("invalid_amount", "El valor no puede ser negativo")
    return val.quantize(Decimal("0.01"))


def resolve_estado(stored: str, fecha_vencimiento: date, today: date) -> str:
    if stored == "pagada":
        return "pagada"
    if fecha_vencimiento <= today:
        return "vencida"
    return "pendiente"


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"fecha inesperada: {type(value)!r}")


def _money_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _today() -> date:
    return datetime.now(get_payments_timezone()).date()


def _dto(row: dict[str, Any], today: date) -> dict[str, Any]:
    stored = str(row["estado"])
    venc = _as_date(row["fecha_vencimiento"])
    valor = row["valor"]
    if not isinstance(valor, Decimal):
        valor = Decimal(str(valor))
    return {
        "id": int(row["id"]),
        "drogueria_id": int(row["drogueria_id"]),
        "proveedor_id": int(row["proveedor_id"]),
        "proveedor": row["proveedor"],
        "numero_factura": row["numero_factura"],
        "fecha_factura": _as_date(row["fecha_factura"]),
        "fecha_vencimiento": venc,
        "valor": _money_str(valor),
        "estado": resolve_estado(stored, venc, today),
    }


def _require_drogueria(settings: Settings, drogueria_id: int) -> None:
    if get_drogueria(settings, drogueria_id) is None:
        raise InvoiceError("drogueria_not_found", "Droguería no encontrada")


def list_proveedores_dto(
    settings: Settings, drogueria_id: int
) -> list[dict[str, Any]]:
    _require_drogueria(settings, drogueria_id)
    rows = repo.list_proveedores(settings, drogueria_id)
    return [
        {"id": int(r["id"]), "drogueria_id": int(r["drogueria_id"]), "name": r["name"]}
        for r in rows
    ]


def create_facturas_batch(
    settings: Settings,
    *,
    drogueria_id: int,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        raise InvoiceError("empty_batch", "Manda al menos una factura")
    if len(items) > MAX_BATCH:
        raise InvoiceError("batch_too_long", f"Máximo {MAX_BATCH} facturas por lote")

    _require_drogueria(settings, drogueria_id)
    today = _today()
    url = repo._require_url(settings)
    created: list[dict[str, Any]] = []

    with psycopg.connect(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            for i, item in enumerate(items):
                try:
                    created.append(
                        _insert_one(cur, drogueria_id=drogueria_id, item=item, today=today)
                    )
                except InvoiceError as e:
                    e.message = f"Ítem {i + 1}: {e.message}"
                    raise
                except pg_errors.UniqueViolation as e:
                    raise InvoiceError(
                        "duplicate_factura",
                        f"Ítem {i + 1}: ya existe esa factura para el proveedor",
                    ) from e
                except pg_errors.CheckViolation as e:
                    raise InvoiceError(
                        "invalid_factura",
                        f"Ítem {i + 1}: fechas o valor inválidos",
                    ) from e
        conn.commit()
    return created


def _insert_one(
    cur, *, drogueria_id: int, item: dict[str, Any], today: date
) -> dict[str, Any]:
    proveedor_id = item.get("proveedor_id")
    name = (item.get("proveedor") or "").strip()
    if proveedor_id is not None:
        cur.execute(
            """
            SELECT id, drogueria_id, name
            FROM proveedores
            WHERE id = %s AND drogueria_id = %s
            """,
            (int(proveedor_id), drogueria_id),
        )
        prov = cur.fetchone()
        if prov is None:
            raise InvoiceError("proveedor_not_found", "Proveedor no encontrado")
        pid = int(prov["id"])
        pname = prov["name"]
    elif name:
        prov = repo.get_or_create_proveedor(cur, drogueria_id=drogueria_id, name=name)
        pid = int(prov["id"])
        pname = prov["name"]
    else:
        raise InvoiceError(
            "missing_proveedor",
            "Manda proveedor_id o proveedor (nombre)",
        )

    numero = str(item.get("numero_factura") or "").strip()
    if not numero:
        raise InvoiceError("invalid_numero", "numero_factura vacío")

    fecha_factura = item["fecha_factura"]
    fecha_vencimiento = item["fecha_vencimiento"]
    if fecha_vencimiento < fecha_factura:
        raise InvoiceError(
            "invalid_fechas",
            "fecha_vencimiento no puede ser anterior a fecha_factura",
        )

    estado = str(item.get("estado") or "pendiente").strip().lower()
    if estado == "vencida":
        estado = "pendiente"
    if estado not in STORED_STATES:
        raise InvoiceError("invalid_estado", "estado debe ser pendiente o pagada")

    valor = parse_money(item.get("valor"))
    row = repo.insert_factura(
        cur,
        drogueria_id=drogueria_id,
        proveedor_id=pid,
        numero_factura=numero,
        fecha_factura=fecha_factura,
        fecha_vencimiento=fecha_vencimiento,
        valor=valor,
        estado=estado,
    )
    row["proveedor"] = pname
    return _dto(row, today)


def list_facturas_dto(
    settings: Settings,
    *,
    drogueria_id: int,
    proveedor_id: int | None = None,
    estado: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    _require_drogueria(settings, drogueria_id)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvoiceError("invalid_range", "date_from no puede ser posterior a date_to")
    if estado is not None and estado not in VISIBLE_STATES:
        raise InvoiceError("invalid_estado", "estado debe ser pendiente, pagada o vencida")

    today = _today()
    rows = repo.list_facturas(
        settings,
        drogueria_id=drogueria_id,
        proveedor_id=proveedor_id,
        date_from=date_from,
        date_to=date_to,
    )
    out = [_dto(r, today) for r in rows]
    if estado is not None:
        out = [x for x in out if x["estado"] == estado]
    return out


def get_factura_dto(settings: Settings, factura_id: int) -> dict[str, Any]:
    row = repo.get_factura(settings, factura_id)
    if row is None:
        raise InvoiceError("factura_not_found", "Factura no encontrada")
    return _dto(row, _today())


def set_factura_estado(
    settings: Settings, factura_id: int, estado: str
) -> dict[str, Any]:
    estado = estado.strip().lower()
    if estado == "vencida":
        raise InvoiceError(
            "invalid_estado",
            "vencida se asigna sola al vencer; marca pagada o pendiente",
        )
    if estado not in STORED_STATES:
        raise InvoiceError("invalid_estado", "estado debe ser pendiente o pagada")
    row = repo.update_factura_estado(settings, factura_id, estado)
    if row is None:
        raise InvoiceError("factura_not_found", "Factura no encontrada")
    return _dto(row, _today())
