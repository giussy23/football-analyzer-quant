# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
news_search.py — Noticias frescas vía DuckDuckGo (ddgs) para el enricher de Claude.

Claude tiene fecha de corte de entrenamiento: sin noticias actuales no sabe
quién está lesionado esta semana ni si el partido es decisivo. Este módulo le
da esa información — la única señal que el mercado tarda horas en absorber.

Sin API key, gratis. Caché en memoria por partido (la búsqueda DDG tarda ~1-2s).
Fallo gracioso: si DDG no responde, devuelve [] y el enricher sigue sin noticias.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_CACHE_TTL = 3 * 3600   # 3 h — las noticias de lesiones cambian rápido
_cache:    dict[str, list[str]] = {}
_cache_ts: dict[str, float] = {}


def fetch_match_news(home: str, away: str, max_items: int = 5) -> list[str]:
    """Busca noticias recientes del partido (lesiones, alineaciones, contexto).

    Devuelve una lista de líneas "fecha | titular: resumen" (máx max_items),
    o [] si no hay resultados o DDG no está disponible.
    """
    key = f"{home}|{away}"
    now = time.time()
    if key in _cache and (now - _cache_ts.get(key, 0)) < _CACHE_TTL:
        return _cache[key]

    items: list[str] = []
    try:
        from ddgs import DDGS

        query = f"{home} {away} alineaciones lesionados bajas"
        with DDGS() as ddg:
            try:
                results = ddg.news(
                    query, region="es-es", timelimit="w", max_results=max_items
                ) or []
            except Exception:
                results = []
            if not results:
                # Fallback: búsqueda web normal (sin filtro de fecha)
                results = ddg.text(query, region="es-es", max_results=max_items) or []

        for r in results:
            title = (r.get("title") or "").strip()
            body  = (r.get("body") or "").strip()[:200]
            date  = (r.get("date") or "")[:10]
            if title:
                items.append(f"{date + ' | ' if date else ''}{title}: {body}")
    except Exception as exc:
        logger.debug("news_search [%s vs %s]: %s", home, away, exc)

    _cache[key] = items
    _cache_ts[key] = now
    return items
