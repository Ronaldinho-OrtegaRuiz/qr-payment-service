"""Corre los sitios en el orden pedido. Economía y Rebaja salen primero."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.services.competitors.models import SiteSlice
from app.services.competitors.query import LAB_ALIASES, sanitize_site_query
from app.services.competitors.sites import SEARCHERS, SITE_ORDER

PRIORITY_SITES: tuple[str, ...] = ("la_economia", "la_rebaja")
_SITE_LABEL = {sid: lbl for sid, lbl in SITE_ORDER}


def _selected_sites(wanted: list[str] | None) -> list[str]:
    allowed = [sid for sid, _lbl in SITE_ORDER]
    if not wanted:
        return allowed
    seen: set[str] = set()
    out: list[str] = []
    for raw in wanted:
        sid = (raw or "").strip().lower()
        if sid in allowed and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out or allowed


def _queue_order(sites: list[str]) -> list[str]:
    first = [s for s in PRIORITY_SITES if s in sites]
    rest = [s for s in sites if s not in first]
    return first + rest


def _run_one(site: str, site_q: str, cap: int) -> tuple[str, SiteSlice]:
    fn = SEARCHERS[site]
    try:
        return site, fn(site_q, cap)
    except Exception as e:  # noqa: BLE001 — un sitio no tumba el resto
        return site, SiteSlice(
            site=site,
            label=_SITE_LABEL[site],
            ok=False,
            error=str(e)[:240],
        )


def iter_competitor_slices(
    raw_q: str,
    *,
    limit: int = 0,
    concurrency: int = 6,
    sites: list[str] | None = None,
) -> Iterator[tuple[str, dict]]:
    """
    Yields ('meta', payload) then ('slice', site_dict) as each site finishes.
    Economía y Rebaja se encolan primero.
    """
    site_q = sanitize_site_query(raw_q)
    chosen = _selected_sites(sites)
    meta = {
        "q": (raw_q or "").strip(),
        "q_site": site_q,
        "lab_aliases": LAB_ALIASES,
        "sites": chosen,
        "priority": [s for s in PRIORITY_SITES if s in chosen],
    }
    if not site_q:
        yield "meta", {**meta, "error": "query vacía después de quitar mg/lab"}
        return
    yield "meta", meta

    workers = max(1, min(int(concurrency), 6))
    cap = max(0, int(limit))
    ordered = _queue_order(chosen)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_run_one, site, site_q, cap) for site in ordered]
        for fut in as_completed(futs):
            _site, slice_ = fut.result()
            yield "slice", slice_.to_dict()


def search_competitors(
    raw_q: str,
    *,
    limit: int = 0,
    concurrency: int = 6,
    sites: list[str] | None = None,
) -> dict:
    meta: dict | None = None
    by_site: dict[str, dict] = {}
    for kind, payload in iter_competitor_slices(
        raw_q, limit=limit, concurrency=concurrency, sites=sites
    ):
        if kind == "meta":
            meta = payload
            continue
        by_site[payload["site"]] = payload
    if meta is None:
        meta = {
            "q": (raw_q or "").strip(),
            "q_site": "",
            "lab_aliases": LAB_ALIASES,
            "slices": [],
        }
    chosen = meta.get("sites") or [sid for sid, _lbl in SITE_ORDER]
    slices = [by_site[sid] for sid in chosen if sid in by_site]
    out = {
        "q": meta.get("q", ""),
        "q_site": meta.get("q_site", ""),
        "lab_aliases": meta.get("lab_aliases", LAB_ALIASES),
        "slices": slices,
    }
    if meta.get("error"):
        out["error"] = meta["error"]
    return out
