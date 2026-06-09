# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
analyzer.py — Pipeline de análisis: backtest walk-forward, Kelly, scoring de riesgo.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np
import pandas as pd

from .config import (
    CLV_MIN, KELLY_CAP, KELLY_FRACTION,
    MAX_OVERROUND_1X2, MAX_OVERROUND_OU, MIN_SAMPLE, MODEL_FILE,
    LEAGUE_TIER, USE_LEAGUE_MODELS,
)
from .consensus import (
    bookmakers_from_api_response, consensus_from_bookmakers,
    edge_vs_consensus, pinnacle_from_bookmakers,
)


def _train_dc_with_timeout(
    dc_model,
    data: pd.DataFrame,
    timeout_secs: int = 15,
    cb: Optional[Callable] = None,
) -> None:
    """
    Entrena el modelo Dixon-Coles en un hilo aparte con timeout.
    Si supera timeout_secs, lo omite y continúa con ML-only.
    """
    done   = threading.Event()
    error  = [None]

    def _worker():
        try:
            dc_model.fit(data)
        except Exception as exc:
            error[0] = exc
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    finished = done.wait(timeout=timeout_secs)

    if not finished:
        logger.warning(
            "Dixon-Coles timeout (%ds) — análisis continúa con ML solo.", timeout_secs
        )
        if cb:
            cb("⚠ Dixon-Coles omitido (timeout) — ML solo activo…")
    elif error[0]:
        logger.warning("Dixon-Coles error: %s", error[0])
        if cb:
            cb("⚠ Dixon-Coles error — ML solo activo…")
    else:
        logger.info("Dixon-Coles completado.")
        if cb:
            cb("Dixon-Coles listo ✓")
