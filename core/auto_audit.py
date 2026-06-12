# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/auto_audit.py — Auditoría automática periódica de rendimiento.

Checks en cada ciclo:
  1. Liquidar picks pendientes (ESPN API, sin coste)
  2. Recalcular estadísticas globales y recientes
  3. Generar alertas (racha negativa, drawdown, ROI, win rate, Sharpe)
  4. Devolver AuditResult con resumen legible + lista de alertas

Diseño:
  - Completamente síncrono y sin tkinter → testeable standalone.
  - Se llama desde un hilo worker en app.py.
  - Devuelve AuditResult con todo lo necesario para actualizar la UI.
"""

from __future__ import annotations

import logging
import math
import statistics as _st
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── Umbrales de alerta ────────────────────────────────────────────────────────

RACHA_LOSS_CRITICAL = 5    # losses consecutivas → alerta roja
RACHA_LOSS_WARN     = 3    # losses consecutivas → alerta amarilla
DD_PCT_CRITICAL     = 0.25 # drawdown > 25% del stake total → alerta roja
DD_PCT_WARN         = 0.15 # drawdown > 15% del stake total → alerta amarilla
ROI_RECENT_WARN     = -0.12  # ROI últimas 10 apuestas < -12%
WR_RECENT_WARN      = 0.35   # win rate últimas 10 < 35%
SHARPE_WARN         = 0.0    # Sharpe rolling < 0 → señal de reversión


@dataclass
class AuditResult:
    timestamp:      str
    picks_settled:  int            # liquidados en este ciclo
    n_settled:      int            # total liquidados histórico
    n_pending:      int            # pendientes aún
    roi:            Optional[float]   # ROI histórico total
    roi_recent:     Optional[float]   # ROI últimas 10
    win_rate:       Optional[float]   # win rate histórico
    win_rate_recent: Optional[float]  # win rate últimas 10
    sharpe:         Optional[float]   # Sharpe por pick (todas)
    max_drawdown:   float             # max DD en unidades de P&L
    racha:          int               # racha actual
    racha_dir:      str               # "+" win  |  "-" loss
    alerts:         list = field(default_factory=list)
    has_critical:   bool = False
    summary:        str  = ""


# ── Función principal ─────────────────────────────────────────────────────────

def run_audit(storage, bankroll_eur: float = 1000.0) -> AuditResult:
    """
    Ejecuta la auditoría completa y devuelve un AuditResult.

    Parámetros
    ----------
    storage      : instancia de core.storage.Storage
    bankroll_eur : bankroll actual en € (para calcular P&L del auto-settler)
    """
    ts = datetime.now().strftime("%H:%M  %d/%m/%Y")
    alerts: list[str] = []

    # ── 1. Liquidar picks pendientes ──────────────────────────────────────────
    settled_now = 0
    try:
        from .auto_settler import auto_settle
        pending = storage.load_model_picks(status="PENDING", limit=200)
        if pending:
            result = auto_settle(pending, bankroll_eur, storage)
            settled_now = result.get("settled", 0)
            logger.info("Auto-audit: %d picks liquidados", settled_now)
    except Exception as exc:
        logger.warning("Auto-audit settler error: %s", exc)

    # ── 2. Cargar estadísticas ────────────────────────────────────────────────
    all_picks = storage.load_model_picks(limit=500)
    settled   = [p for p in all_picks if p.get("status") in ("WIN", "LOSS")]
    pending_n = sum(1 for p in all_picks if p.get("status") == "PENDING")

    if not settled:
        return AuditResult(
            timestamp=ts, picks_settled=settled_now,
            n_settled=0, n_pending=pending_n,
            roi=None, roi_recent=None,
            win_rate=None, win_rate_recent=None,
            sharpe=None, max_drawdown=0.0,
            racha=0, racha_dir="+",
            alerts=[], has_critical=False,
            summary="Sin picks liquidados aún.",
        )

    # Ordenar cronológicamente
    settled = sorted(settled, key=lambda p: p.get("saved_at", "") or "")

    pnl_list   = [float(p.get("pnl", 0.0) or 0.0) for p in settled]
    stakes_raw = [float((p.get("bankroll_pct", 0.0) or 0.0) * 10)
                  for p in settled]  # 10€ de referencia por punto %

    # ROI global
    total_pnl    = sum(pnl_list)
    total_stakes = sum(stakes_raw)
    roi = total_pnl / total_stakes if total_stakes > 1e-9 else None

    # ROI últimas 10
    recent_pnl   = sum(pnl_list[-10:])
    recent_st    = sum(stakes_raw[-10:])
    roi_recent   = recent_pnl / recent_st if recent_st > 1e-9 else None

    # Win rates
    wins          = sum(1 for p in settled if p["status"] == "WIN")
    win_rate      = wins / len(settled) if settled else None
    recent_wins   = sum(1 for p in settled[-10:] if p["status"] == "WIN")
    win_rate_rec  = recent_wins / min(len(settled), 10)

    # Sharpe por pick
    sharpe = None
    if len(pnl_list) >= 4:
        try:
            mean_p = _st.mean(pnl_list)
            std_p  = _st.stdev(pnl_list)
            if std_p > 1e-9:
                sharpe = (mean_p / std_p) * math.sqrt(len(pnl_list))
        except Exception:
            pass

    # Max drawdown (pico → valle)
    cum, acc = [], 0.0
    for v in pnl_list:
        acc += v
        cum.append(acc)
    peak = cum[0]
    max_dd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        max_dd = max(max_dd, peak - v)

    # Racha actual
    statuses = [p.get("status") for p in settled]
    last_st  = statuses[-1]
    racha    = 0
    for st in reversed(statuses):
        if st == last_st:
            racha += 1
        else:
            break

    # ── 3. Generar alertas ────────────────────────────────────────────────────
    n = len(settled)

    # Racha negativa
    if last_st == "LOSS":
        if racha >= RACHA_LOSS_CRITICAL:
            alerts.append(f"🔴  RACHA NEGATIVA: {racha} pérdidas consecutivas")
        elif racha >= RACHA_LOSS_WARN:
            alerts.append(f"🟡  Racha adversa: {racha} pérdidas consecutivas")

    # Drawdown alto (relativo al stake total)
    if total_stakes > 0 and max_dd > 0:
        dd_pct = max_dd / total_stakes
        if dd_pct >= DD_PCT_CRITICAL:
            alerts.append(
                f"🔴  DRAWDOWN CRÍTICO: -{max_dd:.0f}€ ({dd_pct*100:.0f}% del stake total)")
        elif dd_pct >= DD_PCT_WARN:
            alerts.append(
                f"🟡  Drawdown elevado: -{max_dd:.0f}€ ({dd_pct*100:.0f}% del stake total)")

    # ROI reciente
    if roi_recent is not None and roi_recent < ROI_RECENT_WARN:
        alerts.append(f"🟡  ROI últimas 10 apuestas: {roi_recent*100:+.1f}%")

    # Win rate reciente
    if n >= 10 and win_rate_rec < WR_RECENT_WARN:
        alerts.append(
            f"🟡  Win rate últimas 10: {win_rate_rec*100:.0f}%  "
            f"(histórico: {(win_rate or 0)*100:.0f}%)")

    # Sharpe negativo (reversión de la tendencia)
    if sharpe is not None and sharpe < SHARPE_WARN:
        alerts.append(f"🟡  Sharpe negativo ({sharpe:.2f}) — revisar modelo")

    # ── 4. Buenas noticias ────────────────────────────────────────────────────
    good_news = []
    if last_st == "WIN" and racha >= 5:
        good_news.append(f"🟢  Racha positiva: {racha} wins seguidas")
    if roi is not None and roi > 0.10:
        good_news.append(f"🟢  ROI excelente: {roi*100:+.1f}%")
    if sharpe is not None and sharpe >= 2.0:
        good_news.append(f"🟢  Sharpe destacado: {sharpe:.2f}")

    has_critical = any("🔴" in a for a in alerts)

    # ── 5. Resumen ────────────────────────────────────────────────────────────
    parts = []
    if settled_now:
        parts.append(f"{settled_now} pick(s) liquidado(s)")
    parts.append(f"n={n}  ROI {_pct(roi)}  WR {_pct(win_rate)}")
    if alerts:
        parts.append(f"{len(alerts)} alerta(s)")
    elif good_news:
        parts.append(good_news[0])
    summary = " · ".join(parts)

    return AuditResult(
        timestamp=ts,
        picks_settled=settled_now,
        n_settled=n,
        n_pending=pending_n,
        roi=roi,
        roi_recent=roi_recent,
        win_rate=win_rate,
        win_rate_recent=win_rate_rec,
        sharpe=sharpe,
        max_drawdown=max_dd,
        racha=racha,
        racha_dir="+" if last_st == "WIN" else "-",
        alerts=alerts + good_news,
        has_critical=has_critical,
        summary=summary,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v*100:+.{decimals}f}%"


def format_telegram_message(result: AuditResult) -> str:
    """Formatea el AuditResult como mensaje Telegram Markdown."""
    lines = [
        f"📊 *AlphaBet — Auto-Auditoría*",
        f"🕐 {result.timestamp}",
        "",
        f"📈 ROI global: `{_pct(result.roi)}`",
        f"📉 ROI últimas 10: `{_pct(result.roi_recent)}`",
        f"🎯 Win rate: `{_pct(result.win_rate)}` (rec. `{_pct(result.win_rate_recent)}`)",
        f"⚡ Sharpe: `{result.sharpe:.2f}`" if result.sharpe is not None else "⚡ Sharpe: `—`",
        f"📊 Max DD: `-{result.max_drawdown:.1f}€`",
        f"🔁 Racha actual: `{result.racha_dir}{result.racha}`",
        f"⏳ Pendientes: `{result.n_pending}`",
    ]
    if result.picks_settled:
        lines.append(f"✅ Liquidados ahora: `{result.picks_settled}`")

    if result.alerts:
        lines.append("")
        lines.append("*Alertas:*")
        for a in result.alerts:
            lines.append(f"  {a}")

    return "\n".join(lines)
