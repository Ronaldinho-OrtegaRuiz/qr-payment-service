"""Scraping de las 6 páginas (Chromium). Sin APIs HTTP."""

from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

from playwright.sync_api import Page, TimeoutError as PWTimeout

from app.config import get_settings
from app.services.competitors.models import CompetitorProduct, SiteSlice
from app.services.competitors.play import click_first, gather_all, with_page
from app.services.competitors.query import name_matches_query

SITE_ORDER: tuple[tuple[str, str], ...] = (
    ("la_economia", "La Economía"),
    ("la_rebaja", "La Rebaja"),
    ("tu_drogueria", "Tu Droguería Virtual"),
    ("cruz_verde", "Cruz Verde"),
    ("farmatodo", "Farmatodo"),
    ("farmanorte", "Farmanorte"),
)

_JS_CARDS = """
(limit) => {
  const skip = /ver productos|av[ií]same|cargar m[aá]s|limpiar|filtro|iniciar sesi[oó]n|t[eé]rminos|pol[ií]tica|categor[ií]a|home|sitemap|agregar|precio por/i;
  const hint = /mg|ml|tableta|c[aá]psul|jarabe|gotas|caja|crema|gel|acetamin|dolex|dolofen|forte/i;
  const seen = new Set();
  const out = [];
  const pickWrap = (el) => {
    let wrap = el.closest('article,li,[class*="card"],[class*="product"],[class*="Product"],[class*="galleryItem"],[class*="shelf"],[class*="summary"]');
    if (wrap && /\\$/.test(wrap.innerText || '')) return wrap;
    wrap = el;
    for (let i = 0; i < 6 && wrap && wrap.parentElement; i++) {
      wrap = wrap.parentElement;
      if (/\\$/.test(wrap.innerText || '')) return wrap;
    }
    return el.parentElement;
  };
  const anchors = Array.from(document.querySelectorAll('a'));
  for (const a of anchors) {
    let name = (a.innerText || '').replace(/\\s+/g, ' ').trim();
    name = name.replace(/\\s*Agregar\\s*$/i, '').trim();
    if (name.length < 8 || name.length > 140 || skip.test(name) || !hint.test(name)) continue;
    if (/^(acetaminofen|acetaminofén)(\\s+codeina|\\s+gotas)?$/i.test(name)) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const wrap = pickWrap(a);
    const txt = ((wrap && wrap.innerText) || name).replace(/\\s+/g, ' ');
    const img = wrap && wrap.querySelector('img');
    let lab = null;
    if (wrap) {
      const bits = Array.from(wrap.querySelectorAll('span,p,div,small'))
        .map(el => (el.innerText || '').replace(/\\s+/g, ' ').trim())
        .filter(t => t && t.length >= 2 && t.length <= 28 && t !== name && !/[\\$0-9]/.test(t) && !skip.test(t));
      lab = bits[0] || null;
    }
    out.push({
      name,
      lab,
      price: txt,
      url: a.href || null,
      image: (img && (img.src || img.getAttribute('src'))) || null,
    });
    if (limit > 0 && out.length >= limit) break;
  }
  return out;
}
"""

_JS_CRUZ_VERDE = """
(limit) => {
  const cards = Array.from(document.querySelectorAll('ml-card-product'));
  const out = [];
  const seen = new Set();
  for (const card of cards) {
    const named = card.querySelector('a[id]');
    const img = Array.from(card.querySelectorAll('img')).find(i =>
      i.alt && i.src && !/ribbon|club|fail|placeholder/i.test(i.src + i.alt)
    );
    let name = ((named && named.id) || (img && img.alt) || '').replace(/\\s+/g, ' ').trim();
    if (!name) {
      const lines = (card.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
      name = lines.find(t => t.length >= 8 && !/^\\$/.test(t) && !/agregar|despacho|retiro|pum|f[oó]rmula/i.test(t)) || '';
    }
    if (name.length < 6) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const labEl = card.querySelector('p.italic, .uppercase.text-12, p.uppercase');
    let lab = labEl ? (labEl.innerText || '').replace(/\\s+/g, ' ').trim() : '';
    if (!lab) {
      const first = (card.innerText || '').split('\\n').map(s => s.trim()).find(Boolean) || '';
      if (/^[A-ZÁÉÍÓÚÑ0-9 .,&/-]{4,70}$/.test(first) && first.toLowerCase() !== name.toLowerCase()) {
        lab = first;
      }
    }
    const priceEl = card.querySelector('.text-prices');
    const skuM = img && img.src ? img.src.match(/\\/(\\d{4,})[-_]/) : null;
    const pum = (card.innerText || '').match(/PUM:\\s*[^\\n]+/i);
    out.push({
      name,
      lab: lab || null,
      price: (priceEl && priceEl.innerText) || card.innerText || '',
      presentation: pum ? pum[0].trim() : null,
      url: skuM ? ('https://www.cruzverde.com.co/' + skuM[1] + '.html') : null,
      image: img ? img.src : null,
    });
    if (limit > 0 && out.length >= limit) break;
  }
  return out;
}
"""

