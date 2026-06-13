# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/accumulator.py — Motor de combinadas inteligentes con análisis profundo.

Mercados soportados:
  1X2          — Victoria local / Empate / Victoria visitante
  Doble op.    — 1X  (Local o Empate)
                 X2  (Empate o Visitante)
                 12  (Local o Visitante)
  Goles        — OVER 2.5 / UNDER 2.5

Análisis profundo por selección:
  • Ensemble ML + Dixon-Coles (acuerdo entre modelos)
  • Edge vs consenso multi-casa (cuando disponible)
  • Valor de cierre (CLV positivo)
  • Calidad de mercado (overround bajo = mercado líquido)
  • Fiabilidad individual del pick

Mejoras v15.1:
  • Kelly Criterion fraccionado (¼ Kelly) para dimensionamiento de stake
  • Corrección de correlación entre legs (ρ Pearson por liga+jornada)
  • Pesos de _deep_score calibrables (logistic regression sobre picks históricos)
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Optional

__all__ = [
    "build_smart_accumulators",
    "build_safe_accumulators",
    "build_recommended_combo",
    "kelly_fraction",
    "PICK_LABELS",
    "MARKET_BADGE",
    "DEEP_SCORE_WEIGHTS",
]

import numpy as np
import pandas as pd


# ── Constantes de presentación ─────────────────────────────────────────────────

PICK_LABELS: dict[str, str] = {
    "1":        "Victoria Local",
    "X":        "Empate",
    "2":        "Victoria Visitante",
    "1X":       "Local o Empate",
    "X2":       "Empate o Visitante",
    "12":       "Local o Visitante",
    "OVER2.5":  "Más de 2.5 Goles",
    "UNDER2.5": "Menos de 2.5 Goles",
}

# (etiqueta corta, color de fondo para el badge)
MARKET_BADGE: dict[str, tuple[str, str]] = {
    "1X2":           ("1X2",   "#1a4d2a"),
    "double_chance": ("2 OP",  "#1a3d5c"),
    "goals":         ("GOLES", "#4d2a1a"),
}

# Umbrales para el modo inteligente (EV-optimizado)
_MIN_PROB_SINGLE = 0.45   # 1X2 — mínimo
_MIN_PROB_DC     = 0.54   # Doble oportunidad
_MIN_PROB_GOALS  = 0.50   # Goles
_MIN_EDGE        = 0.010  # Edge mínimo vs mercado

# Umbrales para el modo seguro (hit rate maximizado)
_SAFE_MIN_PROB_DC    = 0.60   # DC solo con alta probabilidad
_SAFE_MIN_PROB_GOALS = 0.55   # Goles con clara ventaja del modelo
_SAFE_MAX_DC_ODDS    = 1.85   # DC con cuota demasiado alta = pick incierto

# ── Pesos de puntuación profunda (calibrables externamente) ────────────────────
# Derivados de literatura de apuestas deportivas (Shin 1993; Levitt 2004;
# Forrest & Simmons 2008). Reemplazados por DeepScoreCalibrator cuando
# hay ≥50 picks liquidados en model_picks.
DEEP_SCORE_WEIGHTS: dict[str, float] = {
    "edge_sqrt_scale":    350.0,   # sqrt(edge) × escala
    "prob_scale":         100.0,   # (prob − floor) × escala
    "ml_dc_agree_strong":  35.0,   # acuerdo ML↔DC < 5%
    "ml_dc_agree_mod":     17.0,   # acuerdo ML↔DC < 10%
    "ml_dc_agree_weak":     6.0,   # acuerdo ML↔DC < 15%
    "ml_dc_disagree":      -6.0,   # desacuerdo ML↔DC ≥ 15%
    "consensus_scale":    300.0,   # consensus_edge × escala
    "bookmakers_5":        20.0,   # ≥5 casas disponibles
    "bookmakers_3":        10.0,   # ≥3 casas disponibles
    "market_quality":     600.0,   # (1.07 − overround) × escala
    "clv_scale":          100.0,   # CLV × escala
    "rel_scale":            0.5,   # (reliability − 50) × escala
    "dc_bonus":            45.0,   # bonus fijo para Doble Oportunidad
    "goals_bonus":         28.0,   # bonus fijo para Goles
}


