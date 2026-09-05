"""Buscador de precios de competencia (proceso aparte del monitor IMAP)."""

from app.services.competitors.query import sanitize_site_query
from app.services.competitors.runner import iter_competitor_slices, search_competitors

__all__ = ["sanitize_site_query", "search_competitors"]