_JS_VTEX_SUMMARY = """
(limit) => {
  const cards = Array.from(document.querySelectorAll(
    '.vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container'
  ));
  const out = [];
  const seen = new Set();
  for (const card of cards) {
    const nameEl = card.querySelector(
      '.vtex-product-summary-2-x-productNameContainer, [class*="productNameContainer"], h3'
    );
    let name = ((nameEl && nameEl.innerText) || '').replace(/\\s+/g, ' ').trim();
    if (!name || /^(generica|genérica)$/i.test(name)) {
      const link = card.querySelector('a[href*="/p"]');
      name = ((link && link.innerText) || '').replace(/\\s+/g, ' ').trim();
    }
    name = name.replace(/\\s*Agregar\\s*$/i, '').trim();
    if (name.length < 6 || /^(generica|genérica)$/i.test(name)) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const a = card.querySelector('a[href*="/p"], a[href]');
    const img = Array.from(card.querySelectorAll('img')).find(i =>
      i.src && !/svg|flag|placeholder|icon|ribbon/i.test(i.src + (i.alt || ''))
    );
    const labEl = card.querySelector('.vtex-product-summary-2-x-productBrand, [class*="productBrand"]');
    const txt = card.innerText || '';
    const presM = txt.match(/Presentaci[oó]n:\\s*([^\\n]+)/i)
      || txt.match(/((?:Gramo|Gramos|Tableta|C[aá]psula|Unidad)\\s*a\\s*\\$?\\s*[\\d.]+)/i);
    out.push({
      name,
      lab: labEl ? (labEl.innerText || '').trim() : null,
      price: txt,
      presentation: presM ? (presM[1] || presM[0]).trim() : null,
      url: a ? a.href : null,
      image: img ? (img.src || null) : null,
    });
    if (limit > 0 && out.length >= limit) break;
  }
  return out;
}
"""

_JS_FARMATODO = """
(limit) => {
  const skipImg = /svg|filtro|heart|icon|flag|moto|prime|placeholder/i;
  const out = [];
  const seen = new Set();
  const links = Array.from(document.querySelectorAll('a[href*="/producto/"]'));
  for (const a of links) {
    let name = (a.innerText || '').replace(/\\s+/g, ' ').trim();
    let wrap = a.closest('article,li,[class*="card"],[class*="product"]') || a.parentElement;
    for (let i = 0; i < 8 && wrap && wrap.parentElement; i++) {
      if (/\\$/.test(wrap.innerText || '')) break;
      wrap = wrap.parentElement;
    }
    const want = name.slice(0, 18).toLowerCase();
    const img = Array.from(document.querySelectorAll('img')).find(i =>
      i.src && i.alt && want && i.alt.toLowerCase().includes(want)
      && !skipImg.test(i.src + i.alt)
    ) || Array.from((wrap || document).querySelectorAll('img')).find(i =>
      i.src && /product-images\\.farmatodo|googleusercontent/i.test(i.src)
    );
    if (!name || name.length < 8) name = (img && img.alt) || '';
    name = name.replace(/\\s+/g, ' ').trim();
    if (name.length < 8 || name.length > 180) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const txt = ((wrap && wrap.innerText) || name).replace(/\\s+/g, ' ');
    const presM = txt.match(/((?:Gramos?|Tableta|C[aá]psula)\\s*a\\s*\\$?\\s*[\\d.]+)/i);
    out.push({
      name,
      lab: null,
      price: txt,
      presentation: presM ? presM[1].trim() : null,
      url: a.href || null,
      image: img ? img.src : null,
    });
    if (limit > 0 && out.length >= limit) break;
  }
  return out;
}
"""