from .data import fetch_csv, prepare_fixtures, prepare_historic
from .features import (
    build_feature_row, build_team_long,
    extract_market_features, fair_probs, overround,
)
from .model import FootballModel, FootballModelCollection
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
    roi_std: float = 0.0,
) -> int:
    """
    Puntuación 0-99 de fiabilidad del pick.

    Componentes per-pick (discriminan picks individuales):
      Edge (25 pts)        — principal señal de valor
      Prob vs fair (8 pts) — cuánto supera el modelo al mercado
    Componentes per-división (compartidos por todos los picks de la liga):
      Backtest ROI (12 pts) — historial real de rentabilidad
      Log-loss OOS (8 pts)  — calibración del modelo
    Penalización:
      Volatilidad ROI (7 pts) — reducida vs antes para no aplanar scores
                                 con el backtest puro (que da std más alta)
    """
    import math as _math

    score = 50.0

    # ── Per-pick — curva √ para máxima discriminación ─────────────────────────
    # Curva √: edge 3%→+14  5%→+18  8%→+23  10%→+26  15%→+32  (escala natural)
    e = max(0.0, float(edge or 0))
    score += min(35, _math.sqrt(e) * 90)

    # Diferencial modelo vs mercado (0-8 pts, per pick)
    if model_prob is not None and fair_prob is not None:
        score += max(0, min(8, (float(model_prob) - float(fair_prob)) * 160))

    # ── Per-división ──────────────────────────────────────────────────────────
    score += max(0, min(12, float(bt_roi) * 160))        # ROI backtest (0-12 pts)
    score += max(0, min(8,  (1.15 - float(bt_logloss)) * 20))  # log-loss OOS

    # ── Penalización de inestabilidad (suavizada) ─────────────────────────────
    # pure WF tiene roi_std más alta que pseudo-OOS → penalización proporcional
    score -= max(0, min(7, float(roi_std) * 35))

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
    Walk-forward real con 5 ventanas deslizantes sobre el 40% más reciente del dataset.

    Entrenamiento: primeros 60% datos (el modelo YA ENTRENADO — no re-entrena por ventana).
    Evaluación: 5 ventanas iguales sobre el 40% restante, secuencialmente.

    Retorna todos los campos habituales más:
    - wf_windows:     número de ventanas usadas
    - roi_per_window: lista de ROI por ventana (estabilidad temporal del edge)
    - roi_std:        desviación estándar del ROI entre ventanas (0=muy estable)
    """
    WF_WINDOWS = 5

    n = len(training_df)
    holdout_start = int(n * 0.60)
    holdout_df    = training_df.iloc[holdout_start:].copy()

    holdout_n  = len(holdout_df)
    window_sz  = max(1, holdout_n // WF_WINDOWS)

    profit = bets = wins = 0
    roi_1x2_bets = roi_o25_bets = 0
    roi_1x2_profit = roi_o25_profit = 0.0
    roi_per_window: list[float] = []

    for w in range(WF_WINDOWS):
        w_start = w * window_sz
        w_end   = w_start + window_sz if w < WF_WINDOWS - 1 else holdout_n
        window_df = holdout_df.iloc[w_start:w_end]

        w_profit = 0.0
        w_bets   = 0

        for _, r in window_df.iterrows():
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
                    w_profit += pnl; w_bets += 1
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
                    w_profit += pnl; w_bets += 1
                    roi_o25_bets += 1; roi_o25_profit += pnl

        roi_per_window.append(round(w_profit / w_bets, 4) if w_bets else 0.0)

    roi_std = float(np.std(roi_per_window)) if roi_per_window else 0.0

    return {
        "bets":             bets,
        "profit":           round(profit, 2),
        "roi":              round(profit / bets, 4) if bets else 0.0,
        "hit":              round(wins / bets, 4)   if bets else 0.0,
        "market_1x2_roi":   round(roi_1x2_profit / roi_1x2_bets, 4) if roi_1x2_bets else 0.0,
        "market_o25_roi":   round(roi_o25_profit / roi_o25_bets, 4) if roi_o25_bets else 0.0,
        "eval_samples":     len(holdout_df),
        "wf_windows":       WF_WINDOWS,
        "roi_per_window":   roi_per_window,
        "roi_std":          round(roi_std, 4),
    }


# ── Backtest walk-forward PURO (re-entrena por ventana) ───────────────────────

def run_backtest_pure(
    training_df: pd.DataFrame,
    edge_1x2: float,
    edge_ou: float,
    progress_cb: Optional[Callable] = None,
) -> dict:
    """
    Walk-forward PURO: re-entrena un modelo ligero en cada ventana.
    Garantía: ninguna ventana de test contamina el entrenamiento de esa ventana.

    Usa HistGradientBoostingClassifier sin CalibratedClassifierCV para
    mantener la duración en ~5-15 s adicionales sobre el análisis normal.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    WF_WINDOWS = 5
    MIN_TRAIN  = 150

    df = training_df.dropna(subset=["result"]).copy()
    n  = len(df)

    if n < MIN_TRAIN + 20:
        return {}   # dataset insuficiente → el caller hará fallback

    # Features numéricas del modelo
    feat_cols = [
        c for c in df.columns
        if c.startswith("f_") and pd.api.types.is_numeric_dtype(df[c])
    ]
    if not feat_cols:
        return {}

    # Expanding-window: 55 % train inicial, resto en 5 ventanas de test
    init_train = int(n * 0.55)
    test_total = n - init_train
    window_sz  = max(10, test_total // WF_WINDOWS)

    profit = bets = wins = 0
    roi_1x2_bets = roi_o25_bets = 0
    roi_1x2_profit = roi_o25_profit = 0.0
    roi_per_window: list[float] = []

    for w in range(WF_WINDOWS):
        train_end  = init_train + w * window_sz
        test_start = train_end
        test_end   = test_start + window_sz if w < WF_WINDOWS - 1 else n

        train_w = df.iloc[:train_end]
        test_w  = df.iloc[test_start:test_end]

        if len(train_w) < MIN_TRAIN or test_w.empty:
            roi_per_window.append(0.0)
            continue

        if progress_cb:
            progress_cb(f"⏱ Backtest puro — ventana {w + 1}/{WF_WINDOWS}…")

        X_tr        = train_w[feat_cols]
        y_tr_result = train_w["result"]
        y_tr_over   = train_w["over25"].fillna(0).astype(int)  # fillna antes de cast: NaN → 0

        try:
            clf_1x2 = Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("clf", HistGradientBoostingClassifier(
                    max_iter=80, learning_rate=0.10, max_depth=4,
                    min_samples_leaf=10, random_state=42,
                )),
            ]).fit(X_tr, y_tr_result)

            clf_ov = Pipeline([
                ("imp", SimpleImputer(strategy="median")),
                ("clf", HistGradientBoostingClassifier(
                    max_iter=60, learning_rate=0.10, max_depth=3,
                    min_samples_leaf=10, random_state=42,
                )),
            ]).fit(X_tr, y_tr_over)

        except Exception as exc:
            logger.warning("Pure WF ventana %d error: %s", w, exc)
            roi_per_window.append(0.0)
            continue

        classes_1x2  = clf_1x2.named_steps["clf"].classes_
        col_map      = {c: i for i, c in enumerate(classes_1x2)}
        col_h        = col_map.get("H", 2)
        col_d        = col_map.get("D", 1)
        col_a        = col_map.get("A", 0)

        X_te  = test_w[feat_cols]
        p_1x2 = clf_1x2.predict_proba(X_te)
        # Bug fix: si la ventana de entrenamiento tiene una sola clase (todos Over
        # o todos Under), predict_proba devuelve shape (n,1) y [:, 1] crashea.
        _ov_proba = clf_ov.predict_proba(X_te)
        p_ov  = _ov_proba[:, 1] if _ov_proba.shape[1] > 1 else np.zeros(len(X_te))

        w_profit = 0.0
        w_bets   = 0

        for row_idx, (_, r) in enumerate(test_w.iterrows()):
            p_home = float(p_1x2[row_idx][col_h])
            p_draw = float(p_1x2[row_idx][col_d])
            p_away = float(p_1x2[row_idx][col_a])
            p_over = float(p_ov[row_idx])

            market = None

            if all(pd.notna(r.get(c)) for c in ["B365H", "B365D", "B365A"]):
                fh, fd, fa = fair_probs(
                    float(r["B365H"]), float(r["B365D"]), float(r["B365A"])
                )
                edges = {"1": p_home - fh, "X": p_draw - fd, "2": p_away - fa}
                best  = max(edges, key=edges.get)

                if edges[best] >= edge_1x2:
                    odds = {
                        "1": float(r["B365H"]),
                        "X": float(r["B365D"]),
                        "2": float(r["B365A"]),
                    }[best]
                    won = (
                        (best == "1" and r.get("result") == "H")
                        or (best == "X" and r.get("result") == "D")
                        or (best == "2" and r.get("result") == "A")
                    )
                    pnl = (odds - 1) if won else -1.0
                    profit += pnl; bets += 1; wins += int(won)
                    w_profit += pnl; w_bets += 1
                    roi_1x2_bets += 1; roi_1x2_profit += pnl
                    market = best

            if market is None and pd.notna(r.get("B365O25")) and pd.notna(r.get("B365U25")):
                oi  = 1 / float(r["B365O25"])
                ui  = 1 / float(r["B365U25"])
                ofa = oi / (oi + ui)
                oe  = p_over - ofa

                if oe >= edge_ou:
                    odds = float(r["B365O25"])
                    won  = int(r.get("over25", 0)) == 1
                    pnl  = (odds - 1) if won else -1.0
                    profit += pnl; bets += 1; wins += int(won)
                    w_profit += pnl; w_bets += 1
                    roi_o25_bets += 1; roi_o25_profit += pnl

        roi_per_window.append(round(w_profit / w_bets, 4) if w_bets else 0.0)

    roi_std = float(np.std(roi_per_window)) if roi_per_window else 0.0

    return {
        "bets":           bets,
        "profit":         round(profit, 2),
        "roi":            round(profit / bets, 4) if bets else 0.0,
        "hit":            round(wins / bets, 4)   if bets else 0.0,
        "market_1x2_roi": round(roi_1x2_profit / roi_1x2_bets, 4) if roi_1x2_bets else 0.0,
        "market_o25_roi": round(roi_o25_profit / roi_o25_bets, 4) if roi_o25_bets else 0.0,
        "eval_samples":   bets,
        "wf_windows":     WF_WINDOWS,
        "roi_per_window": roi_per_window,
        "roi_std":        round(roi_std, 4),
        "pure_wf":        True,
    }


