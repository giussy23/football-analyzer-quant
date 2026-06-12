# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_risk_guard.py — Tests del circuit breaker de bankroll.

Ejecutar:  pytest tests/test_risk_guard.py -v
"""

from football_analyzer.core.risk_guard import (
    compute_risk_state, current_loss_streak, max_drawdown_abs,
)


# ── Helpers ──────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_loss_streak_basic(self):
        assert current_loss_streak([10, -5, -5, -5]) == 3
        assert current_loss_streak([-5, -5, 10]) == 0      # último es win
        assert current_loss_streak([]) == 0
        assert current_loss_streak([5, 5, 5]) == 0

    def test_max_drawdown(self):
        # +10, +10 (pico 20), luego -5,-5,-5 (valle 5) → dd = 15
        assert max_drawdown_abs([10, 10, -5, -5, -5]) == 15.0
        # sólo ganancias → sin drawdown
        assert max_drawdown_abs([10, 20, 30]) == 0.0
        assert max_drawdown_abs([]) == 0.0


# ── compute_risk_state ───────────────────────────────────────────────────────────

class TestRiskState:
    def test_normal_when_healthy(self):
        st = compute_risk_state([10, -5, 12, 8], bankroll_eur=1000)
        assert st.mode == "NORMAL"
        assert st.multiplier == 1.0
        assert not st.is_active

    def test_reduced_by_loss_streak(self):
        # 3 pérdidas seguidas → REDUCED
        st = compute_risk_state([10, -5, -5, -5], bankroll_eur=1000)
        assert st.mode == "REDUCED"
        assert st.multiplier == 0.5
        assert st.loss_streak == 3

    def test_paused_by_loss_streak(self):
        # 6 pérdidas seguidas → PAUSED
        st = compute_risk_state([-5] * 6, bankroll_eur=1000)
        assert st.mode == "PAUSED"
        assert st.multiplier == 0.0

    def test_reduced_by_drawdown(self):
        # Pico +100, luego -200 → drawdown 200; bankroll 1000 → 20% ≥ 15%.
        # Pero sólo 1 pérdida (no llega a racha) → REDUCED por drawdown.
        st = compute_risk_state([100, -200], bankroll_eur=1000)
        assert st.mode == "REDUCED"
        assert st.drawdown_pct >= 0.15

    def test_paused_by_drawdown(self):
        # drawdown 35% del bankroll → PAUSED aunque la racha sea corta
        st = compute_risk_state([100, -450], bankroll_eur=1000)
        assert st.mode == "PAUSED"
        assert st.drawdown_pct >= 0.30

    def test_no_bankroll_ignores_drawdown(self):
        # Sin bankroll, un único pnl negativo grande no dispara por drawdown
        st = compute_risk_state([-500], bankroll_eur=0)
        assert st.drawdown_pct == 0.0
        assert st.mode == "NORMAL"   # 1 pérdida < reduce_streak

    def test_severest_wins(self):
        # 6 pérdidas seguidas Y drawdown grande → PAUSED (no REDUCED)
        st = compute_risk_state([-100] * 6, bankroll_eur=1000)
        assert st.mode == "PAUSED"

    def test_reason_is_human_readable(self):
        st = compute_risk_state([-5, -5, -5], bankroll_eur=1000)
        assert "pérdidas" in st.reason.lower()
