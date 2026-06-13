# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
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
    # v12 — decay + xG quality + clean sheets + BTTS
    "pts_w", "gf_w", "ga_w",
    "pts_last5", "gf_last5", "ga_last5",
    "xg_quality",
    "clean_sheet_rate",
    "btts_rate",
    "scoring_eff",
    # v14 — rachas consecutivas
    "win_streak", "loss_streak", "unbeaten",
)


def _count_streak(pts_list: list, target_pts: int) -> int:
    """Cuenta partidos consecutivos con `target_pts` al final de la serie."""
    count = 0
    for p in reversed(pts_list):
        if p == target_pts:
            count += 1
        else:
            break
    return count


def _count_unbeaten(pts_list: list) -> int:
    """Cuenta partidos consecutivos sin perder al final de la serie."""
    count = 0
    for p in reversed(pts_list):
        if p > 0:
            count += 1
        else:
            break
    return count


def _team_snapshot(team_df: pd.DataFrame, decay_halflife: int = 7) -> dict:
    """
    Estadísticas generales + forma reciente con decay exponencial + métricas de calidad.

    decay_halflife=7: un partido jugado hace 7 juegos pesa el 50% de uno de hoy.
    Esto es más honesto que promedios simples — la forma reciente importa más.
    """
    if team_df.empty:
        return {k: np.nan for k in _NAN_KEYS}

    sdf = team_df.sort_values("idx")
    n   = len(sdf)
    gf  = float(sdf["gf"].mean())
    ga  = float(sdf["ga"].mean())

    # ── Decay exponencial ─────────────────────────────────────────────────────
    # Peso del partido más reciente = 1, hace 7 juegos = 0.5, hace 14 = 0.25
    ages    = np.arange(n - 1, -1, -1).astype(float)  # 0 = más reciente
    w       = np.exp(-ages * np.log(2) / decay_halflife)
    w       = w / w.sum()                              # normalizar a suma 1
    pts_arr = sdf["pts"].fillna(0).values
    gf_arr  = sdf["gf"].fillna(0).values
    ga_arr  = sdf["ga"].fillna(0).values
    pts_w   = float(np.dot(w, pts_arr))
    gf_w    = float(np.dot(w, gf_arr))
    ga_w    = float(np.dot(w, ga_arr))

    # ── Forma reciente — ventanas 3 y 5 ──────────────────────────────────────
    last3 = sdf.tail(3)
    last5 = sdf.tail(5)
    prev3 = sdf.iloc[max(0, n - 6): max(0, n - 3)]

    pts_last3 = float(last3["pts"].mean()) if len(last3) >= 1 else np.nan
    pts_prev3 = float(prev3["pts"].mean()) if len(prev3) >= 2 else np.nan
    pts_trend = (
        float(pts_last3 - pts_prev3)
        if not np.isnan(pts_last3) and not np.isnan(pts_prev3)
        else np.nan
    )

    # ── Calidad de disparo / xG mejorado ─────────────────────────────────────
    shots    = pd.to_numeric(sdf["shots"],    errors="coerce")
    shots_on = pd.to_numeric(sdf["shots_on"], errors="coerce")
    corners  = pd.to_numeric(sdf["corners"],  errors="coerce")

    s_sum  = shots.sum(skipna=True)
    so_sum = shots_on.sum(skipna=True)
    shot_acc = float(so_sum / s_sum) if s_sum > 0 else np.nan

    # xg_proxy clásico (backward compatible)
    xg_proxy = float(shots_on.mean()) * 0.35 if shots_on.notna().any() else np.nan

    # xg_quality: SOT×0.33 + shots_off×0.05 + corners×0.02
    # Mucho más preciso — distingue la calidad de las ocasiones
    shots_off = (shots.fillna(0) - shots_on.fillna(0)).clip(lower=0)
    xg_quality = float(
        (shots_on.fillna(0) * 0.33
         + shots_off * 0.05
         + corners.fillna(0) * 0.02).mean()
    ) if shots.notna().any() else np.nan

    # Eficiencia goleadora: goles / disparos a puerta (calibra la puntería real)
    scoring_eff = float(sdf["gf"].sum() / so_sum) if so_sum > 0 else np.nan

    # ── Métricas defensivas y de patrón de gol ────────────────────────────────
    clean_sheet_rate = float((sdf["ga"] == 0).mean())
    btts_rate        = float(((sdf["gf"] > 0) & (sdf["ga"] > 0)).mean())

    # ── Rachas consecutivas ───────────────────────────────────────────────────
    pts_list    = sdf.sort_values("idx")["pts"].fillna(0).tolist()
    win_streak  = _count_streak(pts_list, 3)
    loss_streak = _count_streak(pts_list, 0)
    unbeaten    = _count_unbeaten(pts_list)

    return {
        "pts":       float(sdf["pts"].mean()),
        "gf":        gf,
        "ga":        ga,
        "goal_diff": gf - ga,
        "over25":    float(sdf["over25"].mean()),
        "win_rate":  float((sdf["pts"] == 3).mean()),
        "shots":     float(shots.mean()) if shots.notna().any() else np.nan,
        "shots_on":  float(shots_on.mean()) if shots_on.notna().any() else np.nan,
        "corners":   float(corners.mean()) if corners.notna().any() else np.nan,
        # Forma reciente (ventanas 3 y 5)
        "pts_last3":  pts_last3,
        "pts_trend":  pts_trend,
        "gf_last3":   float(last3["gf"].mean()) if len(last3) >= 1 else np.nan,
        "ga_last3":   float(last3["ga"].mean()) if len(last3) >= 1 else np.nan,
        "pts_last5":  float(last5["pts"].mean()) if len(last5) >= 3 else np.nan,
        "gf_last5":   float(last5["gf"].mean()) if len(last5) >= 3 else np.nan,
        "ga_last5":   float(last5["ga"].mean()) if len(last5) >= 3 else np.nan,
        # Forma con decay (más honesta que promedios simples)
        "pts_w": pts_w,
        "gf_w":  gf_w,
        "ga_w":  ga_w,
        # Calidad de ataque
        "shot_accuracy":  shot_acc,
        "xg_proxy":       xg_proxy,
        "xg_quality":     xg_quality,
        "scoring_eff":    scoring_eff,
        # Patrón defensivo / goleador
        "clean_sheet_rate": clean_sheet_rate,
        "btts_rate":        btts_rate,
        # Rachas (v14)
        "win_streak":  win_streak,
        "loss_streak": loss_streak,
        "unbeaten":    unbeaten,
    }


