# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/claude_enricher.py — Enriquecimiento cualitativo de predicciones con Claude AI.

Claude actúa como capa de contexto sobre el ML cuantitativo:
- Genera 6 features interpretativas (0.0–1.0) por partido
- Recibe el contexto estadístico y lo interpreta cualitativamente
- Aplica sus conocimientos sobre equipos, ligas y rivalidades históricas
- Ajusta suavemente las probabilidades ML (máx ±15 pp) sin reemplazarlas
- Cache por sesión → una sola llamada por partido aunque se analice varias veces
- Fallback gracioso a valores neutros (0.5) si la API no está disponible
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Features que Claude genera ────────────────────────────────────────────────

_CLAUDE_FEATURES = (
    "f_claude_injury_home",   # impacto lesiones en local  (0=sin lesiones, 1=baja crítica)
    "f_claude_injury_away",   # impacto lesiones en visitante
    "f_claude_motivation_h",  # motivación extra del local (0=sin interés, 1=final)
    "f_claude_motivation_a",  # motivación extra del visitante
    "f_claude_tactical_edge", # ventaja táctica local (0=desfavorable, 0.5=neutral, 1=ventaja clara)
    "f_claude_surprise_risk", # riesgo de sorpresa (0=resultado esperado, 1=alta incertidumbre)
)

_NEUTRAL: dict[str, float] = {k: 0.5 for k in _CLAUDE_FEATURES}

# Contexto estadístico que se incluye en el prompt (solo los más informativos)
_CTX_KEYS = (
    "f_elo_diff",        "f_form_diff",
    "f_home_pts_w",      "f_away_pts_w",
    "f_home_gf_avg",     "f_away_gf_avg",
    "f_home_ga_avg",     "f_away_ga_avg",
    "f_rest_diff",       "f_home_win_streak",
    "f_away_win_streak", "h2h_home_win_rate",
    "h2h_count",         "h2h_avg_goals",
)


