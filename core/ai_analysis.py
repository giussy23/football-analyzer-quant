# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/ai_analysis.py — Integracion con Claude API para analisis narrativo de picks.

Usa claude-3-5-haiku (rapido y economico) para generar explicaciones en lenguaje
natural de cada pick VERDE/AMARILLO tras el analisis cuantitativo.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Modelos en orden de preferencia — se prueban de arriba a abajo.
# Limpiado 12/06/2026: claude-3-5-haiku-20241022 y claude-3-5-sonnet-20241022
# están RETIRADOS de la API (404); claude-3-haiku se retira en abril 2026.
_MODELS_PREFERRED = [
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
]

# Precio por millon de tokens (input, output) en USD
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5":  (1.00,  5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}

# ── Contador de sesion ────────────────────────────────────────────────────────
_session: dict = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": 0.0,
    "model": "—",
}


def get_session_usage() -> dict:
    """Devuelve una copia del uso acumulado en la sesion actual."""
    return dict(_session)


def reset_session_usage() -> None:
    _session.update({"calls": 0, "input_tokens": 0,
                     "output_tokens": 0, "cost_usd": 0.0, "model": "—"})


def _track(model: str, input_tokens: int, output_tokens: int) -> None:
    """Acumula uso y calcula coste estimado."""
    p_in, p_out = _PRICING.get(model, (1.00, 5.00))
    cost = (input_tokens / 1_000_000) * p_in + (output_tokens / 1_000_000) * p_out
    _session["calls"]         += 1
    _session["input_tokens"]  += input_tokens
    _session["output_tokens"] += output_tokens
    _session["cost_usd"]      += cost
    _session["model"]          = model


def validate_anthropic_key(key: str) -> tuple[bool, str]:
    """
    Valida una API key de Anthropic con una llamada minima (5 tokens).
    Retorna (ok, mensaje_para_usuario).
    IMPORTANTE: llamar siempre desde un hilo de fondo, nunca desde el hilo UI.
    """
    if not key:
        return False, "Introduce una API key antes de probar."
    if not key.startswith("sk-ant-"):
        return False, "Clave invalida - debe empezar por sk-ant-"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)

        # Probar modelos en orden hasta encontrar uno disponible
        for model in _MODELS_PREFERRED:
            try:
                client.messages.create(
                    model=model,
                    max_tokens=5,
                    messages=[{"role": "user", "content": "ok"}],
                )
                return True, f"Conexion correcta\nModelo activo: {model}"
            except anthropic.NotFoundError:
                continue   # este modelo no esta disponible, prueba el siguiente

        return False, "Ninguno de los modelos disponibles en tu cuenta."

    except anthropic.AuthenticationError:
        return False, "Clave incorrecta o revocada.\nComprueba en console.anthropic.com"
    except anthropic.RateLimitError:
        return False, "Limite de peticiones alcanzado. Espera unos segundos."
    except anthropic.APIConnectionError:
        return False, "Sin conexion con la API. Comprueba tu internet."
    except Exception as exc:
        logger.warning("validate_anthropic_key error: %s", exc)
        return False, f"Error: {exc}"