def _h2h_snapshot(
    long_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    idx_limit: int | None = None,
) -> dict:
    """
    H2H: últimos 6 enfrentamientos directos entre ambos equipos.
    Añade goal_diff y last_result para dar más señal al modelo.
    """
    _empty = {
        "h2h_home_win_rate": np.nan, "h2h_avg_goals": np.nan,
        "h2h_count": 0, "h2h_goal_diff": np.nan, "h2h_last_result": np.nan,
    }
    if "opponent" not in long_df.columns:
        return _empty

    mask = (long_df["team"] == home_team) & (long_df["opponent"] == away_team)
    h2h  = long_df[mask].copy()
    if idx_limit is not None:
        h2h = h2h[h2h["idx"] < idx_limit]
    h2h = h2h.sort_values("idx").tail(6)  # últimos 6 (antes 5)

    if len(h2h) < 2:
        return {**_empty, "h2h_count": len(h2h)}

    # Último resultado: 1.0 = victoria local, 0.5 = empate, 0.0 = derrota local
    last_pts = h2h.iloc[-1]["pts"]
    last_result = 1.0 if last_pts == 3 else (0.5 if last_pts == 1 else 0.0)

    return {
        "h2h_home_win_rate": float((h2h["pts"] == 3).mean()),
        "h2h_avg_goals":     float((h2h["gf"] + h2h["ga"]).mean()),
        "h2h_count":         len(h2h),
        "h2h_goal_diff":     float((h2h["gf"] - h2h["ga"]).mean()),  # NEW: dominio histórico
        "h2h_last_result":   float(last_result),                      # NEW: inercia reciente
    }