# ── Dataset de entrenamiento ───────────────────────────────────────────────────

def build_training_frame(
    hist_by_div: dict[str, pd.DataFrame],
    club_elo=None,
    xg_hist_by_div: dict | None = None,
) -> pd.DataFrame:
    """
    Construye el dataset de entrenamiento con todas las features.

    v14: acepta club_elo (ClubEloModel) y xg_hist_by_div ({div: {team: xg_stats}})
    para enriquecer los datos de entrenamiento. Parámetros opcionales — si son None
    las features correspondientes quedan como NaN (HistGB los ignora correctamente).
    """
    rows = []
    for div, hist_df in hist_by_div.items():
        long_df = build_team_long(hist_df)
        xg_hist = (xg_hist_by_div or {}).get(div, {})
        for i, r in hist_df.iterrows():
            feat = build_feature_row(
                long_df, r.home_team, r.away_team, idx_limit=i,
                hist_df=hist_df,
                match_date=r.get("date"),
                referee=str(r.get("Referee") or ""),
                club_elo=club_elo,
                xg_hist_cache=xg_hist,
            )
            if feat is None:
                continue
            feat.update(extract_market_features(r))
            feat.update({
                "div":           div,
                "f_league_tier": LEAGUE_TIER.get(div, 3),
                "result":        r.result,
                "over25":        r.over25,
                "total_goals":   r.total_goals,
                "B365H":         r.get("B365H"),
                "B365D":         r.get("B365D"),
                "B365A":         r.get("B365A"),
                "B365O25":       r.get("B365O25"),
                "B365U25":       r.get("B365U25"),
            })
            rows.append(feat)
    return pd.DataFrame(rows)


