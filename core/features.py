"""
features.py — Ingeniería de características: estadísticas de equipo + mercado.

v11 añade:
- Momentum / forma reciente (pts_last3, pts_trend, gf_last3, ga_last3)
- xG proxy a partir de disparos a puerta (shot_accuracy, xg_proxy)
- Head-to-head histórico (h2h_home_win_rate, h2h_avg_goals, h2h_count)
- Diferencias de todas las métricas nuevas (home - away)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import first_existing


# ── Market helpers ─────────────────────────────────────────────────────────────

def fair_probs(h: float, d: float, a: float) -> tuple[float, float, float]:
    """Normaliza las cuotas 1X2 a probabilidades sin margen."""
    inv = np.array([1 / h, 1 / d, 1 / a], dtype=float)
    fair = inv / inv.sum()
    return float(fair[0]), float(fair[1]), float(fair[2])


def overround(*odds: float) -> float:
    vals = [float(o) for o in odds if o is not None and pd.notna(o) and float(o) > 1]
    return sum(1.0 / o for o in vals) if vals else np.nan


def market_entropy(probs: list[float]) -> float:
    p = np.array([x for x in probs if x is not None and pd.notna(x) and x > 0], dtype=float)
    return float(-(p * np.log(p)).sum()) if len(p) else np.nan


def extract_market_features(row: pd.Series) -> dict:
    """Extrae todas las features de mercado de una fila (histórico o fixture)."""
    open_h  = first_existing(row, ["B365H",  "AvgH",  "MaxH"])
    open_d  = first_existing(row, ["B365D",  "AvgD",  "MaxD"])
    open_a  = first_existing(row, ["B365A",  "AvgA",  "MaxA"])
    close_h = first_existing(row, ["B365CH", "AvgCH", "MaxCH"])
    close_d = first_existing(row, ["B365CD", "AvgCD", "MaxCD"])
    close_a = first_existing(row, ["B365CA", "AvgCA", "MaxCA"])
    open_o  = first_existing(row, ["B365O25", "B365>2.5", "Avg>2.5",  "Max>2.5"])
    open_u  = first_existing(row, ["B365U25", "B365<2.5", "Avg<2.5",  "Max<2.5"])
    close_o = first_existing(row, ["B365C>2.5", "AvgC>2.5", "MaxC>2.5"])
    close_u = first_existing(row, ["B365C<2.5", "AvgC<2.5", "MaxC<2.5"])

    out: dict = {}

    if all(pd.notna(x) for x in [open_h, open_d, open_a]):
        fh, fd, fa = fair_probs(float(open_h), float(open_d), float(open_a))
        out.update({
            "m_open_home_prob":  fh,
            "m_open_draw_prob":  fd,
            "m_open_away_prob":  fa,
            "m_open_overround":  overround(open_h, open_d, open_a),
            "m_open_confidence": max(fh, fd, fa),
            "m_open_entropy":    market_entropy([fh, fd, fa]),
            "m_open_h": float(open_h),
            "m_open_d": float(open_d),
            "m_open_a": float(open_a),
        })

    if all(pd.notna(x) for x in [close_h, close_d, close_a]):
        fh, fd, fa = fair_probs(float(close_h), float(close_d), float(close_a))
        out.update({
            "m_close_home_prob":  fh,
            "m_close_draw_prob":  fd,
            "m_close_away_prob":  fa,
            "m_close_overround":  overround(close_h, close_d, close_a),
            "m_close_confidence": max(fh, fd, fa),
            "m_close_entropy":    market_entropy([fh, fd, fa]),
            "m_close_h": float(close_h),
            "m_close_d": float(close_d),
            "m_close_a": float(close_a),
        })

    if pd.notna(open_o) and pd.notna(open_u):
        imp_o = 1 / float(open_o)
        imp_u = 1 / float(open_u)
        fair_o = imp_o / (imp_o + imp_u)
        out.update({
            "m_open_over25_prob":   fair_o,
            "m_open_ou_overround":  overround(open_o, open_u),
            "m_open_o25": float(open_o),
            "m_open_u25": float(open_u),
        })

    if pd.notna(close_o) and pd.notna(close_u):
        imp_o = 1 / float(close_o)
        imp_u = 1 / float(close_u)
        fair_o = imp_o / (imp_o + imp_u)
        out.update({
            "m_close_over25_prob":  fair_o,
            "m_close_ou_overround": overround(close_o, close_u),
            "m_close_o25": float(close_o),
            "m_close_u25": float(close_u),
        })

    if "m_open_home_prob" in out and "m_close_home_prob" in out:
        out["m_delta_home_prob"] = out["m_close_home_prob"] - out["m_open_home_prob"]
        out["m_delta_draw_prob"] = out["m_close_draw_prob"] - out["m_open_draw_prob"]
        out["m_delta_away_prob"] = out["m_close_away_prob"] - out["m_open_away_prob"]

    if "m_open_over25_prob" in out and "m_close_over25_prob" in out:
        out["m_delta_over25_prob"] = out["m_close_over25_prob"] - out["m_open_over25_prob"]

    return out


# ── Team stats ─────────────────────────────────────────────────────────────────

_NAN_KEYS = (
    "pts", "gf", "ga", "goal_diff", "over25", "win_rate",
    "shots", "shots_on", "corners",
    "pts_last3", "pts_trend", "gf_last3", "ga_last3",
    "shot_accuracy", "xg_proxy",
)


def _team_snapshot(team_df: pd.DataFrame) -> dict:
    """Estadísticas generales + forma reciente + xG proxy de un conjunto de partidos."""
    if team_df.empty:
        return {k: np.nan for k in _NAN_KEYS}

    sdf       = team_df.sort_values("idx")
    gf        = float(sdf["gf"].mean())
    ga        = float(sdf["ga"].mean())

    # ── Forma reciente ────────────────────────────────────────────────────────
    n         = len(sdf)
    last3     = sdf.tail(3)
    prev3     = sdf.iloc[max(0, n - 6): max(0, n - 3)]

    pts_last3 = float(last3["pts"].mean()) if len(last3) >= 1 else np.nan
    pts_prev3 = float(prev3["pts"].mean()) if len(prev3) >= 2 else np.nan
    pts_trend = (
        float(pts_last3 - pts_prev3)
        if not np.isnan(pts_last3) and not np.isnan(pts_prev3)
        else np.nan
    )

    # ── Calidad de disparo / xG proxy ─────────────────────────────────────────
    shots    = pd.to_numeric(sdf["shots"],    errors="coerce")
    shots_on = pd.to_numeric(sdf["shots_on"], errors="coerce")
    s_sum    = shots.sum(skipna=True)
    so_sum   = shots_on.sum(skipna=True)
    shot_acc = float(so_sum / s_sum) if s_sum > 0 else np.nan
    # Proxy xG: disparos a puerta × tasa histórica media de gol (~0.35)
    xg_proxy = float(shots_on.mean()) * 0.35 if shots_on.notna().any() else np.nan

    return {
        "pts":       float(sdf["pts"].mean()),
        "gf":        gf,
        "ga":        ga,
        "goal_diff": gf - ga,
        "over25":    float(sdf["over25"].mean()),
        "win_rate":  float((sdf["pts"] == 3).mean()),
        "shots":     float(shots.mean()),
        "shots_on":  float(shots_on.mean()),
        "corners":   float(pd.to_numeric(sdf["corners"], errors="coerce").mean()),
        # Forma reciente
        "pts_last3": pts_last3,
        "pts_trend": pts_trend,
        "gf_last3":  float(last3["gf"].mean()) if len(last3) >= 1 else np.nan,
        "ga_last3":  float(last3["ga"].mean()) if len(last3) >= 1 else np.nan,
        # Calidad de ataque
        "shot_accuracy": shot_acc,
        "xg_proxy":      xg_proxy,
    }


def _h2h_snapshot(
    long_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    idx_limit: int | None = None,
) -> dict:
    """H2H: últimos 5 enfrentamientos directos entre ambos equipos."""
    if "opponent" not in long_df.columns:
        return {"h2h_home_win_rate": np.nan, "h2h_avg_goals": np.nan, "h2h_count": 0}

    mask = (long_df["team"] == home_team) & (long_df["opponent"] == away_team)
    h2h  = long_df[mask].copy()
    if idx_limit is not None:
        h2h = h2h[h2h["idx"] < idx_limit]
    h2h = h2h.sort_values("idx").tail(5)

    if len(h2h) < 2:
        return {"h2h_home_win_rate": np.nan, "h2h_avg_goals": np.nan, "h2h_count": len(h2h)}

    return {
        "h2h_home_win_rate": float((h2h["pts"] == 3).mean()),
        "h2h_avg_goals":     float((h2h["gf"] + h2h["ga"]).mean()),
        "h2h_count":         len(h2h),
    }


def build_team_long(hist_df: pd.DataFrame) -> pd.DataFrame:
    """Convierte el histórico en una tabla larga (una fila por equipo por partido)."""
    recs = []
    for i, r in hist_df.iterrows():
        base = {"idx": i, "over25": r.over25}
        recs.append({
            **base,
            "team": r.home_team, "opponent": r.away_team, "is_home": 1,
            "gf": r.home_goals, "ga": r.away_goals,
            "pts": 3 if r.home_goals > r.away_goals else (1 if r.home_goals == r.away_goals else 0),
            "shots":     first_existing(r, ["HS"]),
            "shots_on":  first_existing(r, ["HST"]),
            "corners":   first_existing(r, ["HC"]),
        })
        recs.append({
            **base,
            "team": r.away_team, "opponent": r.home_team, "is_home": 0,
            "gf": r.away_goals, "ga": r.home_goals,
            "pts": 3 if r.away_goals > r.home_goals else (1 if r.home_goals == r.away_goals else 0),
            "shots":     first_existing(r, ["AS"]),
            "shots_on":  first_existing(r, ["AST"]),
            "corners":   first_existing(r, ["AC"]),
        })

    long_df = pd.DataFrame(recs)
    for col in ["shots", "shots_on", "corners"]:
        long_df[col] = pd.to_numeric(long_df[col], errors="coerce")
    return long_df


def build_feature_row(
    long_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    idx_limit: int | None = None,
) -> dict | None:
    """
    Construye una fila de features para un partido.

    idx_limit evita look-ahead bias: solo usa partidos ANTERIORES al índice dado.
    """
    h = long_df[long_df["team"] == home_team].copy()
    a = long_df[long_df["team"] == away_team].copy()

    if idx_limit is not None:
        h = h[h["idx"] < idx_limit]
        a = a[a["idx"] < idx_limit]

    h_all = h.sort_values("idx").tail(10)
    a_all = a.sort_values("idx").tail(10)

    if len(h_all) < 5 or len(a_all) < 5:
        return None

    h_home = h[h["is_home"] == 1].sort_values("idx").tail(5)
    a_away = a[a["is_home"] == 0].sort_values("idx").tail(5)

    hs  = _team_snapshot(h_all)
    aws = _team_snapshot(a_all)
    hhs = _team_snapshot(h_home if not h_home.empty else h_all)
    aas = _team_snapshot(a_away if not a_away.empty else a_all)

    row: dict = {
        # ── Home general ─────────────────────────────────────────────────────
        "f_home_pts":        hs["pts"],
        "f_home_gf":         hs["gf"],
        "f_home_ga":         hs["ga"],
        "f_home_goal_diff":  hs["goal_diff"],
        "f_home_over25":     hs["over25"],
        "f_home_win_rate":   hs["win_rate"],
        "f_home_shots":      hs["shots"],
        "f_home_shots_on":   hs["shots_on"],
        "f_home_corners":    hs["corners"],
        # Forma reciente (home)
        "f_home_pts_last3":  hs["pts_last3"],
        "f_home_pts_trend":  hs["pts_trend"],
        "f_home_gf_last3":   hs["gf_last3"],
        "f_home_ga_last3":   hs["ga_last3"],
        "f_home_shot_acc":   hs["shot_accuracy"],
        "f_home_xg_proxy":   hs["xg_proxy"],
        # Home as home
        "f_home_home_pts":   hhs["pts"],
        "f_home_home_gf":    hhs["gf"],
        "f_home_home_ga":    hhs["ga"],
        # ── Away general ─────────────────────────────────────────────────────
        "f_away_pts":        aws["pts"],
        "f_away_gf":         aws["gf"],
        "f_away_ga":         aws["ga"],
        "f_away_goal_diff":  aws["goal_diff"],
        "f_away_over25":     aws["over25"],
        "f_away_win_rate":   aws["win_rate"],
        "f_away_shots":      aws["shots"],
        "f_away_shots_on":   aws["shots_on"],
        "f_away_corners":    aws["corners"],
        # Forma reciente (away)
        "f_away_pts_last3":  aws["pts_last3"],
        "f_away_pts_trend":  aws["pts_trend"],
        "f_away_gf_last3":   aws["gf_last3"],
        "f_away_ga_last3":   aws["ga_last3"],
        "f_away_shot_acc":   aws["shot_accuracy"],
        "f_away_xg_proxy":   aws["xg_proxy"],
        # Away as away
        "f_away_away_pts":   aas["pts"],
        "f_away_away_gf":    aas["gf"],
        "f_away_away_ga":    aas["ga"],
        # ── Meta ─────────────────────────────────────────────────────────────
        "f_sample_min": min(len(h_all), len(a_all)),
    }

    # ── Diferencias home − away ───────────────────────────────────────────────
    for metric in [
        "pts", "gf", "ga", "goal_diff", "over25", "win_rate",
        "shots", "shots_on", "corners",
        "pts_last3", "pts_trend", "gf_last3", "ga_last3",
        "shot_acc", "xg_proxy",
    ]:
        h_val = row.get(f"f_home_{metric}", np.nan)
        a_val = row.get(f"f_away_{metric}", np.nan)
        row[f"f_diff_{metric}"] = (
            float(h_val - a_val)
            if pd.notna(h_val) and pd.notna(a_val)
            else np.nan
        )

    # ── Head-to-head ──────────────────────────────────────────────────────────
    h2h = _h2h_snapshot(long_df, home_team, away_team, idx_limit)
    row["f_h2h_home_win_rate"] = h2h["h2h_home_win_rate"]
    row["f_h2h_avg_goals"]     = h2h["h2h_avg_goals"]
    row["f_h2h_count"]         = float(h2h["h2h_count"])

    return row
