"""
ai_analysis.py — Análisis narrativo de picks usando Claude API (Anthropic).

Flujo:
1. DuckDuckGo (sin API key) busca noticias recientes del partido
   (bajas, rotaciones, estado del equipo — última semana).
2. Claude Haiku recibe datos del modelo + noticias y genera el análisis.
3. Prompt caching en el system prompt reduce costes en lotes de picks.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# ── System prompts ─────────────────────────────────────────────────────────────

_SYSTEM = (
    "Eres un analista de apuestas deportivas cuantitativas. "
    "Explica en 2 frases (máximo 160 caracteres) por qué este pick tiene valor "
    "estadístico según el modelo ML+Dixon-Coles. Responde en español. "
    "Cita el argumento más fuerte: edge, CLV, movimiento de línea o forma reciente. "
    "Sin disclaimers. Sin repetir el pick ni la cuota."
)

_SYSTEM_WITH_NEWS = (
    "Eres un analista de apuestas deportivas cuantitativas. "
    "Se te dan datos del modelo predictivo Y noticias reales recientes del partido. "
    "Explica en 2-3 frases (máximo 210 caracteres) por qué este pick tiene valor. "
    "Si hay bajas importantes o noticias relevantes, cítalas como argumento. "
    "Responde en español. Sin disclaimers. Sin repetir el pick ni la cuota."
)


# ── Búsqueda de noticias (DuckDuckGo, sin API key) ────────────────────────────

def _search_match_news(home_team: str, away_team: str) -> str:
    """
    Busca noticias recientes del partido (última semana) en DuckDuckGo.
    No requiere API key. Devuelve '' si falla o no hay resultados.
    """
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        return ""
    try:
        query = f"{home_team} vs {away_team} injury team news lineup"
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=4, timelimit="w"))
        snippets = []
        for r in results:
            body = (r.get("body") or r.get("snippet") or "").strip()
            if body:
                snippets.append(body[:280])
        return "\n---\n".join(snippets[:3]) if snippets else ""
    except Exception as exc:
        logger.debug("DuckDuckGo search error (%s vs %s): %s", home_team, away_team, exc)
        return ""


# ── Helpers de prompt ─────────────────────────────────────────────────────────

def _trend_label(trend) -> str:
    import math
    if trend is None or (isinstance(trend, float) and math.isnan(trend)):
        return "desconocida"
    t = float(trend)
    if t > 0.3:  return "↑ en forma"
    if t < -0.3: return "↓ bajando"
    return "estable"


def _build_prompt(row: dict, news: str = "") -> str:
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
        lines.append(f"H2H (últ.{h2h_n}): local gana {float(h2h_wr):.0%}")
    lines.append(
        f"Fiabilidad: {row.get('reliability_score', 0)}/99  "
        f"Kelly: {row.get('bankroll_pct', 0):.2f}%"
    )
    # Noticias web (si disponibles)
    if news:
        lines += ["", "=== NOTICIAS RECIENTES (web) ===", news]
    return "\n".join(lines)


# ── Generación principal ───────────────────────────────────────────────────────

def generate_pick_analysis(row: dict, api_key: str) -> str:
    """
    Genera análisis narrativo para un pick con Claude Haiku.

    Flujo:
      1. Busca noticias del partido en DuckDuckGo (sin API key, última semana).
      2. Llama a Claude con datos del modelo + noticias.
      3. Usa prompt caching en el system prompt para reducir costes en lotes.

    Devuelve '' si falla o si api_key no está configurada.
    """
    if not api_key:
        return ""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK no instalado. Ejecuta: pip install anthropic")
        return ""

    home = row.get("home_team", "")
    away = row.get("away_team", "")

    # 1. Búsqueda de noticias (falla silenciosamente)
    news = _search_match_news(home, away)
    if news:
        logger.info("Noticias encontradas para %s vs %s (%d chars)", home, away, len(news))

    # 2. Llamada a Claude
    system  = _SYSTEM_WITH_NEWS if news else _SYSTEM
    max_tok = 120 if news else 80
    prompt  = _build_prompt(row, news=news)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tok,
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        result = msg.content[0].text.strip()
        # Añadir badge 🔍 si se usaron noticias web
        if news and result:
            result = "🔍 " + result
        return result
    except Exception as exc:
        logger.warning("Claude API error (%s vs %s): %s", home, away, exc)
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
