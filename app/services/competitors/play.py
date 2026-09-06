"""Chromium por sitio (lo que ve el usuario, no APIs)."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from playwright.sync_api import Page, TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from app.services.competitors.models import CompetitorProduct

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Sin tope de productos. Solo freno de seguridad si una página cicla el "ver más".
MAX_LOAD_ROUNDS = 50

_PRICE_RE = re.compile(
    r"\$[\s]*([0-9]{1,3}(?:[.\s][0-9]{3})+(?:,[0-9]{2})?|"
    r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{2})?|"
    r"[0-9]{3,}(?:[.,][0-9]{2})?)"
)

_PRESENTATION_RES = (
    re.compile(r"(?i)presentaci[oó]n:\s*([^\n$]{2,70})"),
    re.compile(r"(?i)(1\s*un\s*\([^)]{3,40}\))"),
    re.compile(r"(?i)(pum:\s*[^\n]{2,60})"),
    re.compile(
        r"(?i)((?:gramos?|tabletas?|c[aá]psulas?|unidad(?:es)?|ml|g)\s*a\s*\$?\s*[\d.\s,]+)"
    ),
    re.compile(r"(?i)(precio por unidad\s*\$[\s\d.,]+)"),
)

_BAD_IMAGE = re.compile(
    r"(?i)(?:\.svg(?:\?|$)|placeholder|ribbon|flag-rx|moto\.svg|data:image|blank\.gif)"
)

LOAD_MORE_SELECTORS = [
    'button:has-text("Ver más productos")',
    'button:has-text("Cargar más")',
    'button:has-text("Mostrar más")',
    'button:has-text("Ver más")',
    ".vtex-search-result-3-x-buttonShowMore button",
    ".load-more-btn-wrap button",
]


def _money_from(text: str) -> str | None:
    m = _PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip()
    if "," in raw and "." not in raw:
        raw = raw.replace(",", "")
    else:
        raw = raw.split(",")[0].replace(".", "").replace(" ", "")
    try:
        n = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if n <= 0:
        return None
    return f"{n.quantize(Decimal('0.01'))}"


def money(text: str | None) -> str | None:
    if not text:
        return None
    text = text.replace("\xa0", " ")
    stripped = re.sub(
        r"(?:pum|precio por unidad)[^$]*\$[\s0-9.,]+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _money_from(stripped) or _money_from(text)


def with_page(fn: Callable[[Page], list[CompetitorProduct]], *, timeout_ms: int = 180000):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            locale="es-CO",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            return fn(page)
        finally:
            context.close()
            browser.close()


def abs_url(href: str | None, base: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return base.rstrip("/") + href
    return None


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^\$[\s0-9.,()]+\s*", "", name)
    name = re.sub(r"(?i)\s*(?:ahorro\s*\$[\s0-9.,]+)\s*", " ", name)
    name = re.sub(r"(?i)\s*1\s*un\s*\([^)]+\)\s*", " ", name)
    name = re.sub(r"(?i)\s*agregar(?: a la bolsa)?\s*$", "", name)
    return re.sub(r"\s+", " ", name).strip(" .")


def presentation_of(*parts: str | None) -> str | None:
    blob = " ".join(p for p in parts if p)
    if not blob:
        return None
    blob = blob.replace("\xa0", " ")
    for rx in _PRESENTATION_RES:
        m = rx.search(blob)
        if not m:
            continue
        text = (m.group(1) if m.lastindex else m.group(0)).strip(" :-")
        text = re.sub(r"(?i)\s*\d+\s*mins?.*$", "", text)
        text = re.sub(r"\s+", " ", text).replace("a$", "a $")
        if 2 <= len(text) <= 80:
            return text
    return None


def clean_image(url: object) -> str | None:
    if not url:
        return None
    href = str(url).strip()
    if not href.startswith("http") or _BAD_IMAGE.search(href):
        return None
    return href


def extract_cards(page: Page, script: str, limit: int = 0) -> list[CompetitorProduct]:
    raw = page.evaluate(script, limit)
    out: list[CompetitorProduct] = []
    if not isinstance(raw, list):
        return out
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "")
        raw_price = str(item.get("price") or "")
        raw_pres = str(item.get("presentation") or "").strip() or None
        name = _clean_name(raw_name)
        if len(name) < 6 or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(
            CompetitorProduct(
                name=name,
                lab=(str(item.get("lab") or "").strip() or None),
                price=money(raw_price) or money(raw_name),
                url=item.get("url") or None,
                image=clean_image(item.get("image")),
                presentation=raw_pres or presentation_of(raw_pres, raw_price, raw_name),
            )
        )
        if limit > 0 and len(out) >= limit:
            break
    return out


def click_first(page: Page, selectors: list[str], *, timeout: int = 4000) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=timeout)
                return True
        except PWTimeout:
            continue
        except Exception:
            continue
    return False


def gather_all(
    page: Page,
    scripts: list[str],
    *,
    limit: int = 0,
    more: list[str] | None = None,
    max_more_clicks: int | None = None,
) -> list[CompetitorProduct]:
    """Extrae cards y sigue 'ver más' / scroll hasta que no crezca el listado.

    max_more_clicks:
      None → sin tope extra de clics
      0    → solo la carga inicial (reintenta si aún no pintó cards)
      N    → carga inicial + N clics de 'Mostrar más' / 'Cargar más'
    """
    sels = list(more or []) + LOAD_MORE_SELECTORS
    last = -1
    stable = 0
    clicks_done = 0
    products: list[CompetitorProduct] = []
    best: list[CompetitorProduct] = []
    for _ in range(MAX_LOAD_ROUNDS):
        products = []
        for script in scripts:
            products = extract_cards(page, script, limit)
            if products:
                break
        if products:
            best = products
        if limit > 0 and len(products) >= limit:
            return products
        if len(products) == last:
            stable += 1
            if stable >= 2 and products:
                break
        else:
            stable = 0
        last = len(products)

        if max_more_clicks == 0:
            if products:
                break
            page.wait_for_timeout(1600)
            continue

        if max_more_clicks is not None and clicks_done >= max_more_clicks:
            break

        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        clicked = click_first(page, sels, timeout=1500)
        if clicked:
            clicks_done += 1
            page.wait_for_timeout(1600)
            continue
        # Si ya hay cards y no hay botón, terminamos. Si la SPA aún no pintó,
        # no abortar: esperar y reintentar (si no, La Rebaja queda en 0).
        if products:
            break
        page.wait_for_timeout(1600)
    return products or best
