"""
core/accumulator.py — Motor de combinadas inteligentes con IA.

Genera las mejores combinadas (2-4 selecciones) usando las
probabilidades out-of-sample del FootballModel.
"""

from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


def build_smart_accumulators(
    df: pd.DataFrame,
    min_legs: int = 2,
    max_legs: int = 4,
    top_candidates: int = 12,
) -> List[Dict]:
    """
    Para cada tamaño (min_legs..max_legs) devuelve la combinada con
    mayor EV esperado, usando las probabilidades del modelo IA.

    Parámetros
    ----------
    df             : DataFrame de resultados del Analyzer (salida de run())
    min_legs       : Número mínimo de selecciones por combinada
    max_legs       : Número máximo de selecciones por combinada
    top_candidates : Cuántos picks pre-filtrar antes de iterar combinaciones

    Retorna
    -------
    Lista de dicts, uno por tamaño de combinada, con:
      n_legs, combined_prob, combined_odds, ev, avg_reliability,
      avg_edge, min_reliability, legs (lista de Series)
    """
    if df.empty:
        return []

    # ── Filtrar solo picks accionables ────────────────────────────────────────
    bets = df[
        (df["no_bet"] == "NO")
        & df["odds"].notna()
        & df["model_prob"].notna()
        & df["edge"].notna()
    ].copy()

    if len(bets) < min_legs:
        return []

    # ── Scoring IA para pre-seleccionar candidatos ────────────────────────────
    bets["_ai_score"] = (
        bets["reliability_score"].fillna(0) * 0.50
        + bets["edge"].fillna(0) * 200
        + bets["ev"].fillna(0) * 100
        + bets["model_prob"].fillna(0) * 20
    )
    bets = bets.sort_values("_ai_score", ascending=False).head(top_candidates)

    accumulators: List[Dict] = []

    for n_legs in range(min_legs, max_legs + 1):
        if len(bets) < n_legs:
            continue

        best: Optional[Dict] = None

        for combo_iter in combinations(bets.iterrows(), n_legs):
            legs = [row for _, row in combo_iter]

            combined_prob = float(np.prod([float(l["model_prob"]) for l in legs]))
            combined_odds = float(np.prod([float(l["odds"]) for l in legs]))
            ev            = combined_prob * combined_odds - 1.0
            avg_rel       = float(np.mean([float(l["reliability_score"]) for l in legs]))
            avg_edge      = float(np.mean([float(l["edge"]) for l in legs]))
            min_rel       = float(min(float(l["reliability_score"]) for l in legs))

            entry: Dict = {
                "n_legs":          n_legs,
                "combined_prob":   round(combined_prob, 4),
                "combined_odds":   round(combined_odds, 2),
                "ev":              round(ev, 4),
                "avg_reliability": round(avg_rel, 1),
                "avg_edge":        round(avg_edge, 4),
                "min_reliability": round(min_rel, 1),
                "legs":            legs,
            }

            if best is None or ev > best["ev"]:
                best = entry

        if best is not None:
            accumulators.append(best)

    return accumulators
