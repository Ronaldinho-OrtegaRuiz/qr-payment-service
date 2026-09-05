"""Uso local: python -m app.services.competitors \"acetaminofen 500mg AG\""""

from __future__ import annotations

import json
import sys

from app.services.competitors.runner import search_competitors


def main() -> None:
    q = " ".join(sys.argv[1:]).strip() or "acetaminofen"
    payload = search_competitors(q, concurrency=6)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