# ── Generador de selecciones extendidas ────────────────────────────────────────

def _make_extended_selections(
    df: pd.DataFrame,
    min_edge: float = _MIN_EDGE,
    prob_calibrator: object = None,
) -> pd.DataFrame:
    """
    Expande el DataFrame de resultados a una fila por (partido × mercado).

    Para cada partido genera todas las selecciones viables:
      - Singles 1X2 (si modelo tiene edge suficiente)
      - Doble oportunidad 1X / X2 / 12 (si prob >= _MIN_PROB_DC)
      - Goles OVER/UNDER 2.5 (si prob >= _MIN_PROB_GOALS)

    Las cuotas de doble oportunidad se derivan de las 1X2 sin margen.
    """
    rows: list[dict] = []

    for _, r in df.iterrows():
        ph  = float(r.get("p_home",   0) or 0)
        pd_ = float(r.get("p_draw",   0) or 0)
        pa  = float(r.get("p_away",   0) or 0)
        po  = float(r.get("p_over25", 0) or 0)
        rel = float(r.get("reliability_score", 50) or 50)

        bh = r.get("B365H");  bd = r.get("B365D");  ba = r.get("B365A")
        bo = r.get("B365O25"); bu = r.get("B365U25")

        base = r.to_dict()

        # ── Singles 1X2 ──────────────────────────────────────────────────────
        if all(_valid_odd(x) for x in [bh, bd, ba]) and _valid_prob_dist(ph, pd_, pa):
            bh_, bd_, ba_ = float(bh), float(bd), float(ba)
            tot = 1/bh_ + 1/bd_ + 1/ba_
            fh, fd_, fa = (1/bh_)/tot, (1/bd_)/tot, (1/ba_)/tot

            for pick, mp, fp, odds in [
                ("1", ph, fh, bh_),
                ("X", pd_, fd_, bd_),
                ("2", pa, fa, ba_),
            ]:
                mp = _cal(mp, prob_calibrator)        # corrige el sesgo del modelo
                edge = mp - fp
                # Cap honesto: ningún pick 1X2 del modelo puede reclamar >82%
                mp_capped = min(mp, 0.82)
                if edge >= min_edge and mp_capped >= _MIN_PROB_SINGLE:
                    rows.append({**base,
                        "pick": pick, "market_type": "1X2",
                        "model_prob": mp_capped, "fair_prob": fp,
                        "edge": edge, "odds": odds, "no_bet": "NO",
                    })

            # ── Doble oportunidad (derivada de 1X2 sin margen) ───────────────
            for pick, mp, fp in [
                ("1X", ph + pd_,  fh + fd_),
                ("X2", pd_ + pa,  fd_ + fa),
                ("12", ph + pa,   fh + fa),
            ]:
                if fp <= 0:
                    continue
                # Margen típico bookmaker para DC (~4%) → cuota más realista
                dc_odds = max(1.04, round(1.0 / (fp * 1.04), 2))
                if dc_odds < 1.04:
                    continue
                mp = _cal(mp, prob_calibrator)        # corrige el sesgo del modelo
                edge = mp - fp
                # Cap: DC puede ser alta pero no más de 88%
                mp_capped = min(mp, 0.88)
                if edge >= min_edge and mp_capped >= _MIN_PROB_DC:
                    rows.append({**base,
                        "pick": pick, "market_type": "double_chance",
                        "model_prob": mp_capped, "fair_prob": fp,
                        "edge": edge, "odds": dc_odds, "no_bet": "NO",
                    })

        # ── Goles Over / Under 2.5 ────────────────────────────────────────────
        # CRÍTICO: solo usar si el modelo tiene una estimación real de goles.
        # Si po = 0 (fixture futuro sin features de goles / modelo sin datos),
        # pu = 1.0 generaría picks UNDER2.5 con 100% de probabilidad → FALSO.
        if _valid_odd(bo) and _valid_odd(bu) and _valid_over_prob(po):
            bo_, bu_ = float(bo), float(bu)
            oi, ui_ = 1/bo_, 1/bu_
            fair_o = oi / (oi + ui_)
            fair_u = ui_ / (oi + ui_)

            # Calibrar el over y derivar el under (mantiene over+under = 1)
            po_eff = _cal(po, prob_calibrator)

            o_edge = po_eff - fair_o
            if o_edge >= min_edge and po_eff >= _MIN_PROB_GOALS:
                rows.append({**base,
                    "pick": "OVER2.5", "market_type": "goals",
                    "model_prob": min(po_eff, 0.85), "fair_prob": fair_o,
                    "edge": o_edge, "odds": bo_, "no_bet": "NO",
                })

            pu = 1.0 - po_eff
            u_edge = pu - fair_u
            if u_edge >= min_edge and pu >= _MIN_PROB_GOALS:
                rows.append({**base,
                    "pick": "UNDER2.5", "market_type": "goals",
                    "model_prob": min(pu, 0.85), "fair_prob": fair_u,
                    "edge": u_edge, "odds": bu_, "no_bet": "NO",
                })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _valid_odd(x) -> bool:
    try:
        return x is not None and pd.notna(x) and float(x) > 1.05
    except (TypeError, ValueError):
        return False