def build_team_long(hist_df: pd.DataFrame) -> pd.DataFrame:
    """Convierte el histórico en una tabla larga (una fila por equipo por partido)."""
    recs = []
    for i, r in hist_df.iterrows():
        date_val = r.get("date") if "date" in r.index else None
        base = {"idx": i, "over25": r.over25, "date": date_val}
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


# ── Nuevas funciones auxiliares (v14) ─────────────────────────────────────────

def _rest_days(
    team: str,
    match_date,
    long_df: pd.DataFrame,
    idx_limit: int | None = None,
) -> float:
    """Días desde el último partido del equipo (feature de fatiga/frescura)."""
    if match_date is None or "date" not in long_df.columns:
        return np.nan
    team_matches = long_df[long_df["team"] == team].copy()
    if idx_limit is not None:
        team_matches = team_matches[team_matches["idx"] < idx_limit]
    team_matches = team_matches.dropna(subset=["date"]).sort_values("date")
    if team_matches.empty:
        return np.nan
    last_date = team_matches.iloc[-1]["date"]
    try:
        delta = match_date - last_date
        return float(delta.days)
    except Exception:
        return np.nan


def _referee_stats(
    referee: str | None,
    hist_df: pd.DataFrame | None,
    idx_limit: int | None = None,
) -> dict:
    """Tendencias históricas del árbitro: tarjetas, sesgo local, goles."""
    empty = {
        "f_ref_yellows_pg":   np.nan,
        "f_ref_reds_pg":      np.nan,
        "f_ref_home_win_pct": np.nan,
        "f_ref_over25_pct":   np.nan,
    }
    if not referee or hist_df is None or "Referee" not in hist_df.columns:
        return empty
    ref_df = hist_df[hist_df["Referee"] == referee].copy()
    if idx_limit is not None:
        ref_df = ref_df[ref_df.index < idx_limit]
    if len(ref_df) < 5:
        return empty

    def _avg(*cols) -> float:
        vals = [
            ref_df[c].astype(float)
            for c in cols if c in ref_df.columns
        ]
        if not vals:
            return np.nan
        combined = sum(v.fillna(0) for v in vals)
        return float(combined.mean())

    yellows_pg   = _avg("HY", "AY")
    reds_pg      = _avg("HR", "AR")
    home_win_pct = float((ref_df["result"] == "H").mean()) if "result" in ref_df.columns else np.nan
    over25_pct   = float(ref_df["over25"].mean())          if "over25" in ref_df.columns else np.nan

    return {
        "f_ref_yellows_pg":   yellows_pg,
        "f_ref_reds_pg":      reds_pg,
        "f_ref_home_win_pct": home_win_pct,
        "f_ref_over25_pct":   over25_pct,
    }


def _elo_features(home_team: str, away_team: str, club_elo) -> dict:
    """Club ELO desde clubelo.com como features del modelo."""
    empty = {
        "f_elo_home":      np.nan,
        "f_elo_away":      np.nan,
        "f_elo_diff":      np.nan,
        "f_elo_prob_home": np.nan,
        "f_elo_prob_away": np.nan,
    }
    if club_elo is None or not club_elo.is_ready():
        return empty
    elo_h = club_elo.get_elo(home_team)
    elo_a = club_elo.get_elo(away_team)
    pred  = club_elo.predict(home_team, away_team)
    return {
        "f_elo_home":      float(elo_h) if elo_h is not None else np.nan,
        "f_elo_away":      float(elo_a) if elo_a is not None else np.nan,
        # Bug fix: usar "is not None" en vez de truthiness — ELO=0 es válido
        "f_elo_diff":      float(elo_h - elo_a) if (elo_h is not None and elo_a is not None) else np.nan,
        "f_elo_prob_home": float(pred[0]) if pred else np.nan,
        "f_elo_prob_away": float(pred[2]) if pred else np.nan,
    }


