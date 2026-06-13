# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/risk_guard.py — Circuit breaker de bankroll.

Mientras auto_audit sólo *avisa* de rachas malas y drawdowns, este módulo
*actúa*: a partir del historial de P&L liquidado decide un modo de riesgo que
escala (o corta) el stake recomendado.

  NORMAL   → multiplicador 1.0   (sin restricción)
  REDUCED  → multiplicador 0.5   (racha adversa o drawdown moderado)
  PAUSED   → multiplicador 0.0   (racha crítica o drawdown severo → no apostar)

Diseño:
  · Funciones puras, sin tkinter ni I/O → testeables de forma aislada.
  · El más severo gana (PAUSED > REDUCED > NORMAL).
  · Umbrales configurables; los defaults son coherentes con auto_audit.
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Umbrales por defecto ────────────────────────────────────────────────────────

REDUCE_LOSS_STREAK = 3      # pérdidas consecutivas → reducir stake
PAUSE_LOSS_STREAK  = 6      # pérdidas consecutivas → pausar
REDUCE_DD_PCT      = 0.15   # drawdown >= 15% del bankroll → reducir
PAUSE_DD_PCT       = 0.30   # drawdown >= 30% del bankroll → pausar

_MULT = {"NORMAL": 1.0, "REDUCED": 0.5, "PAUSED": 0.0}


@dataclass
class RiskState:
    mode:         str     # "NORMAL" | "REDUCED" | "PAUSED"
    multiplier:   float   # factor a aplicar al stake (1.0 / 0.5 / 0.0)
    loss_streak:  int     # pérdidas consecutivas actuales
    drawdown_pct: float   # max drawdown como fracción del bankroll (0–1)
    reason:       str     # texto legible para la UI

    @property
    def is_active(self) -> bool:
        """True si el breaker está restringiendo (REDUCED o PAUSED)."""
        return self.mode != "NORMAL"


# ── Helpers puros ────────────────────────────────────────────────────────────────

def current_loss_streak(settled_pnl: list[float]) -> int:
    """Número de pérdidas consecutivas al final del historial (pnl < 0)."""
    streak = 0
    for pnl in reversed(settled_pnl):
        if pnl < 0:
            streak += 1
        else:
            break
    return streak


def max_drawdown_abs(settled_pnl: list[float]) -> float:
    """Máxima caída pico→valle de la curva de P&L acumulado (valor absoluto)."""
    acc = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in settled_pnl:
        acc += pnl
        peak = max(peak, acc)
        max_dd = max(max_dd, peak - acc)
    return max_dd


# ── Función principal ────────────────────────────────────────────────────────────

def compute_risk_state(
    settled_pnl:   list[float],
    bankroll_eur:  float = 0.0,
    *,
    reduce_streak: int   = REDUCE_LOSS_STREAK,
    pause_streak:  int   = PAUSE_LOSS_STREAK,
    reduce_dd:     float = REDUCE_DD_PCT,
    pause_dd:      float = PAUSE_DD_PCT,
) -> RiskState:
    """
    Decide el modo de riesgo a partir del P&L liquidado.

    Parámetros
    ----------
    settled_pnl   : lista de P&L (€) de picks liquidados, en orden cronológico.
    bankroll_eur  : banca actual (€) para expresar el drawdown en %. Si es 0,
                    el drawdown no se evalúa (sólo cuenta la racha).
    """
    loss_streak = current_loss_streak(settled_pnl)
    dd_abs      = max_drawdown_abs(settled_pnl)
    dd_pct      = (dd_abs / bankroll_eur) if bankroll_eur > 0 else 0.0

    pause_by_streak = loss_streak >= pause_streak
    pause_by_dd     = dd_pct >= pause_dd
    reduce_by_streak = loss_streak >= reduce_streak
    reduce_by_dd     = dd_pct >= reduce_dd

    if pause_by_streak or pause_by_dd:
        mode = "PAUSED"
        if pause_by_streak and pause_by_dd:
            reason = f"{loss_streak} pérdidas seguidas y drawdown {dd_pct*100:.0f}%"
        elif pause_by_streak:
            reason = f"{loss_streak} pérdidas consecutivas (>= {pause_streak})"
        else:
            reason = f"Drawdown {dd_pct*100:.0f}% del bankroll (>= {pause_dd*100:.0f}%)"
    elif reduce_by_streak or reduce_by_dd:
        mode = "REDUCED"
        if reduce_by_streak:
            reason = f"{loss_streak} pérdidas consecutivas (>= {reduce_streak})"
        else:
            reason = f"Drawdown {dd_pct*100:.0f}% del bankroll (>= {reduce_dd*100:.0f}%)"
    else:
        mode = "NORMAL"
        reason = "Sin restricciones"

    return RiskState(
        mode=mode,
        multiplier=_MULT[mode],
        loss_streak=loss_streak,
        drawdown_pct=dd_pct,
        reason=reason,
    )
