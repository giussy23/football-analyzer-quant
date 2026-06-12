# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_kelly_poisson.py — Tests del staking dinámico y el modelo Poisson.

  · dynamic_kelly_fraction — fracción de Kelly que se adapta al Sharpe rolling
  · score_matrix / probs_from_matrix / DixonColesModel — modelo Dixon-Coles

Ejecutar:  pytest tests/test_kelly_poisson.py -v
"""

from football_analyzer.core.analyzer import dynamic_kelly_fraction, KELLY_FRACTION
from football_analyzer.core.poisson import (
    score_matrix, probs_from_matrix, DixonColesModel,
)


# ── dynamic_kelly_fraction ───────────────────────────────────────────────────────

class TestDynamicKelly:
    def test_no_edge_no_stake(self):
        """p=0.5 con cuota 2.0 → sin edge → stake 0."""
        stake, _ = dynamic_kelly_fraction(0.50, 2.0, [])
        assert stake == 0.0

    def test_invalid_odds(self):
        """Cuota <= 1 → stake 0."""
        stake, _ = dynamic_kelly_fraction(0.60, 1.0, [])
        assert stake == 0.0

    def test_positive_edge_no_history_uses_base(self):
        """Con edge y sin historial liquidado → fracción base."""
        stake, frac = dynamic_kelly_fraction(0.60, 2.0, [])
        assert stake > 0
        assert abs(frac - KELLY_FRACTION) < 1e-4

    def test_bad_streak_reduces_fraction(self):
        """Una racha de pérdidas debe reducir la fracción frente a una buena."""
        good = [10, 12, 8, 11, 9, 10, 13, 9]    # media alta, Sharpe positivo
        bad  = [-10, -12, -8, -11, -9, -10]      # Sharpe negativo
        _, frac_good = dynamic_kelly_fraction(0.60, 2.0, good)
        _, frac_bad  = dynamic_kelly_fraction(0.60, 2.0, bad)
        assert frac_bad < frac_good
        assert frac_bad >= 0.05            # nunca por debajo del mínimo de seguridad

    def test_fraction_floor(self):
        """La fracción nunca baja del 5% aunque el Sharpe sea muy negativo."""
        terrible = [-50, -40, -60, -55, -45]
        _, frac = dynamic_kelly_fraction(0.60, 2.0, terrible)
        assert frac >= 0.05


# ── Modelo Poisson Dixon-Coles ───────────────────────────────────────────────────

class TestPoisson:
    def test_score_matrix_normalised(self):
        """La matriz de marcadores suma 1 (es una distribución de probabilidad)."""
        mat = score_matrix(1.5, 1.2)
        assert abs(mat.sum() - 1.0) < 1e-6

    def test_probs_sum_to_one(self):
        """P(H)+P(D)+P(A) ≈ 1 y cada una en [0, 1]."""
        ph, pd_, pa = probs_from_matrix(score_matrix(1.5, 1.2))
        assert abs(ph + pd_ + pa - 1.0) < 0.02
        assert all(0.0 <= p <= 1.0 for p in (ph, pd_, pa))

    def test_home_strength_increases_home_prob(self):
        """Lambda local alta vs visitante baja → P(local) > P(visitante)."""
        ph, _, pa = probs_from_matrix(score_matrix(2.5, 0.7))
        assert ph > pa

    def test_symmetry(self):
        """Lambdas iguales → P(local) ≈ P(visitante)."""
        ph, _, pa = probs_from_matrix(score_matrix(1.4, 1.4))
        assert abs(ph - pa) < 0.02

    def test_unfitted_model_predicts_none(self):
        """Un modelo sin entrenar devuelve None."""
        assert DixonColesModel().predict("Team A", "Team B") is None
