# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/consensus.py — Probabilidad de consenso de mercado (método Pinnacle).

El consenso multi-casa es el mejor estimador disponible de la probabilidad real:
1. Se eliminan los márgenes de cada bookmaker (no-vig normalization)
2. Se promedian las probabilidades resultantes de todos los bookmakers
3. El resultado es más preciso que cualquier bookmaker individual

Referencia: "The wisdom of the crowd beats individuals" - Pinnacle Sports Blog
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# Libros "sharp" (bajo margen, seguidos por profesionales)
# La sabiduría del mercado de Pinnacle es el mejor estimador de probabilidad real.
_SHARP_BOOKS = {
    "pinnacle", "pinnacle_us",
    "betfair_ex_eu", "betfair_ex_uk", "betfair",
    "matchbook", "smarkets",
}


def is_sharp_book(key: str) -> bool:
    """Devuelve True si el bookmaker es considerado 'sharp' (bajo overround)."""
    k = key.lower().replace(" ", "_")
    return any(s in k for s in _SHARP_BOOKS)


def no_vig(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    """
    Elimina el margen del bookmaker por normalización proporcional.
    P_true = P_implied / sum(P_implied)
    """
    if not all(o and o > 1.01 for o in [odds_h, odds_d, odds_a]):
        return 1 / 3, 1 / 3, 1 / 3

    raw = np.array([1 / odds_h, 1 / odds_d, 1 / odds_a])
    norm = raw / raw.sum()
    return float(norm[0]), float(norm[1]), float(norm[2])


def consensus_from_bookmakers(
    bookmakers: list[dict],
    sharp_weight: float = 3.0,
) -> Optional[tuple[float, float, float, int]]:
    """
    Calcula la probabilidad de consenso ponderada desde una lista de bookmakers.

    Los libros sharp (Pinnacle, Betfair Exchange) reciben peso 3× sobre libros
    suaves como B365 o William Hill. Esto replica el "método Pinnacle" de
    estimar la probabilidad real del mercado.

    Cada dict debe tener: bookmaker, odds_h, odds_d, odds_a.
    Devuelve (consensus_h, consensus_d, consensus_a, n_bookmakers) o None.
    """
    ph_list, pd_list, pa_list, w_list = [], [], [], []

    for bk in bookmakers:
        oh = bk.get("odds_h")
        od = bk.get("odds_d")
        oa = bk.get("odds_a")

        if not all(o and o > 1.01 for o in [oh, od, oa]):
            continue

        ph, pd_, pa = no_vig(float(oh), float(od), float(oa))
        w = sharp_weight if is_sharp_book(bk.get("bookmaker", "")) else 1.0
        ph_list.append(ph)
        pd_list.append(pd_)
        pa_list.append(pa)
        w_list.append(w)

    n = len(ph_list)
    if n == 0:
        return None

    w_arr = np.array(w_list, dtype=float)
    w_arr = w_arr / w_arr.sum()

    return (
        round(float(np.dot(w_arr, ph_list)), 4),
        round(float(np.dot(w_arr, pd_list)), 4),
        round(float(np.dot(w_arr, pa_list)), 4),
        n,
    )


def edge_vs_consensus(
    model_prob: float,
    consensus_prob: float,
) -> float:
    """
    Edge real = probabilidad del modelo - probabilidad de consenso de mercado.
    Positivo → el modelo ve más valor del que el mercado ha descontado.
    """
    return round(float(model_prob) - float(consensus_prob), 4)


def pinnacle_from_bookmakers(
    bookmakers: list[dict],
) -> Optional[tuple[float, float, float]]:
    """
    Extrae las probabilidades no-vig de Pinnacle (o libro sharp equivalente).

    Devuelve (p_home, p_draw, p_away) sin margen, o None si no está disponible.

    Por qué importa:
      B365 tiene overround ~7-9%  → su fair_prob subestima la prob. real
      Pinnacle tiene overround ~2-3% → es la mejor referencia del mercado
      El edge vs Pinnacle es mucho más fiable que el edge vs B365.
    """
    for bk in bookmakers:
        if not is_sharp_book(bk.get("bookmaker", "")):
            continue
        oh = bk.get("odds_h")
        od = bk.get("odds_d")
        oa = bk.get("odds_a")
        if not all(o and o > 1.01 for o in [oh, od, oa]):
            continue
        return no_vig(float(oh), float(od), float(oa))
    return None


def bookmakers_from_api_response(match: dict) -> list[dict]:
    """
    Extrae todas las cuotas 1X2 de un partido de The Odds API y las convierte
    a la estructura esperada por consensus_from_bookmakers().
    """
    home = match.get("home_team", "")
    away = match.get("away_team", "")
    result = []

    for bk in match.get("bookmakers", []):
        # Bug fix: usar .get() en lugar de [] para evitar KeyError con respuestas malformadas
        h2h = next(
            (m for m in bk.get("markets", []) if m.get("key") == "h2h"), None
        )
        if not h2h:
            continue

        outs = {
            o.get("name", ""): float(o.get("price", 0) or 0)
            for o in h2h.get("outcomes", [])
            if o.get("name")  # ignorar outcomes sin nombre
        }

        odds_h = outs.get(home)
        odds_d = outs.get("Draw")
        odds_a = outs.get(away)

        if not all(o and o > 1.01 for o in [odds_h, odds_d, odds_a]):
            continue

        result.append({
            "bookmaker": bk.get("key", ""),
            "odds_h":    odds_h,
            "odds_d":    odds_d,
            "odds_a":    odds_a,
        })

    return result