def generate_tipster_analysis(row: dict, api_key: str) -> Optional[tuple[str, str]]:
    """
    Tipster profesional para partidos SIN modelo ML (Mundial, Libertadores...).
    Usa el conocimiento de Claude + cuotas de mercado como señal.

    Retorna (pick, analysis_text) donde pick es "1", "X" o "2".
    IMPORTANTE: llamar siempre desde un hilo de fondo.
    """
    try:
        import anthropic

        home   = row.get("home_team", "?")
        away   = row.get("away_team", "?")
        league = row.get("league", "")
        b365h  = row.get("B365H")
        b365d  = row.get("B365D")
        b365a  = row.get("B365A")

        # Probabilidades implícitas sin margen de la casa
        if b365h and b365d and b365a:
            bh, bd, ba = float(b365h), float(b365d), float(b365a)
            total  = 1/bh + 1/bd + 1/ba
            ph     = round((1/bh) / total * 100, 1)
            pd_    = round((1/bd) / total * 100, 1)
            pa     = round((1/ba) / total * 100, 1)
            odds_ctx = (
                f"Cuotas de mercado: Local {bh} | Empate {bd} | Visitante {ba}\n"
                f"Probabilidades implícitas (sin vig): {ph}% / {pd_}% / {pa}%"
            )
        else:
            odds_ctx = "Sin cuotas disponibles para este partido."

        prompt = (
            f"Eres un tipster profesional de fútbol con amplia experiencia en {league}. "
            f"Analiza el siguiente partido y da tu prediccion experta.\n\n"
            f"Partido: {home} vs {away} ({league})\n"
            f"{odds_ctx}\n\n"
            "Usa tu conocimiento sobre el estado actual de ambos equipos, su forma reciente, "
            "jugadores clave, bajas importantes, y el contexto de la competicion. "
            "Las cuotas del mercado son una señal importante — si el mercado favorece a uno, "
            "explica si coincides o si ves valor en la contra.\n\n"
            "Responde EXACTAMENTE en este formato (sin markdown ni etiquetas extra):\n"
            "PICK: [escribe solo 1, X o 2]\n"
            "ANALISIS: [2-3 frases de razonamiento profesional en espanol]\n"
        )

        client = anthropic.Anthropic(api_key=api_key)
        result_text = None
        for model in _MODELS_PREFERRED:
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=220,
                    messages=[{"role": "user", "content": prompt}],
                )
                result_text = msg.content[0].text.strip()
                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                break
            except anthropic.NotFoundError:
                continue

        if not result_text:
            return None

        # Parsear PICK y ANALISIS del formato estructurado
        pick     = "1"
        analysis = result_text
        for line in result_text.splitlines():
            l = line.strip()
            if l.upper().startswith("PICK:"):
                raw = l.split(":", 1)[1].strip().upper()
                if raw in ("1", "X", "2", "1X", "X2", "12", "1X2"):
                    pick = raw
            elif l.upper().startswith("ANALISIS:"):
                analysis = l.split(":", 1)[1].strip()

        return pick, analysis

    except Exception as exc:
        logger.warning(
            "generate_tipster_analysis error %s vs %s: %s",
            row.get("home_team"), row.get("away_team"), exc,
        )
        return None


def generate_pick_analysis(row: dict, api_key: str) -> Optional[str]:
    """
    Genera un analisis narrativo breve (2 frases) para un pick VERDE/AMARILLO.
    Devuelve None si hay error (no lanza excepciones al caller).
    IMPORTANTE: llamar siempre desde un hilo de fondo - hace una peticion HTTP.
    """
    try:
        import anthropic

        home        = row.get("home_team", "?")
        away        = row.get("away_team", "?")
        league      = row.get("league", "")
        pick        = row.get("pick", "?")
        odds        = row.get("odds")
        edge        = row.get("edge")
        model_prob  = row.get("model_prob")
        fair_prob   = row.get("fair_prob")
        ev          = row.get("ev")
        reliability = row.get("reliability_score")
        clv         = row.get("clv")
        cons_edge   = row.get("consensus_edge")

        lines: list[str] = [
            f"Partido: {home} vs {away} ({league})",
            f"Pick: {pick}" + (f" @ {float(odds):.2f}" if odds else ""),
        ]
        if edge:
            lines.append(f"Edge: {float(edge):.1%}")
        if model_prob and fair_prob:
            lines.append(
                f"P(modelo)={float(model_prob):.1%} vs P(mercado)={float(fair_prob):.1%}"
            )
        if ev:
            lines.append(f"EV: {float(ev):+.2%}")
        if reliability:
            lines.append(f"Fiabilidad: {int(reliability)}/99")
        if clv:
            lines.append(f"CLV: {float(clv):+.2%}")
        if cons_edge:
            lines.append(f"Consenso multi-casa: {float(cons_edge):+.2%}")

        prompt = (
            "Eres un analista cuantitativo de apuestas deportivas. "
            "Con los datos siguientes, escribe 2 frases cortas en espanol que expliquen "
            "por que este pick tiene valor estadistico. "
            "Se concreto con los numeros clave. Sin markdown.\n\n"
            + "\n".join(lines)
            + "\n\nAnalisis:"
        )

        client = anthropic.Anthropic(api_key=api_key)
        for model in _MODELS_PREFERRED:
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=160,
                    messages=[{"role": "user", "content": prompt}],
                )
                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                return msg.content[0].text.strip()
            except anthropic.NotFoundError:
                continue
        return None

    except Exception as exc:
        logger.warning(
            "Claude enrichment fallo para %s vs %s: %s",
            row.get("home_team"), row.get("away_team"), exc,
        )
        return None