class ClaudeFeatureEnricher:
    """
    Enriquece cada fixture con interpretación cualitativa generada por Claude.

    Flujo:
        1. enrich(home, away, league, feats) → llamada API → dict f_claude_*
        2. adjust_probabilities(ph, pd, pa, pov, feats) → ajuste suave de probs
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._cache:   dict[str, dict[str, float]] = {}
        self.n_calls:  int = 0
        self.n_errors: int = 0
        self.n_cached: int = 0

    # ── API pública ───────────────────────────────────────────────────────────

    def enrich(
        self,
        home_team: str,
        away_team: str,
        league:    str  = "",
        existing_feats: Optional[dict] = None,
    ) -> dict[str, float]:
        """
        Devuelve dict con f_claude_* features para el partido.
        Nunca lanza excepción — devuelve neutro (0.5) si algo falla.
        """
        key = f"{home_team}|{away_team}"
        if key in self._cache:
            self.n_cached += 1
            return self._cache[key]

        try:
            result = self._call_api(home_team, away_team, league, existing_feats or {})
        except Exception as exc:
            logger.debug("ClaudeEnricher [%s vs %s]: %s", home_team, away_team, exc)
            self.n_errors += 1
            result = dict(_NEUTRAL)

        self._cache[key] = result
        return result

    @staticmethod
    def adjust_probabilities(
        p_home: float,
        p_draw: float,
        p_away: float,
        p_over: float,
        feats:  dict[str, float],
    ) -> tuple[float, float, float, float]:
        """
        Aplica los ajustes cualitativos de Claude sobre las probabilidades ML.

        Filosofía: ajustes SUAVES (máx ±15 pp en conjunto) para no anular el ML.
        El ML sigue siendo la señal principal; Claude aporta contexto marginal.

        Lesiones    → reducen la probabilidad del equipo afectado
        Motivación  → levemente aumenta la probabilidad del equipo motivado
        Táctica     → inclina levemente hacia el local si hay ventaja táctica
        Sorpresa    → aplana la distribución hacia uniforme
        """
        injury_h  = float(feats.get("f_claude_injury_home",   0.5))
        injury_a  = float(feats.get("f_claude_injury_away",   0.5))
        motiv_h   = float(feats.get("f_claude_motivation_h",  0.5))
        motiv_a   = float(feats.get("f_claude_motivation_a",  0.5))
        tactical  = float(feats.get("f_claude_tactical_edge", 0.5))
        surprise  = float(feats.get("f_claude_surprise_risk", 0.5))

        # ── Multiplicadores centrados en 1.0 ──────────────────────────────────
        # injury: [0.5=0.925 … 1.0=0.775] — reduce con lesión alta
        m_h = 1.0 - (injury_h - 0.5) * 0.45
        m_a = 1.0 - (injury_a - 0.5) * 0.45

        # motivación: [0.5=1.0 … 1.0=1.08] — leve boost si muy motivado
        m_h += (motiv_h - 0.5) * 0.16
        m_a += (motiv_a - 0.5) * 0.16

        # ventaja táctica: inclina ligeramente hacia el local
        m_h += (tactical - 0.5) * 0.20
        m_a -= (tactical - 0.5) * 0.10   # slight reduce away if home has edge

        # Empate: menos afectado, levemente mayor cuando hay incertidumbre
        m_d = 1.0 + (surprise - 0.5) * 0.10

        # ── Aplicar multiplicadores ───────────────────────────────────────────
        ph_adj = max(0.01, p_home * m_h)
        pd_adj = max(0.01, p_draw * m_d)
        pa_adj = max(0.01, p_away * m_a)

        # ── Aplanamiento por sorpresa (suave) ─────────────────────────────────
        blend = (surprise - 0.5) * 0.30   # rango [−0.15, +0.15]
        unif  = 1.0 / 3.0
        ph_adj = ph_adj * (1 - blend) + unif * blend
        pd_adj = pd_adj * (1 - blend) + unif * blend
        pa_adj = pa_adj * (1 - blend) + unif * blend

        # ── Renormalizar a suma = 1 ───────────────────────────────────────────
        total = ph_adj + pd_adj + pa_adj
        if total > 0:
            ph_adj /= total
            pd_adj /= total
            pa_adj /= total

        # ── Over/Under: lesiones altas → menos goles ─────────────────────────
        avg_injury = (injury_h + injury_a) / 2
        over_adj   = p_over - (avg_injury - 0.5) * 0.12
        over_adj   = float(np.clip(over_adj, 0.05, 0.95))

        return (
            round(float(ph_adj), 4),
            round(float(pd_adj), 4),
            round(float(pa_adj), 4),
            round(over_adj, 4),
        )

    @property
    def stats_summary(self) -> str:
        return (
            f"Claude enricher: {self.n_calls} llamadas API, "
            f"{self.n_cached} cacheadas, {self.n_errors} errores"
        )

    # ── Privado ───────────────────────────────────────────────────────────────

    def _call_api(
        self,
        home:   str,
        away:   str,
        league: str,
        feats:  dict,
    ) -> dict[str, float]:
        import anthropic
        from .ai_analysis import _MODELS_PREFERRED, _track

        # Construir contexto cuantitativo (solo features relevantes y no-NaN)
        ctx_lines = []
        for k in _CTX_KEYS:
            v = feats.get(k)
            if v is not None and str(v) != "nan":
                try:
                    ctx_lines.append(f"  {k}: {float(v):.3f}")
                except (ValueError, TypeError):
                    pass
        ctx_block = ("\nContexto estadístico del partido:\n" + "\n".join(ctx_lines)) if ctx_lines else ""

        # ── Noticias frescas (DDG) — la información que Claude NO tiene ───────
        # Sin esto, Claude evalúa lesiones/motivación desde su fecha de corte
        # de entrenamiento: valores inventados que mueven probabilidades reales.
        try:
            from .news_search import fetch_match_news
            news_items = fetch_match_news(home, away)
        except Exception:
            news_items = []
        news_block = (
            "\nNoticias recientes del partido (fuente: búsqueda web de hoy):\n"
            + "\n".join(f"  - {n}" for n in news_items)
        ) if news_items else "\n(No hay noticias recientes disponibles.)"

        prompt = (
            "Eres un experto en análisis táctico y scouting de fútbol europeo. "
            f"Evalúa el partido: {home} vs {away}"
            f"{' (' + league + ')' if league else ''}."
            f"{ctx_block}\n{news_block}\n\n"
            "Devuelve EXACTAMENTE este JSON (sin texto extra, sin markdown):\n"
            "{\n"
            '  "f_claude_injury_home": <0.0–1.0>,\n'
            '  "f_claude_injury_away": <0.0–1.0>,\n'
            '  "f_claude_motivation_h": <0.0–1.0>,\n'
            '  "f_claude_motivation_a": <0.0–1.0>,\n'
            '  "f_claude_tactical_edge": <0.0–1.0>,\n'
            '  "f_claude_surprise_risk": <0.0–1.0>\n'
            "}\n\n"
            "Guía:\n"
            "· injury_home/away  — 0.0=plantilla completa  0.5=baja menor  1.0=titular clave lesionado\n"
            "    IMPORTANTE: basa las lesiones SOLO en las noticias recientes de arriba.\n"
            "    Si las noticias no mencionan bajas (o no hay noticias), usa 0.5.\n"
            "    NO uses tu conocimiento de entrenamiento para lesiones: está desactualizado.\n"
            "· motivation_h/a    — 0.0=partido sin interés  0.5=normal  1.0=final/partido decisivo\n"
            "    Prioriza las noticias; tu conocimiento solo para contexto general (rivalidades, etc.).\n"
            "· tactical_edge     — 0.0=desventaja táctica del local  0.5=neutro  1.0=ventaja táctica clara\n"
            "· surprise_risk     — 0.0=resultado esperado muy probable  0.5=normal  1.0=alta incertidumbre\n"
            "Si no tienes información precisa sobre algún valor, usa 0.5."
        )

        # Structured output: la API garantiza JSON válido conforme al schema
        # (soportado en haiku-4-5 / sonnet-4-6+; fallback a parseo manual si no)
        _schema = {
            "type": "object",
            "properties": {k: {"type": "number"} for k in _CLAUDE_FEATURES},
            "required": list(_CLAUDE_FEATURES),
            "additionalProperties": False,
        }

        client = anthropic.Anthropic(api_key=self._api_key)
        raw    = None

        for model in _MODELS_PREFERRED:
            try:
                try:
                    msg = client.messages.create(
                        model=model,
                        max_tokens=180,
                        messages=[{"role": "user", "content": prompt}],
                        output_config={"format": {"type": "json_schema", "schema": _schema}},
                    )
                except (TypeError, anthropic.BadRequestError):
                    # SDK antiguo o modelo sin structured outputs → llamada normal
                    msg = client.messages.create(
                        model=model,
                        max_tokens=180,
                        messages=[{"role": "user", "content": prompt}],
                    )
                raw = next(
                    (b.text for b in msg.content if getattr(b, "type", "") == "text"), ""
                ).strip()
                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                self.n_calls += 1
                break
            except anthropic.NotFoundError:
                continue

        if raw is None:
            logger.warning("ClaudeEnricher: ningún modelo disponible")
            return dict(_NEUTRAL)

        # Parsear JSON
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Intento de rescate: buscar JSON entre llaves
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(raw[start:end])
                except Exception:
                    logger.debug("ClaudeEnricher: JSON parse fallido | raw=%r", raw[:120])
                    return dict(_NEUTRAL)
            else:
                return dict(_NEUTRAL)

        result: dict[str, float] = {}
        for k in _CLAUDE_FEATURES:
            v = parsed.get(k, 0.5)
            result[k] = float(np.clip(float(v), 0.0, 1.0))

        return result