_JS_ECONOMIA = """
(limit) => {
  const cards = Array.from(document.querySelectorAll('.card-product-vertical'));
  const out = [];
  const seen = new Set();
  for (const card of cards) {
    const img = card.querySelector('img.prod__figure__img, img[alt]');
    const nameEl = card.querySelector('h3.prod__name, [data-testid="card-name"]');
    let name = ((img && img.alt) || (nameEl && nameEl.innerText) || '').replace(/\\s+/g, ' ').trim();
    if (name.length < 6) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    const priceEl = card.querySelector('.base__price, [data-testid="card-base-price"]');
    const pumEl = card.querySelector('.prod__pum, [class*="CardPum"]');
    const a = card.querySelector('a.containerCard, a[href*="/p/"]');
    out.push({
      name,
      lab: null,
      price: (priceEl && priceEl.innerText) || card.innerText || '',
      presentation: pumEl ? (pumEl.innerText || '').trim() : null,
      url: a ? a.href : null,
      image: img ? img.src : null,
    });
    if (limit > 0 && out.length >= limit) break;
  }
  return out;
}
"""


def _vtex_url(host: str, query: str, page: int = 1) -> str:
    q = quote(query, safe="")
    url = f"{host.rstrip('/')}/{q}?_q={q}&map=ft"
    if page > 1:
        url += f"&page={page}"
    return url


def _collect_vtex(page: Page, host: str, query: str, limit: int) -> list[CompetitorProduct]:
    collected: list[CompetitorProduct] = []
    seen: set[str] = set()
    for n in range(1, 41):
        page.goto(_vtex_url(host, query, n), wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                ".vtex-search-result-3-x-galleryItem, .vtex-product-summary-2-x-container",
                timeout=10000,
            )
        except PWTimeout:
            if n == 1:
                page.wait_for_timeout(3000)
            else:
                break
        page.wait_for_timeout(1200)
        batch = gather_all(
            page,
            [_JS_VTEX_SUMMARY, _JS_CARDS],
            limit=0,
            more=['button:has-text("Mostrar más")', 'button:has-text("Mostrar Más")'],
        )
        added = 0
        for prod in batch:
            key = prod.name.lower()
            if key in seen:
                continue
            seen.add(key)
            collected.append(prod)
            added += 1
        if added == 0:
            break
        if limit > 0 and len(collected) >= limit:
            return collected[:limit]
    return collected


def _slice(site: str, label: str, products: list[CompetitorProduct], note: str | None = None) -> SiteSlice:
    return SiteSlice(site=site, label=label, ok=True, products=products, note=note)


def _fail(site: str, label: str, error: str, note: str | None = None) -> SiteSlice:
    return SiteSlice(site=site, label=label, ok=False, error=error, note=note)


def _run(site: str, label: str, fn, query: str, note: str | None = None) -> SiteSlice:
    try:
        products = with_page(fn)
    except Exception as e:  # noqa: BLE001
        return _fail(site, label, str(e)[:240], note)
    products = [p for p in products if name_matches_query(p.name, query)]
    if not products:
        return _fail(site, label, "la página no pintó cards con ese nombre", note)
    return _slice(site, label, products, note=note)