def _valid_over_prob(po: float) -> bool:
    """
    El modelo solo tiene estimación útil de goles si p_over está entre 10% y 90%.
    Si po ≈ 0 (el modelo devuelve 0.0 por falta de datos / fixture futuro sin features),
    usar pu = 1 - po = 1.0 generaría picks UNDER2.5 con 100% de probabilidad falsa.
    """
    return 0.10 <= po <= 0.90


def _valid_prob_dist(ph: float, pd: float, pa: float) -> bool:
    """Las probabilidades 1X2 del ensemble deben sumar aproximadamente 1."""
    return 0.92 <= (ph + pd + pa) <= 1.08


def _cal(mp: float, calibrator) -> float:
    """
    Corrige la probabilidad de una selección con el calibrador isotónico.

    Crucial en combinadas: al multiplicar probabilidades, cualquier sesgo del
    modelo se AMPLIFICA. Calibrar cada leg antes de combinar evita que el EV y
    el Kelly de la combinada salgan sistemáticamente optimistas. Si no hay
    calibrador ajustado, devuelve la probabilidad sin cambios (identidad).
    """
    if calibrator is not None and getattr(calibrator, "is_fitted", False):
        try:
            return float(calibrator.transform(mp))
        except Exception:
            return mp
    return mp


# ── Puntuación de análisis profundo ───────────────────────────────────────────

def _deep_score(row, weights: dict | None = None) -> float:
    """
    Puntuación 0-∞ para una selección considerando múltiples factores.
    Usado para ordenar candidatos antes de construir el acumulador.

    weights: si se proporciona, sobreescribe DEEP_SCORE_WEIGHTS (calibración externa).
    """
    W          = weights if weights is not None else DEEP_SCORE_WEIGHTS
    edge       = float(row.get("edge",              0) or 0)
    model_prob = float(row.get("model_prob",         0) or 0)
    rel        = float(row.get("reliability_score",  50) or 50)
    mtype      = row.get("market_type", "1X2")

    # 1. Edge vs mercado (señal principal — transformación sqrt para reducir outliers)
    score = math.sqrt(max(0, edge)) * W["edge_sqrt_scale"]

    # 2. Probabilidad del modelo (confianza por encima del umbral mínimo del mercado)
    prob_floor = {"double_chance": 0.60, "goals": 0.52, "1X2": 0.48}
    score += max(0, (model_prob - prob_floor.get(mtype, 0.48)) * W["prob_scale"])

    # 3. Acuerdo ML ↔ Dixon-Coles (ensemble estable = señal más fiable)
    ph_ml = float(row.get("p_home_ml") or row.get("p_home", 0) or 0)
    ph_dc = row.get("p_home_dc")
    if ph_dc is not None and pd.notna(ph_dc):
        diff = abs(ph_ml - float(ph_dc))
        if   diff < 0.05:  score += W["ml_dc_agree_strong"]
        elif diff < 0.10:  score += W["ml_dc_agree_mod"]
        elif diff < 0.15:  score += W["ml_dc_agree_weak"]
        else:              score += W["ml_dc_disagree"]

    # 4. Consenso multi-casa (sabiduría del mercado)
    ce   = row.get("consensus_edge")
    n_bk = int(row.get("n_bookmakers", 0) or 0)
    if ce is not None and pd.notna(ce) and float(ce) > 0:
        score += float(ce) * W["consensus_scale"]
    if   n_bk >= 5: score += W["bookmakers_5"]
    elif n_bk >= 3: score += W["bookmakers_3"]

    # 5. Calidad de mercado (overround bajo = mercado líquido = difícil de batir)
    m_or = row.get("m_open_overround")
    if m_or is not None and pd.notna(m_or):
        score += max(0, (1.07 - float(m_or)) * W["market_quality"])

    # 6. CLV positivo (beat the close = señal más fuerte de edge real)
    clv = row.get("clv")
    if clv is not None and pd.notna(clv) and float(clv) > 0:
        score += float(clv) * W["clv_scale"]

    # 7. Fiabilidad histórica del modelo en este tipo de partido
    score += (rel - 50) * W["rel_scale"]

    # 8. Bonus por tipo de mercado (hit rate empírico DC > Goles > 1X2)
    if mtype == "double_chance":
        score += W["dc_bonus"]
    elif mtype == "goals":
        score += W["goals_bonus"]

    return score


