"""API del buscador de competencia (proceso aparte del de pagos).

Local:
    uvicorn app.competitor_main:app --host 127.0.0.1 --port 8001
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.services.competitors.runner import search_competitors

app = FastAPI(
    title="Buscador precios competencia",
    description="Servicio aparte del de pagos. Scraping con Playwright.",
    version="0.1.0",
)

s = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(s.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "competitors"}


@app.get("/competitors/search")
def competitors_search(
    q: Annotated[str, Query(min_length=2, max_length=80, description="Texto del buscador")],
) -> dict:
    """
    El front manda el texto crudo. Aquí se recorta mg/lab, se piden todos los
    resultados y se descartan nombres que no traigan esas palabras (sin tilde).
    Cada producto: name, lab, price, presentation, url, image.
    """
    settings = get_settings()
    return search_competitors(
        q,
        limit=settings.competitor_limit,
        concurrency=settings.competitor_concurrency,
    )


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
