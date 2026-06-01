"""
core/accumulator.py — Motor de combinadas inteligentes con IA.

Genera las mejores combinadas (2-4 selecciones) usando las
probabilidades out-of-sample del FootballModel.
"""

from __future__ import annotations

from itertools import combinations
from typing import Dict, List, Optional

# re-export for convenience
__all__ = ["build_smart_accumulators", "build_recommended_combo"]

import numpy as np
import pandas as pd


def build_recommended_combo(
    df: pd.DataFrame,
    target_min_odds: float = 1.45,
    target_max_odds: float = 2.10,
) -> Optional[Dict]:
    """
    Genera la apuesta combinada recomendada con cuota total entre 1.45 y 2.10.

    Estrategia de triple filtro:
    1. Ensemble ML+DC: model_prob >= 0.68
    2. Edge vs consenso multi-casa positivo (cuando disponible)
    3. risk_light VERDE o AMARILLO

    Devuelve la mejor 2-leg combo o None si no hay candidatos.
    """
    if df.empty:
        return None

    # Filtrar candidatos de alta confianza
    candidates = df[
        (df["no_bet"] == "NO")
        & df["odds"].notna()
        & df["model_prob"].notna()
        & (df["model_prob"].astype(float) >= 0.65)
        & (df["odds"].astype(float) <= 1.65)
        & (df["risk_light"] != "ROJO")
    ].copy()

    if len(candidates) < 2:
        return None

    # Score de calidad: prioriza consensus_edge si existe, si no usa edge
    def _score(row) -> float:
        base = float(row.get("reliability_score", 50)) * 0.5
        base += float(row.get("edge", 0) or 0) * 150
        # Bonus por consenso multi-casa
        ce = row.get("consensus_edge")
        if ce is not None and pd.notna(ce):
            base += float(ce) * 200
        # Bonus por acuerdo ML y DC
        ph_ml = row.get("p_home_ml") or row.get("model_prob", 0)
        ph_dc = row.get("p_home_dc")
        if ph_dc is not None and pd.notna(ph_dc):
            # Si ML y DC coinciden (diferencia < 0.08), bonus de confianza
            diff = abs(float(ph_ml) - float(ph_dc))
            if diff < 0.08:
                base += 15
        return base

    candidates["_score"] = candidates.apply(_score, axis=1)
    candidates = candidates.sort_values("_score", ascending=False)

    best_combo: Optional[Dict] = None
    best_score = -999.0

    for (i1, r1), (i2, r2) in combinations(candidates.iterrows(), 2):
        # Evitar mismo partido
        if (r1.get("home_team") == r2.get("home_team") and
                r1.get("away_team") == r2.get("away_team")):
            continue

        combined_odds = float(r1["odds"]) * float(r2["odds"])
        if not (target_min_odds <= combined_odds <= target_max_odds):
            continue

        combined_prob = float(r1["model_prob"]) * float(r2["model_prob"])
        combined_ev   = combined_prob * combined_odds - 1.0
        combo_score   = float(r1["_score"]) + float(r2["_score"]) + combined_ev * 100

        if combo_score > best_score:
            best_score = combo_score
            best_combo = {
                "n_legs":        2,
                "combined_odds": round(combined_odds, 2),
                "combined_prob": round(combined_prob, 4),
                "ev":            round(combined_ev, 4),
                "score":         round(combo_score, 2),
                "legs":          [r1, r2],
                "method":        "ML+DC ensemble + consenso multi-casa",
            }

    return best_combo


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