# ── Kelly Criterion ────────────────────────────────────────────────────────────

def kelly_fraction(
    model_prob: float,
    odds: float,
    fraction: float = 0.25,
    max_kelly: float = 0.05,
) -> float:
    """
    Fracción de Kelly para dimensionar el stake de una combinada.

    Fórmula:  f* = (b·p − q) / b   donde b = odds − 1, q = 1 − p
    Simplificada: f* = (odds·p − 1) / (odds − 1) = EV / (odds − 1)

    fraction = 0.25  → ¼ Kelly (estándar para apuestas combinadas;
                        reduce varianza sin sacrificar mucho EV).
    max_kelly = 0.05 → techo del 5% del bankroll por combinada.

    Returns: fracción de bankroll recomendada (0.0 si EV negativo).
    """
    b = odds - 1.0
    if b <= 0 or model_prob <= 0 or model_prob >= 1:
        return 0.0
    f_full = (b * model_prob - (1.0 - model_prob)) / b
    if f_full <= 0:
        return 0.0
    return min(round(f_full * fraction, 4), max_kelly)


# ── Correlación entre legs ─────────────────────────────────────────────────────

def _rho_estimate(leg_i: dict, leg_j: dict) -> float:
    """
    Estima ρ de Pearson entre dos legs según liga y fecha.

    Misma liga + misma jornada → ρ = 0.15 (efectos sistémicos de jornada)
    Misma liga, distinta jornada → ρ = 0.08 (estilo de liga compartido)
    Ligas distintas → ρ ≈ 0 (independientes)
    """
    li = str(leg_i.get("league", "") or "").strip()
    lj = str(leg_j.get("league", "") or "").strip()
    same_league = bool(li and lj and li == lj)

    di = str(leg_i.get("date", "") or "")[:10]
    dj = str(leg_j.get("date", "") or "")[:10]
    same_date = bool(di and dj and di == dj)

    if same_league and same_date:
        return 0.15
    if same_league:
        return 0.08
    return 0.0


