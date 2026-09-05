"""Adaptador VTEX (catálogo + intelligent search)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.services.competitors.http import fetch_json, quote_path
from app.services.competitors.models import CompetitorProduct


def _money(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if n <= 0:
        return None
    return f"{n.quantize(Decimal('0.01'))}"


def _from_vtex_item(prod: dict, limit_images: bool = True) -> CompetitorProduct | None:
    name = (prod.get("productName") or prod.get("productTitle") or "").strip()
    if not name:
        return None
    lab = (prod.get("brand") or "").strip() or None
    url = (prod.get("link") or "").strip() or None
    price: str | None = None
    image: str | None = None
    items = prod.get("items") or []
    if items:
        first = items[0] or {}
        imgs = first.get("images") or []
        if imgs and limit_images:
            image = (imgs[0].get("imageUrl") or "").strip() or None
        for seller in first.get("sellers") or []:
            offer = seller.get("commertialOffer") or {}
            price = _money(offer.get("Price"))
            if price:
                break
    return CompetitorProduct(name=name, lab=lab, price=price, url=url, image=image)


def _from_intelligent(prod: dict) -> CompetitorProduct | None:
    name = (prod.get("productName") or "").strip()
    if not name:
        return None
    lab = (prod.get("brand") or "").strip() or None
    link_text = (prod.get("linkText") or "").strip()
    host = (prod.get("link") or "").strip()
    url = host or None
    price: str | None = None
    image: str | None = None
    items = prod.get("items") or []
    if items:
        first = items[0] or {}
        sellers = first.get("sellers") or []
        if sellers:
            offer = sellers[0].get("commertialOffer") or {}
            price = _money(offer.get("Price"))
        imgs = first.get("images") or []
        if imgs:
            image = (imgs[0].get("imageUrl") or "").strip() or None
    if not price:
        rng = (prod.get("priceRange") or {}).get("sellingPrice") or {}
        price = _money(rng.get("lowPrice") or rng.get("highPrice"))
    if not url and link_text:
        url = None
    return CompetitorProduct(name=name, lab=lab, price=price, url=url, image=image)


def search_vtex(
    base_url: str,
    query: str,
    *,
    limit: int = 20,
) -> list[CompetitorProduct]:
    q = query.strip()
    if not q:
        return []
    base = base_url.rstrip("/")
    intel = (
        f"{base}/api/io/_v/api/intelligent-search/product_search/trade-policy/1"
        f"?query={quote_path(q)}&count={limit}"
    )
    status, data = fetch_json(intel)
    products: list[CompetitorProduct] = []
    if status < 400 and isinstance(data, dict) and isinstance(data.get("products"), list):
        for raw in data["products"][:limit]:
            if not isinstance(raw, dict):
                continue
            item = _from_intelligent(raw)
            if item:
                if not item.url and raw.get("linkText"):
                    item.url = f"{base}/{raw['linkText']}/p"
                elif item.url and item.url.startswith("/"):
                    item.url = f"{base}{item.url}"
                products.append(item)
        if products:
            return products[:limit]

    catalog = (
        f"{base}/api/catalog_system/pub/products/search/{quote_path(q)}"
        f"?_from=0&_to={max(0, limit - 1)}"
    )
    status, data = fetch_json(catalog)
    if status >= 400 or not isinstance(data, list):
        catalog_ft = (
            f"{base}/api/catalog_system/pub/products/search"
            f"?ft={quote_path(q)}&_from=0&_to={max(0, limit - 1)}"
        )
        status, data = fetch_json(catalog_ft)
    if not isinstance(data, list):
        return products
    for raw in data[:limit]:
        if not isinstance(raw, dict):
            continue
        item = _from_vtex_item(raw)
        if item:
            if item.url and item.url.startswith("/"):
                item.url = f"{base}{item.url}"
            products.append(item)
    return products[:limit]
