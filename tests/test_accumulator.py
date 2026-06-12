# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_accumulator.py — Tests del motor de combinadas.

Cubre invariantes estables (independientes de calibración o política de
selección): Kelly, correlación entre legs, probabilidad y EV combinados,
y exclusión de legs del mismo partido.

Ejecutar:  pytest tests/test_accumulator.py -v
"""

import numpy as np
import pandas as pd

from football_analyzer.core.accumulator import (
    build_smart_accumulators, build_recommended_combo,
    kelly_fraction, _make_extended_selections, _cal,
    _rho_estimate, _legs_correlation_info,
)
from football_analyzer.core.prob_calibrator import fit_from_picks


def _match(home, away, ph, pdr, pa, po, league="E0", date="2026-05-10"):
    """Una fila de partido con probabilidades del modelo y cuotas B365."""
    return {
        "home_team": home, "away_team": away, "league": league, "div": league,
        "date": date, "no_bet": "NO",
        "p_home": ph, "p_draw": pdr, "p_away": pa, "p_over25": po,
        "reliability_score": 60,
        "B365H": 2.00, "B365D": 3.40, "B365A": 3.80,
        "B365O25": 1.90, "B365U25": 1.90,
        # campos del fallback (no imprescindibles si hay selecciones)
        "odds": 2.00, "model_prob": ph, "edge": 0.05,
    }


def _sample_df():
    return pd.DataFrame([
        _match("Arsenal",   "Brentford", 0.55, 0.25, 0.20, 0.55),
        _match("Madrid",    "Cadiz",     0.58, 0.24, 0.18, 0.52),
        _match("Bayern",    "Bochum",    0.60, 0.22, 0.18, 0.57),
        _match("Liverpool", "Burnley",   0.57, 0.25, 0.18, 0.54),
    ])


# ── kelly_fraction ───────────────────────────────────────────────────────────────

class TestKelly:
    def test_positive_ev(self):
        # p=0.6 a cuota 2.0 → EV positivo → fracción > 0
        assert kelly_fraction(0.60, 2.0) > 0

    def test_negative_ev_zero(self):
        # p=0.4 a cuota 2.0 → EV negativo → 0
        assert kelly_fraction(0.40, 2.0) == 0.0

    def test_cap(self):
        # Nunca supera el techo (max_kelly por defecto 0.05)
        assert kelly_fraction(0.95, 5.0) <= 0.05

    def test_invalid(self):
        assert kelly_fraction(0.6, 1.0) == 0.0      # cuota 1 → b=0
        assert kelly_fraction(0.0, 2.0) == 0.0
        assert kelly_fraction(1.0, 2.0) == 0.0


# ── Correlación entre legs ───────────────────────────────────────────────────────

class TestCorrelation:
    def test_same_league_and_date(self):
        a = {"league": "E0", "date": "2026-05-10"}
        b = {"league": "E0", "date": "2026-05-10"}
        assert _rho_estimate(a, b) == 0.15

    def test_same_league_diff_date(self):
        a = {"league": "E0", "date": "2026-05-10"}
        b = {"league": "E0", "date": "2026-05-17"}
        assert _rho_estimate(a, b) == 0.08

    def test_diff_league(self):
        a = {"league": "E0", "date": "2026-05-10"}
        b = {"league": "SP1", "date": "2026-05-10"}
        assert _rho_estimate(a, b) == 0.0

    def test_correlation_info_ranges(self):
        legs = [
            {"league": "E0", "date": "2026-05-10", "model_prob": 0.6},
            {"league": "E0", "date": "2026-05-10", "model_prob": 0.6},
        ]
        info = _legs_correlation_info(legs)
        assert 0.85 <= info["prob_factor"] <= 1.20      # acotado
        assert 0.50 <= info["kelly_factor"] <= 1.0
        assert info["n_corr_pairs"] == 1


# ── _make_extended_selections ────────────────────────────────────────────────────

class TestSelections:
    def test_generates_selections(self):
        sel = _make_extended_selections(_sample_df())
        assert not sel.empty
        # debe haber al menos un mercado de cada tipo posible
        assert set(sel["market_type"]).issubset({"1X2", "double_chance", "goals"})
        # toda selección con edge >= mínimo
        assert (sel["edge"] >= 0.0).all()

    def test_probabilities_capped(self):
        sel = _make_extended_selections(_sample_df())
        # ningún model_prob por encima de los caps honestos
        assert sel["model_prob"].max() <= 0.88


# ── build_smart_accumulators (invariantes por combinada) ─────────────────────────

class TestSmartAccumulators:
    def test_returns_combos(self):
        combos = build_smart_accumulators(_sample_df(), min_legs=2, max_legs=3)
        assert len(combos) >= 1

    def test_invariants(self):
        for c in build_smart_accumulators(_sample_df(), min_legs=2, max_legs=3):
            legs = c["legs"]
            # cuota combinada = producto de cuotas
            prod_odds = float(np.prod([float(l["odds"]) for l in legs]))
            assert abs(c["combined_odds"] - round(prod_odds, 2)) < 0.02
            # prob combinada = producto de probs × factor de correlación
            prod_prob = float(np.prod([float(l["model_prob"]) for l in legs]))
            expect_prob = round(prod_prob * c["corr_info"]["prob_factor"], 4)
            assert abs(c["combined_prob"] - expect_prob) < 1e-3
            # EV = prob · cuota − 1 (tolerancia 0.01: la cuota combinada se
            # guarda redondeada a 2 decimales, el ev se calcula sin redondear)
            assert abs(c["ev"] - (c["combined_prob"] * c["combined_odds"] - 1.0)) < 0.01

    def test_no_duplicate_match(self):
        for c in build_smart_accumulators(_sample_df(), min_legs=2, max_legs=4):
            keys = [f"{l.get('home_team')}::{l.get('away_team')}" for l in c["legs"]]
            assert len(set(keys)) == len(keys)   # sin dos legs del mismo partido


# ── build_recommended_combo ──────────────────────────────────────────────────────

class TestRecommended:
    def test_odds_in_range(self):
        rec = build_recommended_combo(_sample_df(), target_min_odds=1.40, target_max_odds=2.20)
        if rec is not None:                       # puede no haber combo en rango
            assert 1.40 <= rec["combined_odds"] <= 2.20
            assert rec["n_legs"] == 2


# ── Calibración de probabilidades en las combinadas ──────────────────────────────

def _overconfident_calibrator():
    """Calibrador ajustado a un modelo OPTIMISTA (dice 0.6/0.8 pero gana 0.4/0.6)."""
    picks = (
        [{"model_prob": 0.6, "status": "LOSS"} for _ in range(30)]
        + [{"model_prob": 0.6, "status": "WIN"} for _ in range(20)]
        + [{"model_prob": 0.8, "status": "WIN"} for _ in range(30)]
        + [{"model_prob": 0.8, "status": "LOSS"} for _ in range(20)]
    )
    return fit_from_picks(picks, min_samples=50)


class TestCalibration:
    def test_helper(self):
        cal = _overconfident_calibrator()
        assert cal.is_fitted
        assert _cal(0.80, cal) < 0.80          # corrige a la baja
        assert _cal(0.80, None) == 0.80        # sin calibrador → identidad

    def test_lowers_combo_probabilities(self):
        cal = _overconfident_calibrator()
        raw   = _make_extended_selections(_sample_df())
        calib = _make_extended_selections(_sample_df(), prob_calibrator=cal)
        assert not calib.empty
        # con un modelo optimista, la prob máxima calibrada es menor que la cruda
        assert calib["model_prob"].max() < raw["model_prob"].max()

    def test_no_calibrator_identical(self):
        a = _make_extended_selections(_sample_df())
        b = _make_extended_selections(_sample_df(), prob_calibrator=None)
        assert list(a["model_prob"]) == list(b["model_prob"])
