"""Limpia la query que se manda a las páginas (nombre + crema; sin mg/lab)."""

from __future__ import annotations

import re
import unicodedata

# El lab se filtra después en el front. Aquí no se envía a las páginas.
_LAB_TOKENS = frozenset(
    {
        "ag",
        "a-g",
        "a/g",
        "mk",
        "lafrancol",
        "tecnoquimicas",
        "tecnoquimica",
        "g-far",
        "gfar",
        "g/far",
        "l-s",
        "ls",
    }
)

_KEEP_FORMS = frozenset(
    {
        "crema",
        "gel",
        "jarabe",
        "gotas",
        "unguento",
        "pomada",
        "suspension",
        "solucion",
    }
)

_DOSE_RE = re.compile(
    r"""
    ^(?:
        \d+(?:[.,]\d+)?\s*(?:mg|ml|mcg|mcg|ug|g|gr|kg|ui|iu|%|mg/ml|mg/5ml)
        | \d+\s*/\s*\d+(?:\s*mg)?
        | \d+mg
        | \d+ml
    )$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_SPLIT_RE = re.compile(r"[^\wáéíóúüñÁÉÍÓÚÜÑ/+-]+", re.UNICODE)


def _fold(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").lower()


def sanitize_site_query(raw: str) -> str:
    """
    'acetaminofen 500mg AG' -> 'acetaminofen'
    'crema ketoconazol 2%'  -> 'crema ketoconazol'
    'daflon'                -> 'daflon'
    """
    text = (raw or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for token in _SPLIT_RE.split(text):
        tok = token.strip(".,;:()[]")
        if not tok:
            continue
        folded = _fold(tok).replace("ü", "u")
        if folded in _LAB_TOKENS:
            continue
        if _DOSE_RE.match(folded.replace(" ", "")) or _DOSE_RE.match(folded):
            continue
        if folded in _KEEP_FORMS or not folded.isdigit():
            parts.append(tok)
    return " ".join(parts).strip()


LAB_ALIASES: dict[str, list[str]] = {
    "ag": ["ag", "a-g", "a/g", "lafrancol", "laboratorio franco colombiano"],
    "mk": ["mk", "tecnoquimicas", "tecnoquímicas", "tecnoquimica"],
}


def name_matches_query(name: str, query: str) -> bool:
    """Todas las palabras de la query deben estar en el nombre (sin tilde/mayúscula)."""
    folded_name = _fold(name or "")
    tokens = [_fold(tok) for tok in _SPLIT_RE.split(query or "") if tok.strip()]
    if not tokens or not folded_name:
        return False
    return all(tok in folded_name for tok in tokens)
