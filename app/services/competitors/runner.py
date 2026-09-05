"""Corre los 6 sitios en el orden pedido, máximo 2 a la vez."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.competitors.models import SiteSlice
from app.services.competitors.query import LAB_ALIASES, sanitize_site_query
from app.services.competitors.sites import SEARCHERS, SITE_ORDER


def search_competitors(
    raw_q: str,
    *,
    limit: int = 0,
    concurrency: int = 2,
) -> dict:
    site_q = sanitize_site_query(raw_q)
    if not site_q:
        return {
            "q": (raw_q or "").strip(),
            "q_site": "",
            "lab_aliases": LAB_ALIASES,
            "slices": [],
            "error": "query vacía después de quitar mg/lab",
        }

    workers = max(1, min(int(concurrency), 2))
    cap = max(0, int(limit))
    by_site: dict[str, SiteSlice] = {}

    def _one(site: str) -> tuple[str, SiteSlice]:
        fn = SEARCHERS[site]
        try:
            return site, fn(site_q, cap)
        except Exception as e:  # noqa: BLE001 — un sitio no tumba el resto
            label = next(lbl for sid, lbl in SITE_ORDER if sid == site)
            return site, SiteSlice(
                site=site,
                label=label,
                ok=False,
                error=str(e)[:240],
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_one, site) for site, _lbl in SITE_ORDER]
        for fut in as_completed(futs):
            site, slice_ = fut.result()
            by_site[site] = slice_

    slices = [by_site[site].to_dict() for site, _lbl in SITE_ORDER if site in by_site]
    return {
        "q": (raw_q or "").strip(),
        "q_site": site_q,
        "lab_aliases": LAB_ALIASES,
        "slices": slices,
    }
