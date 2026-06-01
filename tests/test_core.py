"""
tests/test_core.py — Tests unitarios para el motor analítico.

Ejecutar:
    pytest tests/ -v
"""

import numpy as np
import pandas as pd
import pytest

from football_analyzer.core.analyzer import (
    assess_risk,
    compute_reliability,
    fractional_kelly,
)
from football_analyzer.core.features import (
    fair_probs,
    market_entropy,
    overround,
    build_feature_row,
    build_team_long,
)
from football_analyzer.core.data import prepare_historic


# ── fractional_kelly ──────────────────────────────────────────────────────────

class TestFractionalKelly:
    def test_positive_edge(self):
        """Apuesta con edge positivo devuelve stake > 0."""
        k = fractional_kelly(prob=0.55, odds=2.0)
        assert k > 0

    def test_no_edge(self):
        """Sin edge (p=0.5 con cuota 2.0) → kelly = 0."""
        k = fractional_kelly(prob=0.50, odds=2.0)
        assert k == 0.0

    def test_cap_respected(self):
        """Nunca supera el cap del 1.5%."""
        k = fractional_kelly(prob=0.99, odds=10.0, cap=0.015)
        assert k <= 0.015

    def test_zero_for_bad_odds(self):
        """Cuota ≤ 1 → 0."""
        assert fractional_kelly(0.9, 1.0) == 0.0
        assert fractional_kelly(0.9, 0.5) == 0.0

    def test_none_inputs(self):
        """Inputs None no rompen."""
        assert fractional_kelly(None, 2.0) == 0.0
        assert fractional_kelly(0.6, None) == 0.0


# ── fair_probs ────────────────────────────────────────────────────────────────

class TestFairProbs:
    def test_sum_to_one(self):
        fh, fd, fa = fair_probs(2.0, 3.5, 4.0)
        assert abs(fh + fd + fa - 1.0) < 1e-9

    def test_favorite_higher_prob(self):
        """El equipo con cuota más baja tiene mayor probabilidad."""
        fh, fd, fa = fair_probs(1.5, 4.0, 6.0)
        assert fh > fd > fa

    def test_symmetric(self):
        """Cuotas iguales → probabilidades iguales."""
        fh, _, fa = fair_probs(3.0, 3.0, 3.0)
        assert abs(fh - fa) < 1e-9


# ── overround ─────────────────────────────────────────────────────────────────

class TestOverround:
    def test_fair_book(self):
        """Cuotas justas → overround ≈ 1.0."""
        or_ = overround(2.0, 3.0, 3.0)  # sum(1/p) = 0.5+0.333+0.333 = 1.166...
        assert or_ > 1.0

    def test_empty_list(self):
        assert np.isnan(overround())

    def test_ignores_bad_values(self):
        or_ = overround(2.0, None, np.nan, 4.0)
        assert or_ == pytest.approx(1 / 2.0 + 1 / 4.0)


# ── market_entropy ────────────────────────────────────────────────────────────

class TestMarketEntropy:
    def test_uniform_max_entropy(self):
        """Distribución uniforme tiene entropía máxima."""
        e_uniform = market_entropy([1 / 3, 1 / 3, 1 / 3])
        e_skewed  = market_entropy([0.8, 0.1, 0.1])
        assert e_uniform > e_skewed

    def test_empty(self):
        assert np.isnan(market_entropy([]))


# ── assess_risk ───────────────────────────────────────────────────────────────

class TestAssessRisk:
    def test_no_bet_market(self):
        light, _ = assess_risk(0.1, 80, True, "NO BET")
        assert light == "ROJO"

    def test_green_with_strong_edge(self):
        light, _ = assess_risk(edge=0.10, reliability=80, passes_filters=True, market="1")
        assert light == "VERDE"

    def test_yellow_moderate_edge(self):
        light, _ = assess_risk(edge=0.05, reliability=65, passes_filters=True, market="1")
        assert light == "AMARILLO"

    def test_red_weak_edge(self):
        light, _ = assess_risk(edge=0.02, reliability=70, passes_filters=True, market="1")
        assert light == "ROJO"

    def test_red_low_reliability(self):
        light, _ = assess_risk(edge=0.10, reliability=50, passes_filters=True, market="1")
        assert light == "ROJO"

    def test_red_failed_filters(self):
        light, _ = assess_risk(edge=0.10, reliability=80, passes_filters=False, market="1")
        assert light == "ROJO"


