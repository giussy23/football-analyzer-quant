"""
ai_analysis.py — Análisis narrativo de picks usando Claude API (Anthropic).

Usa prompt caching en el system prompt para reducir costes cuando se analizan
múltiples picks en el mismo lote (~0 tokens de sistema en llamadas 2-N).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Eres un analista de apuestas deportivas cuantitativas. "
    "Tu tarea: explicar en 2 frases cortas (máximo 160 caracteres en total) "
    "por qué este pick tiene valor estadístico, basándote en los datos del "
    "ensemble ML+Dixon-Coles. Responde en español. Cita el argumento más "
    "fuerte: edge, CLV, movimiento de línea o consenso de casas. "
    "Sin disclaimers. Sin repetir el pick ni la cuota."
)


def _trend_label(trend) -> str:
    import math
    if trend is None or (isinstance(trend, float) and math.isnan(trend)):
        return "desconocida"
    t = float(trend)
    if t > 0.3:  return "↑ en forma"
    if t < -0.3: return "↓ bajando"
    return "estable"


def _build_prompt(row: dict) -> str:
    import math
    p_h = float(row.get("p_home") or 0)
    p_d = float(row.get("p_draw") or 0)
    p_a = float(row.get("p_away") or 0)

    lines = [
        f"{row.get('home_team', '?')} vs {row.get('away_team', '?')} "
        f"({row.get('league', '?')})",
        f"Pick: {row.get('pick', '?')} @ {row.get('odds', '?')}",
        f"Ensemble (ML+DC): P(1)={p_h:.0%} P(X)={p_d:.0%} P(2)={p_a:.0%}",
    ]
    if row.get("edge"):
        lines.append(f"Edge: {float(row['edge']):.1%}")
    if row.get("ev"):
        lines.append(f"EV: {float(row['ev']):.1%}")
    if row.get("clv") is not None:
        clv = float(row["clv"])
        lines.append(f"CLV: {clv:+.1%} ({'a favor' if clv > 0 else 'en contra'})")
    if row.get("market_move") is not None:
        lines.append(f"Mov. de línea: {float(row['market_move']):+.1%}")
    n_bks = row.get("n_bookmakers") or 0
    if row.get("consensus_edge") and n_bks > 1:
        lines.append(
            f"Consenso {n_bks} casas: edge {float(row['consensus_edge']):+.1%}"
        )
    # Forma reciente (features v11)
    h_l3 = row.get("f_home_pts_last3")
    a_l3 = row.get("f_away_pts_last3")
    if h_l3 is not None and not (isinstance(h_l3, float) and math.isnan(h_l3)):
        lines.append(
            f"Forma local (últ.3): {float(h_l3):.1f}pts — "
            f"{_trend_label(row.get('f_home_pts_trend'))}"
        )
    if a_l3 is not None and not (isinstance(a_l3, float) and math.isnan(a_l3)):
        lines.append(
            f"Forma visitante (últ.3): {float(a_l3):.1f}pts — "
            f"{_trend_label(row.get('f_away_pts_trend'))}"
        )
    # H2H
    h2h_wr = row.get("f_h2h_home_win_rate")
    h2h_n  = int(row.get("f_h2h_count") or 0)
    if h2h_wr is not None and not (isinstance(h2h_wr, float) and math.isnan(h2h_wr)) and h2h_n >= 2:
        lines.append(
            f"H2H (últ.{h2h_n}): local gana {float(h2h_wr):.0%}"
        )
    lines.append(
        f"Fiabilidad: {row.get('reliability_score', 0)}/99  "
        f"Kelly: {row.get('bankroll_pct', 0):.2f}%"
    )
    return "\n".join(lines)


def generate_pick_analysis(row: dict, api_key: str) -> str:
    """
    Genera análisis narrativo (≤160 chars) para un pick con Claude Haiku.
    Usa prompt caching en el system prompt para reducir costes por lote.
    Devuelve '' si falla o si el API key no está configurado.
    """
    if not api_key:
        return ""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK no instalado. Ejecuta: pip install anthropic")
        return ""
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _build_prompt(row)}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning(
            "Claude API error (%s vs %s): %s",
            row.get("home_team"), row.get("away_team"), exc,
        )
        return ""


def validate_anthropic_key(api_key: str) -> tuple[bool, str]:
    """Valida la API key de Anthropic con una petición mínima."""
    if not api_key:
        return False, "Introduce una API key."
    try:
        import anthropic
    except ImportError:
        return False, "anthropic SDK no instalado. Ejecuta: pip install anthropic"
    try:
        client = anthropic.Anthropic(api_key=api_key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": "ok"}],
        )
        return True, "✓ API key válida"
    except Exception as exc:
        return False, f"Error: {exc}"