# ── Drift detection ───────────────────────────────────────────────────────────

def detect_model_drift(results_df: pd.DataFrame, backtest_summary: dict):
    """
    Detecta si el modelo está underperforming respecto al backtest histórico.
    Compara el ROI esperado del backtest vs las métricas recientes.
    Returns None si no hay suficientes datos, o dict con info del drift.
    """
    if results_df is None or results_df.empty:
        return None
    if not backtest_summary:
        return None

    # ROI esperado: media de ROIs por liga del backtest
    expected_rois = [d.get("roi", 0) for d in backtest_summary.values() if "roi" in d]
    if not expected_rois:
        return None
    expected_roi = sum(expected_rois) / len(expected_rois)

    # Edge medio de los picks VERDE como proxy del ROI esperado en tiempo real
    if "risk_light" in results_df.columns:
        verde = results_df[results_df["risk_light"] == "VERDE"].copy()
    else:
        verde = pd.DataFrame()

    if verde.empty or "ev" not in verde.columns:
        return None

    current_avg_ev = float(verde["ev"].mean())

    # Drift si el EV actual está muy por debajo del ROI esperado del backtest
    gap = expected_roi - current_avg_ev
    roi_stds = [d.get("roi_std", 0.05) for d in backtest_summary.values() if "roi_std" in d]
    avg_std = sum(roi_stds) / len(roi_stds) if roi_stds else 0.05

    if avg_std > 0 and gap > 2.0 * avg_std:
        return {
            "drift_detected": True,
            "expected_roi": expected_roi,
            "current_ev": current_avg_ev,
            "gap": gap,
            "sigma": gap / avg_std,
            "message": (
                f"⚠️ Model drift detectado: ROI esperado {expected_roi:+.1%} "
                f"vs EV actual {current_avg_ev:+.1%} "
                f"({gap / avg_std:.1f}σ de desviación)"
            ),
        }
    return {
        "drift_detected": False,
        "expected_roi": expected_roi,
        "current_ev": current_avg_ev,
    }


# ── Análisis principal ─────────────────────────────────────────────────────────