def _legs_correlation_info(legs: list) -> dict:
    """
    Calcula el impacto de correlación entre todos los pares de legs.

    La correlación positiva (misma liga/jornada) tiene dos efectos opuestos:
      · prob_factor > 1: P(todos ganan) es ligeramente MAYOR que el producto
        independiente porque los factores sistémicos favorecen a todos a la vez.
      · kelly_factor < 1: la varianza es más alta, por lo que el stake óptimo
        de Kelly se REDUCE para proteger el bankroll.

    Returns dict:
      rho_max       — correlación máxima entre cualquier par de legs
      n_corr_pairs  — nº de pares con ρ > 0
      prob_factor   — multiplicador para combined_prob  (0.80 – 1.20)
      kelly_factor  — reductor para kelly_pct           (0.0 – 1.0)
      summary       — texto corto para la UI
    """
    n = len(legs)
    if n < 2:
        return {"rho_max": 0.0, "n_corr_pairs": 0,
                "prob_factor": 1.0, "kelly_factor": 1.0, "summary": ""}

    rho_max      = 0.0
    n_corr_pairs = 0
    prob_adj_sum = 0.0
    pair_count   = 0

    for i in range(n):
        for j in range(i + 1, n):
            rho = _rho_estimate(legs[i], legs[j])
            pair_count += 1
            if rho > 0:
                n_corr_pairs += 1
                rho_max = max(rho_max, rho)

                pi = float(legs[i].get("model_prob", 0.5) or 0.5)
                pj = float(legs[j].get("model_prob", 0.5) or 0.5)
                sigma_i = math.sqrt(max(0.0, pi * (1.0 - pi)))
                sigma_j = math.sqrt(max(0.0, pj * (1.0 - pj)))

                # P(A∩B)_corr / P(A∩B)_indep = 1 + ρ·σi·σj / (pi·pj)
                if pi * pj > 0:
                    prob_adj_sum += rho * sigma_i * sigma_j / (pi * pj)

    if pair_count == 0:
        return {"rho_max": 0.0, "n_corr_pairs": 0,
                "prob_factor": 1.0, "kelly_factor": 1.0, "summary": ""}

    # Prob factor: promedio de ajustes pairwise, acotado a [0.85, 1.20]
    prob_factor   = float(np.clip(1.0 + prob_adj_sum / pair_count, 0.85, 1.20))

    # Kelly factor: reducción por mayor varianza — escala con sqrt(1 − ρ_max)
    kelly_factor  = float(np.clip(math.sqrt(1.0 - rho_max), 0.50, 1.0))

    # Resumen para la UI
    if n_corr_pairs == 0:
        summary = ""
    elif rho_max >= 0.15:
        summary = f"⚠ {n_corr_pairs} par(es) misma liga+jornada · ρ={rho_max:.2f}"
    else:
        summary = f"ℹ {n_corr_pairs} par(es) misma liga · ρ={rho_max:.2f}"

    return {
        "rho_max":      round(rho_max, 3),
        "n_corr_pairs": n_corr_pairs,
        "prob_factor":  round(prob_factor, 4),
        "kelly_factor": round(kelly_factor, 4),
        "summary":      summary,
    }


def _analysis_flags(row) -> dict:
    """Indicadores de confirmación para mostrar en la UI."""
    ph_ml = float(row.get("p_home_ml") or row.get("p_home", 0) or 0)
    ph_dc = row.get("p_home_dc")
    ce    = row.get("consensus_edge")
    clv   = row.get("clv")
    n_bk  = int(row.get("n_bookmakers", 0) or 0)

    ml_dc_agree = (
        ph_dc is not None
        and pd.notna(ph_dc)
        and abs(ph_ml - float(ph_dc)) < 0.10
    )
    has_consensus = (
        ce is not None
        and pd.notna(ce)
        and float(ce) > 0
        and n_bk >= 3
    )
    clv_positive = (
        clv is not None
        and pd.notna(clv)
        and float(clv) > 0
    )
    high_prob = float(row.get("model_prob", 0) or 0) >= 0.62

    return {
        "ml_dc_agree":   ml_dc_agree,
        "has_consensus": has_consensus,
        "clv_positive":  clv_positive,
        "high_prob":     high_prob,
        "n_confirmations": sum([ml_dc_agree, has_consensus, clv_positive, high_prob]),
    }


# ── Apuesta recomendada ────────────────────────────────────────────────────────

