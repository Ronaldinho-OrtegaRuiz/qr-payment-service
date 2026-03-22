"""Asigna drogueria_id según el nombre de comercio parseado del correo."""

from __future__ import annotations

from app.config import Settings


def resolve_drogueria_id_for_entry(settings: Settings, entry: dict) -> int:
    """
    Si el texto parseado `drogueria` contiene (case-insensitive) DROGUERIA_SECONDARY_MATCH,
    usa DROGUERIA_SECONDARY_ID; si no, DROGUERIA_ID.
    """
    if not entry.get("parse_ok"):
        return settings.drogueria_id
    name = (entry.get("drogueria") or "").strip()
    if not name:
        return settings.drogueria_id
    sub = settings.drogueria_secondary_match.strip().lower()
    if sub and sub in name.lower():
        return settings.drogueria_secondary_id
    return settings.drogueria_id