class Analyzer:
    def __init__(
        self,
        hist_by_div:    dict[str, pd.DataFrame],
        fixtures_df:    pd.DataFrame,
        claude_api_key: str = "",
    ) -> None:
        self.hist_by_div = {k: prepare_historic(v) for k, v in hist_by_div.items()}
        self.fixtures    = prepare_fixtures(fixtures_df)
        self.model       = FootballModel.load_or_none(MODEL_FILE) or FootballModel()
        self.dc_model    = DixonColesModel()   # Modelo Poisson Dixon-Coles
        self.model_collection: Optional[FootballModelCollection] = None
        self.diagnostics:      list[str] = []
        self.backtest_summary: dict      = {}
        self.drift_info:       dict | None = None

        # Claude feature enricher (opcional — activo solo si hay API key)
        from .claude_enricher import ClaudeFeatureEnricher
        self.claude_enricher: Optional[ClaudeFeatureEnricher] = (
            ClaudeFeatureEnricher(claude_api_key)
            if claude_api_key and claude_api_key.startswith("sk-ant-")
            else None
        )

        # Injury fetcher (opcional — activo solo si hay API key de API-Football)
        self.injury_fetcher = None
        self._injury_api_key: str = ""  # se rellena en run()

    def run(
        self,
        selected_divs:   list[str],
        edge_1x2:        float = 0.03,
        edge_ou:         float = 0.03,
        force_retrain:   bool  = False,
        progress_cb=None,
        injury_api_key:  str   = "",
    ) -> pd.DataFrame:

        def _cb(msg: str) -> None:
            if progress_cb:
                progress_cb(msg)

        # ── Injury fetcher (API-Football) ─────────────────────────────────────
        if injury_api_key:
            from .injuries import InjuryFetcher
            self.injury_fetcher = InjuryFetcher(injury_api_key)
            _cb("🩹 Cargando datos de lesiones (API-Football)…")
        else:
            self.injury_fetcher = None

        # ── Club ELO desde clubelo.com (gratis, ~700 clubs europeos) ─────────
        from .club_elo import ClubEloModel
        club_elo = ClubEloModel()
        _cb("Cargando Club ELO (clubelo.com)…")
        club_elo.load()

        # ── xG histórico temporada anterior de Understat ─────────────────────
        from .understat import fetch_league_xg as _fetch_xg, current_season as _cur_season
        prev_season = _cur_season() - 1
        xg_hist_by_div: dict = {}
        for _div in selected_divs:
            try:
                xg_data = _fetch_xg(_div, prev_season)
                if xg_data:
                    xg_hist_by_div[_div] = xg_data
            except Exception:
                pass
        if xg_hist_by_div:
            _cb(f"xG histórico (Understat {prev_season}): {len(xg_hist_by_div)} ligas")

        _cb("Construyendo dataset de entrenamiento…")
        train_all = build_training_frame(
            self.hist_by_div,
            club_elo=club_elo,
            xg_hist_by_div=xg_hist_by_div,
        )
        if train_all.empty:
            raise ValueError("No se pudo construir el dataset de entrenamiento.")

        # Entrenar ML solo si es necesario
        if force_retrain or not self.model._fitted:
            _cb("⏳ Entrenando modelos ML por primera vez (puede tardar ~1 min)…")
            self.model.fit(train_all, progress_cb=_cb)
            self.model.save(MODEL_FILE)
            _cb("✓ Modelo guardado — próximos análisis serán instantáneos")

        # ── Modelos por liga (opcional) ───────────────────────────────────────
        if USE_LEAGUE_MODELS and (force_retrain or self.model_collection is None):
            try:
                if "div" in train_all.columns:
                    data_by_div = {
                        d: grp for d, grp in train_all.groupby("div")
                    }
                    divs_with_data = sum(
                        1 for grp in data_by_div.values()
                        if len(grp) >= 300  # MIN_ROWS_PER_LEAGUE
                    )
                    if divs_with_data >= 2:
                        _cb("Entrenando modelos por liga…")
                        feature_cols = [
                            c for c in train_all.columns
                            if c.startswith("f_") and pd.api.types.is_numeric_dtype(train_all[c])
                        ]
                        # Renombrar columnas target al formato esperado por FootballModel.fit
                        # (FootballModel.fit usa "result", "over25", "total_goals")
                        # data_by_div ya los tiene con esos nombres — pasamos feature_cols solamente
                        # y construimos el subset correcto dentro de fit_all vía excepción controlada
                        col = FootballModelCollection()
                        # fit_all internamente intenta columnas target_1x2/target_over25/target_goals
                        # que no existen aquí; usamos un wrapper que adapta las columnas reales
                        # construyendo data_by_div_for_fit con los alias correctos
                        data_by_div_for_fit: dict[str, pd.DataFrame] = {}
                        for d, grp in data_by_div.items():
                            g = grp.copy()
                            # Crear aliases esperados por fit_all
                            if "result" in g.columns:
                                g["target_1x2"] = g["result"]
                            if "over25" in g.columns:
                                g["target_over25"] = g["over25"]
                            if "total_goals" in g.columns:
                                g["target_goals"] = g["total_goals"]
                            data_by_div_for_fit[d] = g
                        col.fit_all(data_by_div_for_fit, feature_cols, progress_cb=_cb)
                        if col.global_model is not None or col.models:
                            self.model_collection = col
                            # Persistir en el directorio del modelo global
                            import os
                            model_dir = os.path.dirname(os.path.abspath(MODEL_FILE)) or "."
                            try:
                                col.save_all(model_dir)
                            except Exception as _save_exc:
                                logger.warning("No se pudo guardar FootballModelCollection: %s", _save_exc)
                            logger.info(
                                "FootballModelCollection lista: %d modelos de liga + global",
                                len(col.models),
                            )
                            _cb(f"Modelos por liga: {list(col.models.keys())} + global")
            except Exception as _col_exc:
                logger.warning("Error construyendo FootballModelCollection: %s", _col_exc)
                self.model_collection = None

        # Entrenar Dixon-Coles con timeout (puede ser lento con muchas ligas)
        all_hist = pd.concat(list(self.hist_by_div.values()), ignore_index=True) \
                   if self.hist_by_div else pd.DataFrame()
        if len(all_hist) >= 50:
            _cb("Entrenando Dixon-Coles Poisson…")
            _train_dc_with_timeout(self.dc_model, all_hist, timeout_secs=15, cb=_cb)

        _cb("Generando predicciones…")

        model_type = self.model.metrics.get("model_type", "HistGB")
        base_lrns  = self.model.metrics.get("base_learners", [])
        self.diagnostics = [
            f"Entrenado con {self.model.metrics['train_samples']} muestras",
            f"Modelo: {model_type}"
            + (f" [{', '.join(base_lrns)}]" if base_lrns else ""),
            f"Log-loss OOS (1X2): {self.model.metrics['oos_match_logloss']:.4f}",
            f"Brier OOS (O2.5):   {self.model.metrics['oos_over_brier']:.4f}",
            f"Walk-forward splits: {self.model.metrics['wf_splits']}",
            f"Fixtures cargados:  {len(self.fixtures)}",
        ]
        if self.model_collection is not None:
            self.diagnostics.append(
                f"Modelos por liga: {self.model_collection.trained_divs} "
                f"(global: {'sí' if self.model_collection.global_model else 'no'})"
            )
        if self.injury_fetcher is not None:
            self.diagnostics.append("🩹 API-Football injuries: activo")
        if self.claude_enricher is not None:
            self.diagnostics.append("🤖 Claude enricher: activo (ajuste cualitativo)")

        rows = []
        for div in selected_divs:
            div_train = train_all[train_all["div"] == div].copy()
            bt_source = div_train if len(div_train) > 40 else train_all

            # ── Backtest PURO con fallback a pseudo-OOS ─────────────────────
            bt = run_backtest_pure(bt_source, edge_1x2, edge_ou, progress_cb=_cb)
            if not bt:
                # Datos insuficientes → fallback al método anterior
                bt = run_backtest(self.model, bt_source, edge_1x2, edge_ou)
                bt["pure_wf"] = False

            bt["match_logloss"] = self.model.metrics["oos_match_logloss"]
            self.backtest_summary[div] = bt

            hist_df = self.hist_by_div.get(div)
            if hist_df is None or hist_df.empty:
                continue

            # Añadir flag pure_wf al resultado de backtest
            bt.setdefault("pure_wf", False)

            long_df  = build_team_long(hist_df)
            xg_hist  = xg_hist_by_div.get(div, {})
            fx = self.fixtures[self.fixtures["div"] == div].copy()

            # Pre-importar lineup fetcher (ESPN, sin API key)
            from .lineups import get_lineup_for_match as _get_lineup

            for _, r in fx.iterrows():
                # ── Alineaciones en tiempo real (ESPN, gratis) ────────────────
                _match_date_str = str(r.get("date") or "")[:10]
                _lineup_data    = {}
                if _match_date_str:
                    try:
                        _lineup_data = _get_lineup(
                            r.home_team, r.away_team, _match_date_str
                        )
                    except Exception as _le:
                        logger.debug("ESPN lineup error %s vs %s: %s",
                                     r.home_team, r.away_team, _le)

                feat = build_feature_row(
                    long_df, r.home_team, r.away_team,
                    hist_df=hist_df,
                    match_date=r.get("date"),
                    referee=str(r.get("Referee") or ""),
                    club_elo=club_elo,
                    xg_hist_cache=xg_hist,
                    lineup=_lineup_data,        # ← alineación ESPN conectada
                )
                if feat is None:
                    continue

                feat.update(extract_market_features(r))
                feat["f_league_tier"] = LEAGUE_TIER.get(div, 3)
                feat_row = pd.Series(feat)

                # ── Predicción ML: modelo por liga con fallback al global ──────
                p_home_ml, p_draw_ml, p_away_ml, expected_goals, p_over = \
                    self.model.predict_row(feat_row)
                if self.model_collection is not None:
                    try:
                        _active_model = (
                            self.model_collection.models.get(div)
                            or self.model_collection.global_model
                        )
                        if _active_model is not None:
                            p_home_ml, p_draw_ml, p_away_ml, expected_goals, p_over = \
                                _active_model.predict_row(feat_row)
                    except Exception as _pred_exc:
                        logger.debug(
                            "model_collection.predict_div %s error, usando modelo global: %s",
                            div, _pred_exc,
                        )

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

                # ── Lesiones reales (API-Football) ────────────────────────────
                _injury_home_names: list[str] = []
                _injury_away_names: list[str] = []
                _injury_home_score: float = 0.5
                _injury_away_score: float = 0.5

                if self.injury_fetcher is not None:
                    try:
                        _ih, _injury_home_names = self.injury_fetcher.get_impact(
                            r.home_team, div
                        )
                        _ia, _injury_away_names = self.injury_fetcher.get_impact(
                            r.away_team, div
                        )
                        _injury_home_score = _ih
                        _injury_away_score = _ia
                    except Exception as _inj_exc:
                        logger.debug("InjuryFetcher fixture error: %s", _inj_exc)

                # ── Ajuste cualitativo Claude (si API key disponible) ─────────
                _claude_feats: dict = {}
                if self.claude_enricher is not None:
                    try:
                        _claude_feats = self.claude_enricher.enrich(
                            r.home_team, r.away_team,
                            league=div,
                            existing_feats=feat,
                        )
                    except Exception as _ce_exc:
                        logger.debug("Claude enricher fixture error: %s", _ce_exc)

                # Lesiones reales sobreescriben las estimaciones de Claude
                if self.injury_fetcher is not None:
                    _claude_feats["f_claude_injury_home"] = _injury_home_score
                    _claude_feats["f_claude_injury_away"] = _injury_away_score

                if _claude_feats:
                    try:
                        from .claude_enricher import ClaudeFeatureEnricher as _CE
                        p_home, p_draw, p_away, p_over = _CE.adjust_probabilities(
                            p_home, p_draw, p_away, p_over, _claude_feats
                        )
                    except Exception as _adj_exc:
                        logger.debug("Probability adjustment error: %s", _adj_exc)

                # ── Consenso multi-casa (The Odds API) ────────────────────────
                raw_bks = r.get("_bookmakers_raw", []) or []
                bk_list = bookmakers_from_api_response({
                    "home_team":  r.home_team,
                    "away_team":  r.away_team,
                    "bookmakers": raw_bks,
                })
                consensus_res = consensus_from_bookmakers(bk_list)
                if consensus_res:
                    cons_h, cons_d, cons_a, n_bks = consensus_res
                else:
                    cons_h = cons_d = cons_a = None
                    n_bks  = 0

                # ── Pinnacle como referencia sharp ────────────────────────────
                # Si Pinnacle está disponible en el feed de la API, sus cuotas
                # sin margen (~2%) son una referencia mucho más fiable que B365 (~8%).
                pin_res = pinnacle_from_bookmakers(bk_list)
                # pin_res = (pin_fh, pin_fd, pin_fa) o None

                market       = "NO BET"
                edge         = None
                odds         = None
                model_prob   = None
                fair_prob    = None
                ev           = None
                opening_fair  = None
                closing_fair  = None
                clv           = None
                market_move   = None
                consensus_edge = None
                pinnacle_edge  = None
                sharp_ref      = "b365"   # referencia usada para el edge

                # ── 1X2 ───────────────────────────────────────────────────────
                if all(pd.notna(r.get(c)) for c in ["B365H", "B365D", "B365A"]):
                    # Referencia principal: Pinnacle si disponible, B365 si no
                    if pin_res is not None:
                        # Pinnacle tiene ~2% overround → fair probs reales
                        fh, fd, fa = pin_res
                        sharp_ref  = "pinnacle"
                    else:
                        fh, fd, fa = fair_probs(
                            float(r["B365H"]), float(r["B365D"]), float(r["B365A"])
                        )
                        sharp_ref = "b365"

                    edges = {"1": p_home - fh, "X": p_draw - fd, "2": p_away - fa}
                    best  = max(edges, key=edges.get)

                    # Siempre calcular también el edge vs B365 para comparar
                    b365_fh, b365_fd, b365_fa = fair_probs(
                        float(r["B365H"]), float(r["B365D"]), float(r["B365A"])
                    )
                    b365_edges = {"1": p_home - b365_fh, "X": p_draw - b365_fd, "2": p_away - b365_fa}

                    if edges[best] >= edge_1x2:
                        market     = best
                        edge       = float(edges[best])
                        odds       = {"1": float(r["B365H"]), "X": float(r["B365D"]), "2": float(r["B365A"])}[best]
                        model_prob = {"1": p_home, "X": p_draw, "2": p_away}[best]
                        fair_prob  = {"1": fh, "X": fd, "2": fa}[best]
                        opening_fair = fair_prob
                        ev = model_prob * odds - 1.0

                        # Pinnacle edge (si disponible: la métrica más fiable)
                        if pin_res is not None:
                            pin_map    = {"1": pin_res[0], "X": pin_res[1], "2": pin_res[2]}
                            pinnacle_edge = edge_vs_consensus(model_prob, pin_map[best])

                        # Edge vs consenso multi-casa
                        if cons_h is not None:
                            cons_map = {"1": cons_h, "X": cons_d, "2": cons_a}
                            consensus_edge = edge_vs_consensus(model_prob, cons_map[best])

                        if all(pd.notna(r.get(c)) for c in ["B365CH", "B365CD", "B365CA"]):
                            cp = fair_probs(float(r["B365CH"]), float(r["B365CD"]), float(r["B365CA"]))
                            closing_fair = {"1": cp[0], "X": cp[1], "2": cp[2]}[best]
                            # CLV positivo = apostaste antes de que el mercado te diera
                            # la razón (closing_fair > opening_fair = mercado subió tu lado)
                            clv         = closing_fair - opening_fair
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
                            # CLV positivo = apostaste antes de que el mercado te diera
                            # la razón (closing_fair > opening_fair = mercado subió tu lado)
                            clv         = closing_fair - opening_fair
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

                reliability  = compute_reliability(
                    edge, model_prob, fair_prob,
                    bt.get("roi", 0),
                    bt.get("match_logloss", self.model.metrics["oos_match_logloss"]),
                    roi_std=bt.get("roi_std", 0.0),
                )
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
                    "pinnacle_edge":    round(pinnacle_edge, 4) if pinnacle_edge is not None else None,
                    "sharp_ref":        sharp_ref,
                    # Datos de lesiones (API-Football)
                    "injury_home":      round(_injury_home_score, 2),
                    "injury_away":      round(_injury_away_score, 2),
                    "injuries_home":    ", ".join(_injury_home_names) if _injury_home_names else "",
                    "injuries_away":    ", ".join(_injury_away_names) if _injury_away_names else "",
                    # Alineaciones en tiempo real (ESPN, gratis)
                    "home_formation":   _lineup_data.get("home_formation", ""),
                    "away_formation":   _lineup_data.get("away_formation", ""),
                    "home_lineup":      ", ".join(_lineup_data.get("home_starting", [])[:6]),
                    "away_lineup":      ", ".join(_lineup_data.get("away_starting", [])[:6]),
                    "analysis":        (
                        reason if no_bet == "SI"
                        else (
                            f"EV {ev:.2%} | Edge {edge:.2%}"
                            + (f" [PIN {pinnacle_edge:+.2%}]" if pinnacle_edge is not None else "")
                            + (f" | ConsEdge {consensus_edge:+.2%}" if consensus_edge is not None else "")
                            + (f" | CLV {clv:+.2%}" if clv is not None else "")
                            + f" | Kelly {bankroll_pct:.2f}%"
                            + (f" | {n_bks}bks" if n_bks > 1 else "")
                        )
                    ),
                })

        results_df = pd.DataFrame(rows)

        # ── SHAP top features por pick ────────────────────────────────────────
        try:
            feature_cols = [c for c in results_df.columns if c.startswith("f_")]
            if feature_cols and hasattr(self.model, "compute_shap_top"):
                X_pred = results_df[feature_cols].copy()
                shap_rows = self.model.compute_shap_top(X_pred, n_top=5)
                if shap_rows:
                    results_df["shap_top"] = shap_rows
        except Exception as _e:
            logger.debug("SHAP computation skipped: %s", _e)

        # ── Métricas por liga en backtest_summary ────────────────────────────
        if self.model_collection is not None:
            try:
                for _div, _metrics in self.model_collection.metrics_by_div.items():
                    if _div in self.backtest_summary and _metrics:
                        self.backtest_summary[_div]["league_model_metrics"] = _metrics
            except Exception as _ms_exc:
                logger.debug("Error añadiendo métricas de liga a backtest_summary: %s", _ms_exc)

        # ── Drift detection ───────────────────────────────────────────────────
        self.drift_info = detect_model_drift(results_df, self.backtest_summary)
        if self.drift_info and self.drift_info.get("drift_detected"):
            logger.warning(self.drift_info.get("message", "Model drift detected"))

        return results_df
