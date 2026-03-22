"""
Parser para notificaciones de pago vía correo (plantilla Bancolombia).
Ejemplo:
  Bancolombia: DROGUERIA RICKY, recibiste un pago de GABRIEL JESUS MARTINEZ MEDRANO
  por $2,500.00 en tu cuenta *8186 conectado a la llave 0089074729 el 19/03/2026 a las 09:41. ...
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

# Plantilla: comercio después de "Bancolombia:", nombre antes de " por $", monto, fecha/hora al final del bloque.
_PAGO_PATTERN = re.compile(
    r"Bancolombia:\s*(?P<drogueria>[^,]+?)\s*,\s*"
    r"recibiste un pago de\s+(?P<nombre_cliente>.+?)\s+por\s*"
    r"\$\s*(?P<valor>[\d,]+\.\d{2})\b\s+"
    r"en tu cuenta.*?el\s+(?P<fecha>\d{2}/\d{2}/\d{4})\s+a las\s+(?P<hora>\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ParsedBancolombiaPago:
    drogueria: str
    nombre_cliente: str
    valor: str
    fecha: str
    hora: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def parse_bancolombia_pago_text(text: str) -> ParsedBancolombiaPago | None:
    """Extrae campos del cuerpo/asunto si coincide la plantilla. None si no matchea."""
    if not text or not text.strip():
        return None
    normalized = " ".join(text.split())
    m = _PAGO_PATTERN.search(normalized)
    if not m:
        return None
    return ParsedBancolombiaPago(
        drogueria=m.group("drogueria").strip(),
        nombre_cliente=m.group("nombre_cliente").strip(),
        valor=m.group("valor").strip(),
        fecha=m.group("fecha").strip(),
        hora=m.group("hora").strip(),
    )


def parse_bancolombia_pago_to_jsonable(text: str) -> dict[str, Any] | None:
    p = parse_bancolombia_pago_text(text)
    return p.to_dict() if p else None