def search_la_economia(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        page.goto(
            f"https://www.droguerialaeconomia.com/search?name={quote_plus(query)}",
            wait_until="domcontentloaded",
        )
        try:
            page.wait_for_selector(".card-product-vertical", timeout=12000)
        except PWTimeout:
            page.wait_for_timeout(3500)
        return gather_all(page, [_JS_ECONOMIA, _JS_CARDS], limit=limit)

    return _run("la_economia", "La Economía", _go, query)


def search_la_rebaja(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        return _collect_vtex(page, "https://www.larebajavirtual.com", query, limit)

    return _run("la_rebaja", "La Rebaja", _go, query)


def search_tu_drogueria(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        return _collect_vtex(page, "https://www.tudrogueriavirtual.com", query, limit)

    return _run("tu_drogueria", "Tu Droguería Virtual", _go, query)


def _cruz_verde_city(page: Page) -> None:
    city = get_settings().competitor_city
    try:
        click_first(
            page,
            [
                'a:has-text("Bogotá")',
                'span:has-text("Bogotá")',
                'div.cursor-pointer:has-text("Bogotá")',
            ],
            timeout=2500,
        )
        page.wait_for_timeout(800)
        box = page.get_by_placeholder(re.compile("ciudad|localidad", re.I))
        if box.count():
            box.first.fill(city)
            page.wait_for_timeout(800)
            opt = page.get_by_text(city, exact=False)
            if opt.count() > 1:
                opt.nth(1).click()
            elif opt.count():
                opt.first.click()
            click_first(page, ['button:has-text("Aceptar")', 'button:has-text("Confirmar")'])
            page.wait_for_timeout(1500)
    except Exception:
        pass


def search_cruz_verde(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        page.goto(
            f"https://www.cruzverde.com.co/search?query={quote_plus(query)}",
            wait_until="domcontentloaded",
        )
        try:
            page.wait_for_selector("ml-card-product", timeout=15000)
        except PWTimeout:
            page.wait_for_timeout(4000)
        _cruz_verde_city(page)
        click_first(
            page,
            [
                'button:has-text("48 Productos")',
                'text=48 Productos',
            ],
            timeout=1500,
        )
        try:
            mostrar = page.get_by_text(re.compile(r"12 Productos", re.I))
            if mostrar.count():
                mostrar.first.click()
                page.wait_for_timeout(400)
                click_first(page, ['text=48 Productos'], timeout=1500)
                page.wait_for_timeout(1200)
        except Exception:
            pass
        return gather_all(
            page,
            [_JS_CRUZ_VERDE, _JS_CARDS],
            limit=limit,
            more=['button:has-text("Ver más productos")'],
        )

    return _run(
        "cruz_verde",
        "Cruz Verde",
        _go,
        query,
        note="SPA oficial: /search?query=. Default 12; pedimos 48 y 'Ver más productos'.",
    )


def search_farmatodo(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        page.goto(
            "https://www.farmatodo.com.co/buscar?product="
            f"{quote_plus(query)}&departamento=Todos&filtros=",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(4000)
        click_first(page, ['button:has-text("Cerrar")', '[aria-label="Cerrar"]'], timeout=1500)
        page.wait_for_timeout(2000)
        return gather_all(
            page,
            [_JS_FARMATODO, _JS_CARDS],
            limit=limit,
            more=['button:has-text("Cargar más")'],
        )

    return _run(
        "farmatodo",
        "Farmatodo",
        _go,
        query,
        note="SPA: /buscar?product=. Ciudad en home (sale Bogotá). Hay modal de dirección.",
    )


def _click_text(page: Page, texts: list[str]) -> bool:
    return bool(
        page.evaluate(
            """(texts) => {
              const nodes = Array.from(document.querySelectorAll('span,div,button,li,p,label'));
              for (const want of texts) {
                const el = nodes.find(e => (e.innerText || '').trim() === want && e.offsetParent);
                if (el) { el.click(); return true; }
              }
              return false;
            }""",
            texts,
        )
    )


def _farmanorte_set_location(page: Page) -> None:
    s = get_settings()
    dept = s.competitor_department
    city = s.competitor_city
    address = s.competitor_address
    try:
        page.wait_for_selector("text=¿En qué ciudad te entregamos?", timeout=8000)
    except PWTimeout:
        return
    _click_text(page, ["Selecciona departamento"])
    page.wait_for_timeout(500)
    _click_text(page, [dept, "Bolívar", "Bolivar", "BOLIVAR"])
    page.wait_for_timeout(500)
    _click_text(page, ["Selecciona ciudad"])
    page.wait_for_timeout(400)
    _click_text(page, [city, "Cartagena", "CARTAGENA"])
    page.wait_for_timeout(400)
    click_first(page, ['button:has-text("Siguiente")'])
    page.wait_for_timeout(900)
    try:
        addr = page.locator("input:visible").last
        if addr.count():
            addr.click()
            addr.fill(address)
            page.wait_for_timeout(1000)
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
    except Exception:
        pass
    click_first(page, ['button:has-text("Siguiente")', 'button:has-text("Confirmar")'])
    page.wait_for_timeout(500)
    click_first(page, ['button:has-text("Confirmar")', 'button:has-text("Aceptar")'])
    page.wait_for_timeout(1500)


def search_farmanorte(query: str, limit: int) -> SiteSlice:
    def _go(page: Page) -> list[CompetitorProduct]:
        page.goto("https://www.farmanorte.com.co/", wait_until="domcontentloaded")
        _farmanorte_set_location(page)
        products = _collect_vtex(page, "https://www.farmanorte.com.co", query, limit)
        if products:
            return products
        head = query.split()[0] if query.split() else query
        if head.lower() != query.lower():
            products = _collect_vtex(page, "https://www.farmanorte.com.co", head, limit)
        return products

    return _run(
        "farmanorte",
        "Farmanorte",
        _go,
        query,
        note="Sin ubicación la web dice 0. URL VTEX con %20; si 0, reintenta con la primera palabra.",
    )


SEARCHERS = {
    "la_economia": search_la_economia,
    "la_rebaja": search_la_rebaja,
    "tu_drogueria": search_tu_drogueria,
    "cruz_verde": search_cruz_verde,
    "farmatodo": search_farmatodo,
    "farmanorte": search_farmanorte,
}