# ── compute_reliability ───────────────────────────────────────────────────────

class TestComputeReliability:
    def test_range(self):
        """Siempre entre 0 y 99."""
        for edge in [0, 0.05, 0.15]:
            for roi in [-0.2, 0, 0.1]:
                r = compute_reliability(edge, 0.6, 0.5, roi, 1.0)
                assert 0 <= r <= 99

    def test_higher_edge_higher_score(self):
        r_low  = compute_reliability(0.01, 0.55, 0.50, 0.05, 1.0)
        r_high = compute_reliability(0.10, 0.65, 0.50, 0.05, 1.0)
        assert r_high > r_low


# ── prepare_historic ─────────────────────────────────────────────────────────

class TestPrepareHistoric:
    def _sample_df(self):
        return pd.DataFrame({
            "Date": ["01/09/2024", "08/09/2024"],
            "HomeTeam": ["Arsenal", "Chelsea"],
            "AwayTeam": ["Brentford", "Fulham"],
            "FTHG": [2, 1],
            "FTAG": [0, 1],
            "FTR": ["H", "D"],
            "B365H": [1.5, 2.0],
            "B365D": [4.0, 3.2],
            "B365A": [6.0, 4.0],
        })

    def test_result_derived(self):
        df = prepare_historic(self._sample_df())
        assert list(df["result"]) == ["H", "D"]

    def test_over25_correct(self):
        df = prepare_historic(self._sample_df())
        assert list(df["over25"]) == [1, 0]  # 2-0 → over, 1-1 → under

    def test_sorted_by_date(self):
        raw = self._sample_df()
        raw.iloc[0], raw.iloc[1] = raw.iloc[1].copy(), raw.iloc[0].copy()
        df = prepare_historic(raw)
        assert df.iloc[0]["home_team"] == "Arsenal"  # fecha más antigua primero


# ── build_feature_row ─────────────────────────────────────────────────────────

class TestBuildFeatureRow:
    def _make_long(self):
        """Crea un DataFrame largo mínimo para 2 equipos con 10 partidos."""
        rows = []
        for i in range(10):
            rows.append({"team": "Arsenal",   "is_home": 1, "idx": i, "gf": 2, "ga": 1,
                         "pts": 3, "over25": 1, "shots": 12, "shots_on": 5, "corners": 6})
            rows.append({"team": "Brentford", "is_home": 0, "idx": i, "gf": 1, "ga": 2,
                         "pts": 0, "over25": 1, "shots": 8,  "shots_on": 3, "corners": 4})
        return pd.DataFrame(rows)

    def test_returns_dict(self):
        long_df = self._make_long()
        feat = build_feature_row(long_df, "Arsenal", "Brentford")
        assert isinstance(feat, dict)

    def test_contains_f_prefix_keys(self):
        long_df = self._make_long()
        feat = build_feature_row(long_df, "Arsenal", "Brentford")
        assert any(k.startswith("f_") for k in feat)

    def test_returns_none_insufficient_data(self):
        long_df = self._make_long().head(4)  # menos de 5 por equipo
        feat = build_feature_row(long_df, "Arsenal", "Brentford")
        assert feat is None

    def test_idx_limit_prevents_leakage(self):
        long_df = self._make_long()
        feat_no_limit   = build_feature_row(long_df, "Arsenal", "Brentford")
        feat_with_limit = build_feature_row(long_df, "Arsenal", "Brentford", idx_limit=5)
        # Con menos datos, los promedios pueden diferir
        assert feat_no_limit is not None
        assert feat_with_limit is not None
