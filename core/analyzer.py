"""
analyzer.py — Pipeline de análisis: backtest walk-forward, Kelly, scoring de riesgo.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from .config import (
    CLV_MIN, KELLY_CAP, KELLY_FRACTION,
    MAX_OVERROUND_1X2, MAX_OVERROUND_OU, MIN_SAMPLE, MODEL_FILE,
)
from .consensus import bookmakers_from_api_response, consensus_from_bookmakers, edge_vs_consensus
from .data import fetch_csv, prepare_fixtures, prepare_historic
from .features import (
    build_feature_row, build_team_long,
    extract_market_features, fair_probs, overround,
)
from .model import FootballModel
from .poisson import DixonColesModel

logger = logging.getLogger(__name__)


# ── Helpers financieros ────────────────────────────────────────────────────────

def fractional_kelly(
    prob: float,
    odds: float,
    frac: float = KELLY_FRACTION,
    cap:  float = KELLY_CAP,
) -> float:
    if not prob or not odds or odds <= 1:
        return 0.0
    b = odds - 1.0
    q = 1.0 - prob
    full_kelly = (b * prob - q) / b if b > 0 else 0.0
    return round(max(0.0, min(full_kelly * frac, cap)), 4)


def compute_reliability(
    edge: Optional[float],
    model_prob: Optional[float],
    fair_prob: Optional[float],
    bt_roi: float,
    bt_logloss: float,
) -> int:
    score = 50.0
    score += max(0, min(20, (edge or 0) * 250))
    score += max(0, min(15, bt_roi * 200))
    score += max(0, min(10, (1.15 - bt_logloss) * 25))
    if model_prob is not None and fair_prob is not None:
        score += max(0, min(5, (model_prob - fair_prob) * 100))
    return int(max(0, min(99, round(score))))


def assess_risk(
    edge: Optional[float],
    reliability: int,
    passes_filters: bool,
    market: str,
) -> tuple[str, str]:
    if market == "NO BET":
        return "ROJO", "No apostar"
    if not passes_filters or reliability < 58:
        return "ROJO", "Muestra o calibración insuficiente"
    if edge is not None and edge >= 0.08 and reliability >= 74:
        return "VERDE", "Ventaja estadística sólida"
    if edge is not None and edge >= 0.045 and reliability >= 64:
        return "AMARILLO", "Hay valor pero con cautela"
    return "ROJO", "Ventaja insuficiente"


# ── Backtest walk-forward ──────────────────────────────────────────────────────

def run_backtest(
    model: FootballModel,
    training_df: pd.DataFrame,
    edge_1x2: float,
    edge_ou: float,
) -> dict:
    """
    Backtest temporal: evalúa solo en la mitad más reciente del dataset
    para evitar sobreoptimismo in-sample.
    """
    n = len(training_df)
    eval_df = training_df.iloc[n // 2:].copy()   # sólo segunda mitad

    profit = bets = wins = 0
    roi_1x2_bets = roi_o25_bets = 0
    roi_1x2_profit = roi_o25_profit = 0.0

    for _, r in eval_df.iterrows():
        p_home, p_draw, p_away, _, p_over = model.predict_row(r)
        market = None

        if all(pd.notna(r.get(c)) for c in ["B365H", "B365D", "B365A"]):
            fh, fd, fa = fair_probs(float(r["B365H"]), float(r["B365D"]), float(r["B365A"]))
            edges = {"1": p_home - fh, "X": p_draw - fd, "2": p_away - fa}
            best  = max(edges, key=edges.get)

            if edges[best] >= edge_1x2:
                odds = {"1": float(r["B365H"]), "X": float(r["B365D"]), "2": float(r["B365A"])}[best]
                won  = (
                    (best == "1" and r["result"] == "H")
                    or (best == "X" and r["result"] == "D")
                    or (best == "2" and r["result"] == "A")
                )
                pnl = (odds - 1) if won else -1.0
                profit += pnl; bets += 1; wins += int(won)
                roi_1x2_bets += 1; roi_1x2_profit += pnl
                market = best

        if market is None and pd.notna(r.get("B365O25")) and pd.notna(r.get("B365U25")):
            over_imp  = 1 / float(r["B365O25"])
            under_imp = 1 / float(r["B365U25"])
            over_fair = over_imp / (over_imp + under_imp)
            over_edge = p_over - over_fair

            if over_edge >= edge_ou:
                odds = float(r["B365O25"])
                won  = int(r["over25"]) == 1
                pnl  = (odds - 1) if won else -1.0
                profit += pnl; bets += 1; wins += int(won)
                roi_o25_bets += 1; roi_o25_profit += pnl

    return {
        "bets":             bets,
        "profit":           round(profit, 2),
        "roi":              round(profit / bets, 4) if bets else 0.0,
        "hit":              round(wins / bets, 4)   if bets else 0.0,
        "market_1x2_roi":   round(roi_1x2_profit / roi_1x2_bets, 4) if roi_1x2_bets else 0.0,
        "market_o25_roi":   round(roi_o25_profit / roi_o25_bets, 4) if roi_o25_bets else 0.0,
        "eval_samples":     len(eval_df),
    }


# ── Dataset de entrenamiento ───────────────────────────────────────────────────

def build_training_frame(hist_by_div: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for div, hist_df in hist_by_div.items():
        long_df = build_team_long(hist_df)
        for i, r in hist_df.iterrows():
            feat = build_feature_row(long_df, r.home_team, r.away_team, idx_limit=i)
            if feat is None:
                continue
            feat.update(extract_market_features(r))
            feat.update({
                "div":         div,
                "result":      r.result,
                "over25":      r.over25,
                "total_goals": r.total_goals,
                "B365H":       r.get("B365H"),
                "B365D":       r.get("B365D"),
                "B365A":       r.get("B365A"),
                "B365O25":     r.get("B365O25"),
                "B365U25":     r.get("B365U25"),
            })
            rows.append(feat)
    return pd.DataFrame(rows)


# ── Análisis principal ─────────────────────────────────────────────────────────

class Analyzer:
    def __init__(
        self,
        hist_by_div: dict[str, pd.DataFrame],
        fixtures_df: pd.DataFrame,
    ) -> None:
        self.hist_by_div = {k: prepare_historic(v) for k, v in hist_by_div.items()}
        self.fixtures    = prepare_fixtures(fixtures_df)
        self.model       = FootballModel.load_or_none(MODEL_FILE) or FootballModel()
        self.dc_model    = DixonColesModel()   # Modelo Poisson Dixon-Coles
        self.diagnostics:      list[str] = []
        self.backtest_summary: dict      = {}

    def run(
        self,
        selected_divs: list[str],
        edge_1x2: float = 0.03,
        edge_ou:  float = 0.03,
        force_retrain: bool = False,
        progress_cb=None,
    ) -> pd.DataFrame:

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        _cb("Construyendo dataset de entrenamiento…")
        train_all = build_training_frame(self.hist_by_div)
        if train_all.empty:
            raise ValueError("No se pudo construir el dataset de entrenamiento.")

        # Entrenar ML solo si es necesario
        if force_retrain or not self.model._fitted:
            _cb("Entrenando ML (RandomForest + GradientBoosting)…")
            self.model.fit(train_all)
            self.model.save(MODEL_FILE)

        # Entrenar Dixon-Coles con todos los históricos disponibles
        all_hist = pd.concat(list(self.hist_by_div.values()), ignore_index=True) \
                   if self.hist_by_div else pd.DataFrame()
        if len(all_hist) >= 50:
            _cb("Entrenando Dixon-Coles Poisson…")
            self.dc_model.fit(all_hist)

        _cb("Generando predicciones…")

        self.diagnostics = [
            f"Entrenado con {self.model.metrics['train_samples']} muestras",
            f"Log-loss OOS (1X2): {self.model.metrics['oos_match_logloss']:.4f}",
            f"Brier OOS (O2.5):   {self.model.metrics['oos_over_brier']:.4f}",
            f"Walk-forward splits: {self.model.metrics['wf_splits']}",
            f"Fixtures cargados:  {len(self.fixtures)}",
        ]

        rows = []
        for div in selected_divs:
            div_train = train_all[train_all["div"] == div].copy()
            bt_source = div_train if len(div_train) > 40 else train_all
            bt = run_backtest(self.model, bt_source, edge_1x2, edge_ou)
            bt["match_logloss"] = self.model.metrics["oos_match_logloss"]
            self.backtest_summary[div] = bt

            hist_df = self.hist_by_div.get(div)
            if hist_df is None or hist_df.empty:
                continue

            long_df = build_team_long(hist_df)
            fx = self.fixtures[self.fixtures["div"] == div].copy()

            for _, r in fx.iterrows():
                feat = build_feature_row(long_df, r.home_team, r.away_team)
                if feat is None:
                    continue

                feat.update(extract_market_features(r))
                feat_row = pd.Series(feat)

                p_home_ml, p_draw_ml, p_away_ml, expected_goals, p_over = \
                    self.model.predict_row(feat_row)

                # ── Ensemble ML + Dixon-Coles (60/40) ─────────────────────────
                dc_pred = self.dc_model.predict(r.home_team, r.away_team) \
                          if self.dc_model.is_fitted() else None

                if dc_pred is not None:
                    dc_h, dc_d, dc_a, _lh, _la = dc_pred
                    p_home = round(0.60 * p_home_ml + 0.40 * dc_h, 4)
                    p_draw = round(0.60 * p_draw_ml + 0.40 * dc_d, 4)
                    p_away = round(0.60 * p_away_ml + 0.40 * dc_a, 4)
                else:
                    p_home, p_draw, p_away = p_home_ml, p_draw_ml, p_away_ml
                    dc_h = dc_d = dc_a = None

                # ── Consenso multi-casa (The Odds API) ────────────────────────
                raw_bks       = r.get("_bookmakers_raw", []) or []
                bk_list       = bookmakers_from_api_response({"home_team": r.home_team,
                                                               "away_team": r.away_team,
                                                               "bookmakers": raw_bks})
                consensus_res = consensus_from_bookmakers(bk_list)
                if consensus_res:
                    cons_h, cons_d, cons_a, n_bks = consensus_res
                else:
                    cons_h = cons_d = cons_a = None
                    n_bks  = 0

                market      = "NO BET"
                edge        = None
                odds        = None
                model_prob  = None
                fair_prob   = None
                ev          = None
                opening_fair  = None
                closing_fair  = None
                clv           = None
                market_move   = None
                consensus_edge = None

                # ── 1X2 ───────────────────────────────────────────────────────
                if all(pd.notna(r.get(c)) for c in ["B365H", "B365D", "B365A"]):
                    fh, fd, fa = fair_probs(
                        float(r["B365H"]), float(r["B365D"]), float(r["B365A"])
                    )
                    edges = {"1": p_home - fh, "X": p_draw - fd, "2": p_away - fa}
                    best  = max(edges, key=edges.get)

                    if edges[best] >= edge_1x2:
                        market     = best
                        edge       = float(edges[best])
                        odds       = {"1": float(r["B365H"]), "X": float(r["B365D"]), "2": float(r["B365A"])}[best]
                        model_prob = {"1": p_home, "X": p_draw, "2": p_away}[best]
                        fair_prob  = {"1": fh, "X": fd, "2": fa}[best]
                        opening_fair = fair_prob
                        ev = model_prob * odds - 1.0
                        # Edge vs consenso multi-casa
                        if cons_h is not None:
                            cons_map = {"1": cons_h, "X": cons_d, "2": cons_a}
                            consensus_edge = edge_vs_consensus(model_prob, cons_map[best])

                        if all(pd.notna(r.get(c)) for c in ["B365CH", "B365CD", "B365CA"]):
                            cp = fair_probs(float(r["B365CH"]), float(r["B365CD"]), float(r["B365CA"]))
                            closing_fair = {"1": cp[0], "X": cp[1], "2": cp[2]}[best]
                            clv         = opening_fair - closing_fair
                            market_move = closing_fair - opening_fair

                # ── Over 2.5 ─────────────────────────────────────────────────
                if pd.notna(r.get("B365O25")) and pd.notna(r.get("B365U25")):
                    oi  = 1 / float(r["B365O25"])
                    ui  = 1 / float(r["B365U25"])
                    ofa = oi / (oi + ui)
                    oe  = p_over - ofa

                    if oe >= edge_ou and (edge is None or oe > edge):
                        market       = "OVER2.5"
                        edge         = float(oe)
                        odds         = float(r["B365O25"])
                        model_prob   = p_over
                        fair_prob    = ofa
                        opening_fair = fair_prob
                        ev           = model_prob * odds - 1.0

                        if pd.notna(r.get("B365C>2.5")) and pd.notna(r.get("B365C<2.5")):
                            coi = 1 / float(r["B365C>2.5"])
                            cui = 1 / float(r["B365C<2.5"])
                            closing_fair = coi / (coi + cui)
                            clv         = opening_fair - closing_fair
                            market_move = closing_fair - opening_fair

                # ── Filtros y scoring ─────────────────────────────────────────
                sample_ok      = feat_row.get("f_sample_min", 0) >= MIN_SAMPLE
                overround_ok   = (
                    (pd.isna(feat_row.get("m_open_overround"))    or feat_row.get("m_open_overround")    <= MAX_OVERROUND_1X2)
                    and (pd.isna(feat_row.get("m_open_ou_overround")) or feat_row.get("m_open_ou_overround") <= MAX_OVERROUND_OU)
                )
                clv_ok         = clv is None or clv >= CLV_MIN
                edge_ok        = edge is not None and edge >= max(edge_1x2 if market in ["1", "X", "2"] else edge_ou, 0.025)
                passes_filters = sample_ok and overround_ok and clv_ok and edge_ok

                reliability  = compute_reliability(edge, model_prob, fair_prob, bt.get("roi", 0), bt.get("match_logloss", self.model.metrics["oos_match_logloss"]))
                risk_light, reason = assess_risk(edge, reliability, passes_filters, market)
                no_bet       = "SI" if risk_light == "ROJO" else "NO"
                bankroll_pct = 0.0 if no_bet == "SI" else fractional_kelly(model_prob, odds) * 100

                rows.append({
                    "date":            r.get("date"),
                    "time":            r.get("time", ""),
                    "league":          div,
                    "home_team":       r.home_team,
                    "away_team":       r.away_team,
                    "pick":            market,
                    "odds":            round(odds, 2)         if odds        is not None else None,
                    # Cuotas brutas de mercado para el simulador
                    "B365H":           r.get("B365H"),
                    "B365D":           r.get("B365D"),
                    "B365A":           r.get("B365A"),
                    "B365O25":         r.get("B365O25"),
                    "B365U25":         r.get("B365U25"),
                    "edge":            round(edge, 4)         if edge        is not None else None,
                    "model_prob":      round(model_prob, 4)   if model_prob  is not None else None,
                    "fair_prob":       round(fair_prob, 4)    if fair_prob   is not None else None,
                    "open_fair_prob":  round(opening_fair, 4) if opening_fair is not None else None,
                    "close_fair_prob": round(closing_fair, 4) if closing_fair is not None else None,
                    "clv":             round(clv, 4)          if clv         is not None else None,
                    "market_move":     round(market_move, 4)  if market_move is not None else None,
                    "open_overround":  (round(feat_row.get("m_open_overround"), 4)    if pd.notna(feat_row.get("m_open_overround"))    else None),
                    "close_overround": (round(feat_row.get("m_close_overround"), 4)   if pd.notna(feat_row.get("m_close_overround"))   else None),
                    "market_entropy":  (round(feat_row.get("m_open_entropy"), 4)      if pd.notna(feat_row.get("m_open_entropy"))      else None),
                    "ev":              round(ev, 4)            if ev          is not None else None,
                    "expected_goals":  round(expected_goals, 2),
                    # Ensemble: probabilidades finales (ML 60% + DC 40%)
                    "p_home":          round(p_home, 4),
                    "p_draw":          round(p_draw, 4),
                    "p_away":          round(p_away, 4),
                    "p_over25":        round(p_over, 4),
                    # Desglose del ensemble para transparencia
                    "p_home_ml":       round(p_home_ml, 4),
                    "p_draw_ml":       round(p_draw_ml, 4),
                    "p_away_ml":       round(p_away_ml, 4),
                    "p_home_dc":       round(dc_h, 4) if dc_h is not None else None,
                    "p_draw_dc":       round(dc_d, 4) if dc_d is not None else None,
                    "p_away_dc":       round(dc_a, 4) if dc_a is not None else None,
                    # Consenso multi-casa
                    "consensus_h":     cons_h,
                    "consensus_d":     cons_d,
                    "consensus_a":     cons_a,
                    "n_bookmakers":    n_bks,
                    "consensus_edge":  round(consensus_edge, 4) if consensus_edge is not None else None,
                    "reliability_score": reliability,
                    "risk_light":      risk_light,
                    "no_bet":          no_bet,
                    "bankroll_pct":    round(bankroll_pct, 2),
                    "stake_units":     round(bankroll_pct, 2),
                    "analysis":        (
                        reason if no_bet == "SI"
                        else (
                            f"EV {ev:.2%} | Edge {edge:.2%}"
                            + (f" | ConsEdge {consensus_edge:+.2%}" if consensus_edge is not None else "")
                            + (f" | CLV {clv:+.2%}" if clv is not None else "")
                            + f" | Kelly {bankroll_pct:.2f}%"
                            + (f" | {n_bks}bks" if n_bks > 1 else "")
                        )
                    ),
                })

        return pd.DataFrame(rows)
