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
) -> Optional[tuple[float, float, float, int]]:
    """
    Calcula la probabilidad de consenso desde una lista de bookmakers.

    Cada dict debe tener: odds_h, odds_d, odds_a (cuotas 1X2).
    Devuelve (consensus_h, consensus_d, consensus_a, n_bookmakers) o None.
    """
    ph_list, pd_list, pa_list = [], [], []

    for bk in bookmakers:
        oh = bk.get("odds_h")
        od = bk.get("odds_d")
        oa = bk.get("odds_a")

        if not all(o and o > 1.01 for o in [oh, od, oa]):
            continue

        ph, pd_, pa = no_vig(float(oh), float(od), float(oa))
        ph_list.append(ph)
        pd_list.append(pd_)
        pa_list.append(pa)

    n = len(ph_list)
    if n == 0:
        return None

    return (
        round(float(np.mean(ph_list)), 4),
        round(float(np.mean(pd_list)), 4),
        round(float(np.mean(pa_list)), 4),
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


def bookmakers_from_api_response(match: dict) -> list[dict]:
    """
    Extrae todas las cuotas 1X2 de un partido de The Odds API y las convierte
    a la estructura esperada por consensus_from_bookmakers().
    """
    home = match.get("home_team", "")
    away = match.get("away_team", "")
    result = []

    for bk in match.get("bookmakers", []):
        h2h = next((m for m in bk.get("markets", []) if m["key"] == "h2h"), None)
        if not h2h:
            continue

        outs = {o["name"]: float(o.get("price", 0) or 0)
                for o in h2h.get("outcomes", [])}

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