def sanity_check_picks(picks: list[dict], api_key: str) -> list[dict]:
    """
    Revisa picks VERDE/AMARILLO como 'abogado del diablo'.

    Retorna lista de dicts con:
        match    : str  — "Home vs Away"
        pick     : str  — pick recomendado
        flag     : bool — True si hay algo sospechoso
        concern  : str  — descripción del problema (o "Sin alertas")
        severity : str  — "alta" | "media" | "baja" | "ok"

    Nunca lanza excepciones al caller.
    IMPORTANTE: llamar siempre desde un hilo de fondo.
    """
    if not picks or not api_key:
        return []

    try:
        import anthropic
        import json as _json

        # Construir resumen de picks para el prompt
        pick_lines: list[str] = []
        for i, p in enumerate(picks[:12], 1):
            home  = p.get("home_team", "?")
            away  = p.get("away_team", "?")
            pick  = p.get("pick", "?")
            odds  = p.get("odds")
            edge  = p.get("edge")
            prob  = p.get("model_prob")
            ev    = p.get("ev")
            league = p.get("league", "")
            line = f"{i}. {home} vs {away} ({league}) — Pick: {pick}"
            if odds:
                line += f" @ {float(odds):.2f}"
            if edge:
                line += f" · Edge: {float(edge)*100:+.1f}%"
            if prob:
                line += f" · P: {float(prob):.0%}"
            if ev:
                line += f" · EV: {float(ev)*100:+.1f}%"
            pick_lines.append(line)

        prompt = (
            "Eres un analista de apuestas actuando como abogado del diablo. "
            "Revisa estos picks de un modelo cuantitativo y detecta posibles problemas:\n"
            "- Partidos con contexto especial que invalide el modelo (derby atípico, "
            "equipo sin motivación, lesiones conocidas de jugadores clave)\n"
            "- Picks con edge muy débil (< 3%) o cuotas demasiado bajas (< 1.50)\n"
            "- Correlaciones: picks del mismo partido o liga que se solapan\n"
            "- Cualquier red flag basada en tu conocimiento actual de los equipos\n\n"
            "Picks a revisar:\n"
            + "\n".join(pick_lines)
            + "\n\nResponde SOLO con JSON válido (sin markdown), exactamente así:\n"
            '{"picks": [{"match": "Home vs Away", "pick": "...", "flag": true/false, '
            '"concern": "descripción del problema o Sin alertas", '
            '"severity": "alta|media|baja|ok"}]}'
        )

        client = anthropic.Anthropic(api_key=api_key)
        raw_text: str = ""
        for model in _MODELS_PREFERRED:
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=800,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw_text = msg.content[0].text.strip()
                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                break
            except anthropic.NotFoundError:
                continue

        if not raw_text:
            return []

        # Limpiar posibles bloques markdown
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        data = _json.loads(raw_text)
        return data.get("picks", [])

    except Exception as exc:
        logger.warning("sanity_check_picks error: %s", exc)
        return []