def _xg_hist_features(
    home_team: str,
    away_team: str,
    xg_hist_cache: dict | None,
) -> dict:
    """xG medio de la temporada anterior (Understat) como feature del modelo."""
    empty = {
        "f_home_xg_hist":  np.nan,
        "f_home_xga_hist": np.nan,
        "f_away_xg_hist":  np.nan,
        "f_away_xga_hist": np.nan,
        "f_diff_xg_hist":  np.nan,
    }
    if not xg_hist_cache:
        return empty
    from .understat import get_team_xg
    h = get_team_xg(home_team, xg_hist_cache)
    a = get_team_xg(away_team, xg_hist_cache)
    h_xg  = h["xg"]  if h else np.nan
    h_xga = h["xga"] if h else np.nan
    a_xg  = a["xg"]  if a else np.nan
    a_xga = a["xga"] if a else np.nan
    diff  = float(h_xg - a_xg) if pd.notna(h_xg) and pd.notna(a_xg) else np.nan
    return {
        "f_home_xg_hist":  h_xg,
        "f_home_xga_hist": h_xga,
        "f_away_xg_hist":  a_xg,
        "f_away_xga_hist": a_xga,
        "f_diff_xg_hist":  diff,
    }


def build_feature_row(
    long_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    idx_limit: int | None = None,
    # v14: nuevos parámetros opcionales — todos con default None (backward-compatible)
    hist_df: pd.DataFrame | None = None,
    match_date=None,
    referee: str | None = None,
    club_elo=None,
    xg_hist_cache: dict | None = None,
    # v15: features meteorológicas (opcional, backward-compatible)
    weather: dict | None = None,
    # v16: features de alineación pre-partido (opcional, backward-compatible)
    lineup: dict | None = None,
) -> dict | None:
    """
    Construye una fila de features para un partido.

    idx_limit evita look-ahead bias: solo usa partidos ANTERIORES al índice dado.
    Los parámetros v14 son todos opcionales: el modelo funciona con NaN cuando faltan.
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
        # Forma reciente (3 y 5 partidos)
        "f_home_pts_last3":  hs["pts_last3"],
        "f_home_pts_trend":  hs["pts_trend"],
        "f_home_gf_last3":   hs["gf_last3"],
        "f_home_ga_last3":   hs["ga_last3"],
        "f_home_pts_last5":  hs["pts_last5"],
        "f_home_gf_last5":   hs["gf_last5"],
        "f_home_ga_last5":   hs["ga_last5"],
        # Forma con decay exponencial (v12)
        "f_home_pts_w":      hs["pts_w"],
        "f_home_gf_w":       hs["gf_w"],
        "f_home_ga_w":       hs["ga_w"],
        # Calidad de ataque
        "f_home_shot_acc":   hs["shot_accuracy"],
        "f_home_xg_proxy":   hs["xg_proxy"],
        "f_home_xg_quality": hs["xg_quality"],
        "f_home_scoring_eff":hs["scoring_eff"],
        # Patrón defensivo
        "f_home_clean_sheet":hs["clean_sheet_rate"],
        "f_home_btts":       hs["btts_rate"],
        # Home as home
        "f_home_home_pts":   hhs["pts"],
        "f_home_home_gf":    hhs["gf"],
        "f_home_home_ga":    hhs["ga"],
        "f_home_home_pts_w": hhs["pts_w"],
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
        # Forma reciente (3 y 5 partidos)
        "f_away_pts_last3":  aws["pts_last3"],
        "f_away_pts_trend":  aws["pts_trend"],
        "f_away_gf_last3":   aws["gf_last3"],
        "f_away_ga_last3":   aws["ga_last3"],
        "f_away_pts_last5":  aws["pts_last5"],
        "f_away_gf_last5":   aws["gf_last5"],
        "f_away_ga_last5":   aws["ga_last5"],
        # Forma con decay exponencial (v12)
        "f_away_pts_w":      aws["pts_w"],
        "f_away_gf_w":       aws["gf_w"],
        "f_away_ga_w":       aws["ga_w"],
        # Calidad de ataque
        "f_away_shot_acc":   aws["shot_accuracy"],
        "f_away_xg_proxy":   aws["xg_proxy"],
        "f_away_xg_quality": aws["xg_quality"],
        "f_away_scoring_eff":aws["scoring_eff"],
        # Patrón defensivo
        "f_away_clean_sheet":aws["clean_sheet_rate"],
        "f_away_btts":       aws["btts_rate"],
        # Away as away
        "f_away_away_pts":   aas["pts"],
        "f_away_away_gf":    aas["gf"],
        "f_away_away_ga":    aas["ga"],
        "f_away_away_pts_w": aas["pts_w"],
        # ── Rachas consecutivas (v14) ─────────────────────────────────────────
        "f_home_win_streak":  hs["win_streak"],
        "f_home_loss_streak": hs["loss_streak"],
        "f_home_unbeaten":    hs["unbeaten"],
        "f_away_win_streak":  aws["win_streak"],
        "f_away_loss_streak": aws["loss_streak"],
        "f_away_unbeaten":    aws["unbeaten"],
        # ── Meta ─────────────────────────────────────────────────────────────
        "f_sample_min": min(len(h_all), len(a_all)),
    }

    # ── Días de descanso (v14) ────────────────────────────────────────────────
    row["f_home_rest_days"] = _rest_days(home_team, match_date, long_df, idx_limit)
    row["f_away_rest_days"] = _rest_days(away_team, match_date, long_df, idx_limit)
    h_rd = row["f_home_rest_days"]
    a_rd = row["f_away_rest_days"]
    row["f_diff_rest_days"] = (
        float(h_rd - a_rd) if pd.notna(h_rd) and pd.notna(a_rd) else np.nan
    )
    # Ventaja de descanso (flag binario: local descansa ≥3 días más)
    row["f_rest_advantage"] = (
        1.0 if (pd.notna(row["f_diff_rest_days"]) and row["f_diff_rest_days"] >= 3) else
        (-1.0 if (pd.notna(row["f_diff_rest_days"]) and row["f_diff_rest_days"] <= -3) else 0.0)
    )

    # ── Club ELO (v14) ────────────────────────────────────────────────────────
    row.update(_elo_features(home_team, away_team, club_elo))

    # ── xG histórico temporada anterior (v14) ─────────────────────────────────
    row.update(_xg_hist_features(home_team, away_team, xg_hist_cache))

    # ── Tendencias del árbitro (v14) ──────────────────────────────────────────
    row.update(_referee_stats(referee, hist_df, idx_limit))

    # ── Diferencias home − away ───────────────────────────────────────────────
    for metric in [
        "pts", "gf", "ga", "goal_diff", "over25", "win_rate",
        "shots", "shots_on", "corners",
        "pts_last3", "pts_trend", "gf_last3", "ga_last3",
        "pts_last5", "gf_last5", "ga_last5",
        "pts_w", "gf_w", "ga_w",
        "shot_acc", "xg_proxy", "xg_quality", "scoring_eff",
        "clean_sheet", "btts",
        "win_streak", "loss_streak", "unbeaten",
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
    row["f_h2h_goal_diff"]     = h2h["h2h_goal_diff"]    # NEW
    row["f_h2h_last_result"]   = h2h["h2h_last_result"]  # NEW

    # ── Weather features (v15) ────────────────────────────────────────────────
    # 0/default cuando no hay datos — backward-compatible con todos los callers
    row["f_rain_mm"]     = float(weather.get("rain_mm", 0))          if weather else 0.0
    row["f_wind_kmh"]    = float(weather.get("wind_kmh", 0))         if weather else 0.0
    row["f_temp_c"]      = float(weather.get("temp_c", 15))          if weather else 15.0
    row["f_bad_weather"] = int(weather.get("is_bad_weather", False))  if weather else 0

    # ── Lineup features (v16) ─────────────────────────────────────────────────
    # 0 cuando no hay datos de alineación — backward-compatible con todos los callers
    row["f_home_missing_starters"] = int(lineup.get("home_missing", 0)) if lineup else 0
    row["f_away_missing_starters"] = int(lineup.get("away_missing", 0)) if lineup else 0
    row["f_lineup_diff_missing"]   = (
        row["f_home_missing_starters"] - row["f_away_missing_starters"]
    )

    return row