def build_recommended_combo(
    df: pd.DataFrame,
    target_min_odds: float = 1.40,
    target_max_odds: float = 2.20,
    weights: dict | None = None,
    prob_calibrator: object = None,
) -> Optional[Dict]:
    """
    Genera la mejor combinada 2-patas con cuota total 1.40-2.20.
    Usa todas las selecciones (1X2 + doble oportunidad + goles) para
    maximizar la probabilidad de acierto con análisis profundo.
    Incluye Kelly Criterion y corrección de correlación entre legs.
    """
    if df.empty:
        return None

    cands = _make_extended_selections(df, min_edge=_MIN_EDGE,
                                      prob_calibrator=prob_calibrator)
    if cands.empty or len(cands) < 2:
        return None

    cands["_ds"] = cands.apply(lambda r: _deep_score(r, weights), axis=1)
    cands = cands.sort_values("_ds", ascending=False).head(20)

    best: Optional[Dict] = None
    best_score = -999.0

    for (i1, r1), (i2, r2) in combinations(cands.iterrows(), 2):
        # No repetir mismo partido
        if (r1.get("home_team") == r2.get("home_team")
                and r1.get("away_team") == r2.get("away_team")):
            continue

        c_odds = float(r1["odds"]) * float(r2["odds"])
        if not (target_min_odds <= c_odds <= target_max_odds):
            continue

        legs_list   = [r1, r2]
        corr        = _legs_correlation_info(legs_list)
        c_prob_raw  = float(r1["model_prob"]) * float(r2["model_prob"])
        c_prob      = round(c_prob_raw * corr["prob_factor"], 4)
        c_ev        = c_prob * c_odds - 1.0
        c_score     = float(r1["_ds"]) + float(r2["_ds"]) + c_ev * 120
        kelly_pct   = kelly_fraction(c_prob, c_odds) * corr["kelly_factor"]

        if c_score > best_score:
            best_score = c_score
            best = {
                "n_legs":        2,
                "combined_odds": round(c_odds, 2),
                "combined_prob": c_prob,
                "ev":            round(c_ev, 4),
                "score":         round(c_score, 2),
                "kelly_pct":     round(kelly_pct, 4),
                "corr_info":     corr,
                "legs":          legs_list,
                "market_mix":    _market_mix(legs_list),
                "method":        "Análisis profundo · ML+DC+Consenso",
                "flags":         [_analysis_flags(r1), _analysis_flags(r2)],
            }

    return best


# ── Acumuladores inteligentes por categoría ───────────────────────────────────

def build_smart_accumulators(
    df: pd.DataFrame,
    min_legs: int = 2,
    max_legs: int = 4,
    top_candidates: int = 16,
    weights: dict | None = None,
    prob_calibrator: object = None,
) -> List[Dict]:
    """
    Genera las mejores combinadas con análisis profundo multi-mercado.

    Para cada tamaño (min_legs..max_legs) devuelve la combinada con mayor EV
    usando todas las selecciones disponibles (1X2, doble oportunidad, goles).

    Cada combinada incluye:
      n_legs, combined_prob, combined_odds, ev, avg_reliability,
      avg_edge, min_reliability, legs, market_mix, flags (por leg),
      kelly_pct, corr_info.
    """
    if df.empty:
        return []

    # Generar todas las selecciones viables (calibradas si hay calibrador)
    all_sel = _make_extended_selections(df, min_edge=_MIN_EDGE,
                                        prob_calibrator=prob_calibrator)

    if all_sel.empty or len(all_sel) < min_legs:
        # Fallback: usar solo los picks del modelo (comportamiento anterior)
        all_sel = df[
            (df["no_bet"] == "NO")
            & df["odds"].notna()
            & df["model_prob"].notna()
            & df["edge"].notna()
        ].copy()
        if len(all_sel) < min_legs:
            return []
        all_sel["market_type"] = "1X2"

    # Puntuar y pre-seleccionar candidatos con pesos actuales (calibrados o default)
    all_sel["_ds"] = all_sel.apply(lambda r: _deep_score(r, weights), axis=1)
    all_sel = all_sel.sort_values("_ds", ascending=False).head(top_candidates)

    accumulators: List[Dict] = []

    for n_legs in range(min_legs, max_legs + 1):
        if len(all_sel) < n_legs:
            continue

        best: Optional[Dict] = None

        for combo_iter in combinations(all_sel.iterrows(), n_legs):
            legs = [row for _, row in combo_iter]

            # Evitar dos selecciones del mismo partido
            match_keys = [
                f"{l.get('home_team','?')}::{l.get('away_team','?')}"
                for l in legs
            ]
            if len(set(match_keys)) < n_legs:
                continue

            corr      = _legs_correlation_info(legs)
            c_prob_raw = float(np.prod([float(l["model_prob"]) for l in legs]))
            c_prob    = round(c_prob_raw * corr["prob_factor"], 4)
            c_odds    = float(np.prod([float(l["odds"])        for l in legs]))
            ev        = c_prob * c_odds - 1.0
            avg_rel   = float(np.mean([float(l.get("reliability_score", 50) or 50) for l in legs]))
            avg_edge  = float(np.mean([float(l.get("edge", 0) or 0)               for l in legs]))
            min_rel   = float(min(float(l.get("reliability_score", 50) or 50)     for l in legs))
            kelly_pct = kelly_fraction(c_prob, c_odds) * corr["kelly_factor"]

            # Score balanceado: calidad de las selecciones (deep_score, que premia
            # probabilidad y confirmaciones) + EV. Evita elegir la combinada de
            # máximo EV pero improbable (longshot de alta varianza, baja tasa de
            # acierto) — mismo criterio que la apuesta recomendada.
            sel_score = sum(float(l.get("_ds", 0) or 0) for l in legs) + ev * 120

            entry: Dict = {
                "n_legs":          n_legs,
                "combined_prob":   c_prob,
                "combined_odds":   round(c_odds, 2),
                "ev":              round(ev, 4),
                "avg_reliability": round(avg_rel, 1),
                "avg_edge":        round(avg_edge, 4),
                "min_reliability": round(min_rel, 1),
                "kelly_pct":       round(kelly_pct, 4),
                "score":           round(sel_score, 2),
                "corr_info":       corr,
                "legs":            legs,
                "market_mix":      _market_mix(legs),
                "flags":           [_analysis_flags(l) for l in legs],
            }

            if best is None or sel_score > best["score"]:
                best = entry

        if best is not None:
            accumulators.append(best)

    return accumulators