def autopsy_pick(pick: dict, history: list[dict], api_key: str) -> str:
    """
    Autopsia post-partido: analiza por qué el modelo acertó o falló.

    pick    — dict del pick liquidado (home_team, away_team, pick, odds,
              model_prob, edge, status: WIN|LOSS, pnl, clv, league)
    history — últimos picks liquidados (para detectar patrones)

    Retorna texto narrativo. Nunca lanza excepciones al caller.
    IMPORTANTE: llamar siempre desde un hilo de fondo.
    """
    if not api_key:
        return "⚠ Configura la API key de Anthropic en ⚙️ Strategy."

    try:
        import anthropic

        home   = pick.get("home_team", "?")
        away   = pick.get("away_team", "?")
        mpick  = pick.get("pick", "?")
        odds   = pick.get("odds")
        prob   = pick.get("model_prob")
        edge   = pick.get("edge")
        status = pick.get("status", "?")
        clv    = pick.get("clv")
        league = pick.get("league", "")

        result_emoji = "✅ GANADO" if status == "WIN" else "❌ PERDIDO"

        pick_desc = (
            f"Partido: {home} vs {away} ({league})\n"
            f"Pick: {mpick}" + (f" @ {float(odds):.2f}" if odds else "") + "\n"
            f"Resultado: {result_emoji}\n"
        )
        if prob:
            pick_desc += f"Probabilidad modelo: {float(prob):.0%}\n"
        if edge:
            pick_desc += f"Edge estimado: {float(edge)*100:+.1f}%\n"
        if clv is not None:
            pick_desc += f"CLV (vs cuota de cierre): {float(clv)*100:+.1f}%\n"

        # Patrón de picks recientes para contexto
        pattern_lines: list[str] = []
        settled = [p for p in history if p.get("status") in ("WIN", "LOSS")][-10:]
        if len(settled) >= 3:
            wins = sum(1 for p in settled if p.get("status") == "WIN")
            pattern_lines.append(
                f"Racah reciente: {wins}/{len(settled)} ganados en últimos {len(settled)} picks"
            )
            # ¿Hay picks similares (mismo tipo de mercado)?
            same_market = [
                p for p in settled
                if str(p.get("pick", "")).split()[0] == str(mpick).split()[0]
                and p.get("status") in ("WIN", "LOSS")
            ]
            if same_market:
                mkt_wins = sum(1 for p in same_market if p.get("status") == "WIN")
                pattern_lines.append(
                    f"En picks '{mpick.split()[0]}': {mkt_wins}/{len(same_market)} ganados"
                )

        prompt = (
            "Eres un analista cuantitativo de apuestas deportivas realizando "
            "una autopsia post-partido. Analiza el siguiente pick:\n\n"
            + pick_desc
            + ("\n" + "\n".join(pattern_lines) if pattern_lines else "")
            + "\n\nRealiza una autopsia concisa (4-6 frases) en español que cubra:\n"
            "1. Si fue un error del modelo o simplemente varianza estadística normal\n"
            "2. Qué factores pudo no capturar bien el modelo cuantitativo\n"
            "3. Si la apuesta tenía valor positivo aunque haya perdido (buena apuesta, mal resultado)\n"
            "4. Una recomendación práctica para partidos similares en el futuro\n"
            "Sé directo y usa los datos disponibles. Sin markdown."
        )

        client = anthropic.Anthropic(api_key=api_key)
        for model in _MODELS_PREFERRED:
            try:
                msg = client.messages.create(
                    model=model,
                    max_tokens=350,
                    messages=[{"role": "user", "content": prompt}],
                )
                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                return msg.content[0].text.strip()
            except anthropic.NotFoundError:
                continue

        return "⚠ Ningún modelo Claude disponible con tu API key."

    except Exception as exc:
        logger.warning("autopsy_pick error: %s", exc)
        return f"⚠ Error al generar autopsia: {exc}"
