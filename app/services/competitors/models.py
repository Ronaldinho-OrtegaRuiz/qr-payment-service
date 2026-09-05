"""Modelos del buscador de precios de competencia."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompetitorProduct:
    name: str
    lab: str | None
    price: str | None
    url: str | None
    image: str | None = None
    presentation: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lab": self.lab,
            "price": self.price,
            "presentation": self.presentation,
            "url": self.url,
            "image": self.image,
        }


@dataclass
class SiteSlice:
    site: str
    label: str
    ok: bool
    products: list[CompetitorProduct] = field(default_factory=list)
    error: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "label": self.label,
            "ok": self.ok,
            "error": self.error,
            "note": self.note,
            "count": len(self.products),
            "products": [p.to_dict() for p in self.products],
        }