# ── Combinadas seguras (DC + Goles, hit rate máxima) ─────────────────────────

def build_safe_accumulators(
    df: pd.DataFrame,
    min_legs: int = 2,
    max_legs: int = 3,
    weights: dict | None = None,
    prob_calibrator: object = None,
) -> List[Dict]:
    """
    Genera combinadas de alta fiabilidad usando SOLO Doble Oportunidad y Goles.

    Optimiza para tasa de acierto máxima (combined_prob) en lugar de EV.
    Requiere probabilidad del modelo >= 60% en DC y >= 55% en goles.
    Las cuotas DC se calculan con margen ~4% sobre la prob. no-vig del mercado.
    Incluye Kelly Criterion y corrección de correlación.
    """
    if df.empty:
        return []

    rows: list[dict] = []

    for _, r in df.iterrows():
        ph  = float(r.get("p_home",   0) or 0)
        pd_ = float(r.get("p_draw",   0) or 0)
        pa  = float(r.get("p_away",   0) or 0)
        po  = float(r.get("p_over25", 0) or 0)

        bh = r.get("B365H"); bd = r.get("B365D"); ba = r.get("B365A")
        bo = r.get("B365O25"); bu = r.get("B365U25")

        base = r.to_dict()

        # ── Doble oportunidad ──────────────────────────────────────────────────
        if all(_valid_odd(x) for x in [bh, bd, ba]) and _valid_prob_dist(ph, pd_, pa):
            bh_, bd_, ba_ = float(bh), float(bd), float(ba)
            tot = 1/bh_ + 1/bd_ + 1/ba_
            fh, fd, fa = (1/bh_)/tot, (1/bd_)/tot, (1/ba_)/tot

            for pick, mp, fp in [
                ("1X", ph + pd_, fh + fd),
                ("X2", pd_ + pa, fd + fa),
                ("12", ph + pa,  fh + fa),
            ]:
                if fp <= 0:
                    continue
                dc_odds = max(1.04, round(1.0 / (fp * 1.04), 2))
                if dc_odds >= _SAFE_MAX_DC_ODDS:
                    continue  # cuota alta → pick demasiado incierto
                mp = _cal(mp, prob_calibrator)        # corrige el sesgo del modelo
                # Cap honesto para DC
                mp_capped = min(mp, 0.88)
                if mp_capped >= _SAFE_MIN_PROB_DC:
                    rows.append({**base,
                        "pick": pick, "market_type": "double_chance",
                        "model_prob": mp_capped, "fair_prob": fp,
                        "edge": max(0.0, mp - fp), "odds": dc_odds, "no_bet": "NO",
                    })

        # ── Goles Over / Under 2.5 ────────────────────────────────────────────
        # Igual que en _make_extended_selections: solo si el modelo tiene
        # una estimación meaningful (po entre 10% y 90%).
        if _valid_odd(bo) and _valid_odd(bu) and _valid_over_prob(po):
            bo_, bu_ = float(bo), float(bu)
            oi, ui  = 1/bo_, 1/bu_
            fair_o  = oi / (oi + ui)
            fair_u  = 1.0 - fair_o

            po_eff = _cal(po, prob_calibrator)
            if po_eff >= _SAFE_MIN_PROB_GOALS:
                rows.append({**base,
                    "pick": "OVER2.5", "market_type": "goals",
                    "model_prob": min(po_eff, 0.85), "fair_prob": fair_o,
                    "edge": max(0.0, po_eff - fair_o), "odds": bo_, "no_bet": "NO",
                })
            pu = 1.0 - po_eff
            if pu >= _SAFE_MIN_PROB_GOALS:
                rows.append({**base,
                    "pick": "UNDER2.5", "market_type": "goals",
                    "model_prob": min(pu, 0.85), "fair_prob": fair_u,
                    "edge": max(0.0, pu - fair_u), "odds": bu_, "no_bet": "NO",
                })

    if len(rows) < min_legs:
        return []

    cands = pd.DataFrame(rows)
    # Ordenar por probabilidad del modelo descendente (seguridad primero)
    cands = cands.sort_values("model_prob", ascending=False).head(24)

    accumulators: List[Dict] = []

    for n_legs in range(min_legs, max_legs + 1):
        if len(cands) < n_legs:
            continue

        best: Optional[Dict] = None

        for combo_iter in combinations(cands.iterrows(), n_legs):
            legs = [row for _, row in combo_iter]

            match_keys = [
                f"{l.get('home_team','?')}::{l.get('away_team','?')}"
                for l in legs
            ]
            if len(set(match_keys)) < n_legs:
                continue

            corr       = _legs_correlation_info(legs)
            c_prob_raw = float(np.prod([float(l["model_prob"]) for l in legs]))
            c_prob     = round(c_prob_raw * corr["prob_factor"], 4)
            c_odds     = float(np.prod([float(l["odds"])        for l in legs]))
            ev         = c_prob * c_odds - 1.0
            avg_rel    = float(np.mean([float(l.get("reliability_score", 50) or 50) for l in legs]))
            avg_edge   = float(np.mean([float(l.get("edge", 0) or 0)               for l in legs]))
            min_rel    = float(min(float(l.get("reliability_score", 50) or 50)     for l in legs))
            kelly_pct  = kelly_fraction(c_prob, c_odds) * corr["kelly_factor"]

            entry: Dict = {
                "n_legs":          n_legs,
                "combined_prob":   c_prob,
                "combined_odds":   round(c_odds, 2),
                "ev":              round(ev, 4),
                "avg_reliability": round(avg_rel, 1),
                "avg_edge":        round(avg_edge, 4),
                "min_reliability": round(min_rel, 1),
                "kelly_pct":       round(kelly_pct, 4),
                "corr_info":       corr,
                "legs":            legs,
                "market_mix":      _market_mix(legs),
                "flags":           [_analysis_flags(l) for l in legs],
                "safe_mode":       True,
            }

            # Priorizar tasa de acierto (combined_prob) sobre EV
            if best is None or c_prob > best["combined_prob"]:
                best = entry

        if best is not None:
            accumulators.append(best)

    return accumulators


# ── Helpers ────────────────────────────────────────────────────────────────────

def _market_mix(legs: list) -> dict:
    """Resumen de los tipos de mercado en una combinada."""
    counts: dict[str, int] = {}
    for leg in legs:
        mt = leg.get("market_type", "1X2") if hasattr(leg, "get") else "1X2"
        counts[mt] = counts.get(mt, 0) + 1
    return counts
