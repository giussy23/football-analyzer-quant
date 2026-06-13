# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/ai_chat.py — Sesión de chat interactivo con Claude IA.

Mantiene historial de conversación y contexto de la app (picks, bankroll,
resultados recientes) para que Claude actúe como analista cuantitativo personal.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Importar pricing y modelos del módulo hermano
from .ai_analysis import _MODELS_PREFERRED, _PRICING, _track

_DIAS  = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Palabras que indican que la pregunta necesita datos FRESCOS (búsqueda web)
_WEB_TRIGGERS = (
    "resultado", "resultados", "se jugó", "se jugaron", "jugaron", "ganó", "ganaron",
    "marcador", "partidos", "partido de hoy", "partido de ayer", "ayer", "hoy",
    "esta semana", "última", "ultimo", "último", "acaba", "acaban", "reciente",
    "mundial", "champions", "clasificación", "clasificacion", "lesion", "lesión",
    "alineación", "alineacion", "fichaje", "noticia", "qué pasó", "que paso",
    "ahora mismo", "en directo", "en vivo",
)


def _fecha_es(now) -> str:
    """Fecha y hora en español, sin depender del locale del sistema."""
    return (f"{_DIAS[now.weekday()]} {now.day} de {_MESES[now.month - 1]} "
            f"de {now.year}, {now.strftime('%H:%M')}")


def _needs_web(message: str) -> bool:
    m = message.lower()
    return any(t in m for t in _WEB_TRIGGERS)


def _web_search(query: str, max_items: int = 6) -> str:
    """Busca en DuckDuckGo (sin API key) y devuelve titulares recientes.
    Devuelve '' si no hay resultados o ddgs no está disponible."""
    items: list[str] = []
    try:
        from ddgs import DDGS
        with DDGS() as ddg:
            try:
                res = ddg.news(query, region="es-es", timelimit="w",
                               max_results=max_items) or []
            except Exception:
                res = []
            if not res:
                res = ddg.text(query, region="es-es", max_results=max_items) or []
        for r in res:
            title = (r.get("title") or "").strip()
            body  = (r.get("body") or "").strip()[:180]
            date  = (r.get("date") or "")[:10]
            if title:
                items.append(f"- {date + ' · ' if date else ''}{title}: {body}")
    except Exception as exc:
        logger.debug("Chat web search: %s", exc)
    return "\n".join(items)


class FootballChat:
    """
    Sesión de chat multi-turno con Claude IA.

    Uso:
        chat = FootballChat(api_key="sk-ant-...")
        chat.update_context(picks=[...], bankroll=1000.0, recent_results=[...])
        response = chat.send("¿Cuál es el mejor pick de hoy?")
        chat.clear()
    """

    def __init__(self, api_key: str, storage=None) -> None:
        self.api_key = api_key
        self._storage = storage          # para la herramienta consultar_historial
        self._history: list[dict] = []   # [{"role": "user"|"assistant", "content": str}]
        self._context_block: str = ""    # Bloque de contexto inyectado en cada system prompt
        self._model_used: str = "—"
        self._active_view: str = ""

    # ── Herramientas (function calling) ────────────────────────────────────────

    _TOOLS = [
        {
            "name": "buscar_web",
            "description": (
                "Busca en internet información ACTUAL de fútbol: resultados de "
                "partidos jugados, lesiones, alineaciones probables, fichajes, "
                "noticias, clasificaciones. Úsala siempre que necesites datos "
                "posteriores a tu entrenamiento o de los últimos días."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Búsqueda concreta, p.ej. 'Real Madrid lesionados jornada' o 'resultado Brasil Marruecos'",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "consultar_historial",
            "description": (
                "Consulta el historial REAL del usuario en AlphaBet: sus picks "
                "liquidados (ROI, CLV, racha), combinadas y quinielas guardadas. "
                "Úsala cuando pregunte por su rendimiento, su mejor/peor pick, "
                "cómo va el mes, su CLV, etc."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "tipo": {
                        "type": "string",
                        "enum": ["resumen", "picks_liquidados", "combinadas", "quinielas"],
                        "description": "Qué consultar: 'resumen' (win rate, ROI, CLV global) o el detalle de cada tipo",
                    }
                },
                "required": ["tipo"],
            },
        },
    ]

    def _consultar_historial(self, tipo: str) -> str:
        """Ejecuta la herramienta consultar_historial sobre la BD (read-only)."""
        if self._storage is None:
            return "No hay base de datos conectada."
        try:
            if tipo in ("resumen", "picks_liquidados"):
                picks   = self._storage.load_model_picks(limit=500)
                settled = [p for p in picks if p.get("status") in ("WIN", "LOSS")]
                if not settled:
                    return "El usuario aún no tiene picks liquidados (WIN/LOSS)."
                wins = sum(1 for p in settled if p["status"] == "WIN")
                pnl  = sum(float(p.get("pnl") or 0) for p in settled)
                clvs = [float(p["clv"]) for p in settled if p.get("clv") is not None]
                clv_avg = (sum(clvs) / len(clvs)) if clvs else None
                head = (
                    f"RESUMEN: {len(settled)} picks liquidados · "
                    f"{wins}W/{len(settled)-wins}L · acierto {wins/len(settled)*100:.0f}% · "
                    f"P&L {pnl:+.2f}€"
                    + (f" · CLV medio {clv_avg*100:+.1f}%" if clv_avg is not None else "")
                )
                if tipo == "resumen":
                    return head
                lines = [head, "", "ÚLTIMOS 20:"]
                for p in settled[-20:]:
                    ic = "✅" if p["status"] == "WIN" else "❌"
                    lines.append(
                        f"{ic} {p.get('home_team','')} vs {p.get('away_team','')} — "
                        f"{p.get('pick','')} @ {float(p.get('odds') or 0):.2f} · "
                        f"P&L {float(p.get('pnl') or 0):+.2f}€"
                    )
                return "\n".join(lines)
            if tipo == "combinadas":
                combos = self._storage.load_combos(limit=30)
                if not combos:
                    return "Sin combinadas guardadas."
                lines = [f"{len(combos)} combinadas guardadas (últimas 15):"]
                for c in combos[:15]:
                    legs = c.get("legs", c.get("picks", []))
                    odds = c.get("combo_odds", c.get("odds"))
                    st   = c.get("status", c.get("result", "PENDIENTE"))
                    lines.append(f"· {len(legs)} patas @ {float(odds or 0):.2f} — {st}")
                return "\n".join(lines)
            if tipo == "quinielas":
                qs = self._storage.load_quinielas(limit=20)
                if not qs:
                    return "Sin quinielas guardadas."
                lines = [f"{len(qs)} quinielas guardadas:"]
                for q in qs[:15]:
                    j  = q.get("jornada", "?")
                    ac = q.get("aciertos")
                    st = q.get("status", "PENDIENTE")
                    lines.append(f"· Jornada {j} — {st}" + (f" · {ac} aciertos" if ac is not None else ""))
                return "\n".join(lines)
            return "Tipo de consulta no reconocido."
        except Exception as exc:
            logger.debug("consultar_historial error: %s", exc)
            return f"Error al leer el historial: {exc}"

    # ── Contexto ──────────────────────────────────────────────────────────────

    def update_context(
        self,
        picks: list[dict] | None = None,
        bankroll: float | None = None,
        recent_results: list[dict] | None = None,
        clv_stats: dict | None = None,
        edge_threshold: float = 0.03,
        quiniela_picks: list[dict] | None = None,
        combinadas: list[dict] | None = None,
        backtest_summary: dict | None = None,
        diagnostics: list[str] | None = None,
        active_view: str | None = None,
    ) -> None:
        """
        Reconstruye el bloque de contexto con los datos actuales de la app.

        picks           — lista de dicts con home_team, away_team, pick, odds, edge,
                          model_prob, p_home, p_draw, p_away, league, risk_light
        bankroll        — banca total en euros
        recent_results  — últimos picks con status (WIN/LOSS/PENDING) y pnl
        clv_stats       — dict con avg_clv (float), pct_positive (float 0-1)
        edge_threshold  — umbral de edge configurado
        quiniela_picks  — lista de dicts de la quiniela actual (15 partidos)
        combinadas      — lista de combinadas recomendadas del acumulador
        backtest_summary — métricas del modelo (backtest OOS por liga)
        diagnostics     — lista de strings de diagnóstico del modelo
        active_view     — panel activo ("quiniela", "analysis", "accumulator", etc.)
        """
        if active_view is not None:
            self._active_view = active_view

        lines: list[str] = []

        # --- Panel activo ---
        view_names = {
            "quiniela":    "Quiniela IA",
            "analysis":    "Trading Desk",
            "accumulator": "Combinadas IA",
            "results":     "Tracker de Resultados",
            "portfolio":   "Portfolio / Monte Carlo",
            "alerts":      "Alertas / Monitor de Líneas",
        }
        if self._active_view:
            lines.append(f"Panel activo: {view_names.get(self._active_view, self._active_view)}")

        # --- Bankroll y umbral ---
        if bankroll is not None and bankroll > 0:
            lines.append(f"Bankroll: {bankroll:,.0f}€")
        lines.append(f"Umbral edge: {edge_threshold * 100:.1f}%")

        # --- Picks VERDE/AMARILLO del análisis ---
        verde = [p for p in (picks or []) if p.get("risk_light") == "VERDE"]
        amarillo = [p for p in (picks or []) if p.get("risk_light") == "AMARILLO"]

        if verde:
            lines.append(f"\n== PICKS VERDE HOY ({len(verde)}) ==")
            for i, p in enumerate(verde[:10], 1):
                home   = p.get("home_team", "?")
                away   = p.get("away_team", "?")
                pick   = p.get("pick", "?")
                odds   = p.get("odds")
                edge   = p.get("edge")
                prob   = p.get("model_prob")
                league = p.get("league", "")
                ev     = p.get("ev")
                parts  = [f"{i}. {home} vs {away} ({league}) — Pick: {pick}"]
                if odds:
                    parts.append(f"Cuota: {float(odds):.2f}")
                if edge:
                    parts.append(f"Edge: {float(edge)*100:+.1f}%")
                if prob:
                    parts.append(f"P(modelo): {float(prob):.0%}")
                if ev:
                    parts.append(f"EV: {float(ev)*100:+.1f}%")
                lines.append(" · ".join(parts))
        else:
            lines.append("\n== PICKS HOY ==\nSin picks VERDE en el último análisis.")

        if amarillo:
            lines.append(f"(+ {len(amarillo)} picks AMARILLO de menor confianza)")

        # --- Quiniela actual ---
        if quiniela_picks:
            from collections import Counter
            picks_vals = [p.get("pick", "?") for p in quiniela_picks]
            dist = Counter(picks_vals)
            n1  = dist.get("1", 0)
            nx  = dist.get("X", 0)
            n2  = dist.get("2", 0)
            doubles = sum(1 for v in picks_vals if len(v) == 2)
            triples = sum(1 for v in picks_vals if len(v) == 3)
            sources = Counter(p.get("p_source", "?") for p in quiniela_picks)
            src_str = " · ".join(f"{k}×{v}" for k, v in sources.items())

            lines.append(f"\n== QUINIELA ACTUAL ({len(quiniela_picks)} partidos) ==")
            lines.append(f"Distribución: 1→{n1} · X→{nx} · 2→{n2} · Dobles→{doubles} · Triples→{triples}")
            lines.append(f"Fuentes: {src_str}")
            lines.append("")

            for i, p in enumerate(quiniela_picks, 1):
                home  = p.get("home_team", "?")
                away  = p.get("away_team", "?")
                pick  = p.get("pick", "?")
                src   = p.get("p_source", "")
                ph    = p.get("p_home")
                pd_   = p.get("p_draw")
                pa    = p.get("p_away")
                conf  = p.get("claude_confidence")
                reason = p.get("claude_reason", "")

                # Tipo de signo
                sign_type = "Simple"
                if len(str(pick)) == 2:
                    sign_type = "Doble"
                elif len(str(pick)) == 3:
                    sign_type = "Triple"

                pick_line = f"Partido {i}: {home} vs {away}"
                lines.append(pick_line)

                src_label = {"ml": "ML", "claude": "Claude IA", "club_elo": "Club ELO",
                             "elo": "ELO", "odds_api": "Odds API"}.get(src, src)
                detail = f"  Selección: {pick} ({sign_type}) · Fuente: {src_label}"
                if conf:
                    detail += f" (confianza {conf}/5)"
                lines.append(detail)

                if ph is not None and pd_ is not None and pa is not None:
                    lines.append(
                        f"  Probabilidades: Casa {float(ph)*100:.0f}% · "
                        f"Empate {float(pd_)*100:.0f}% · "
                        f"Vis {float(pa)*100:.0f}%"
                    )
                if reason:
                    lines.append(f"  Razón IA: \"{reason}\"")

        # --- Combinadas ---
        if combinadas:
            lines.append(f"\n== COMBINADAS RECOMENDADAS ({len(combinadas)} generadas) ==")
            for i, combo in enumerate(combinadas[:4], 1):
                legs  = combo.get("legs", [])
                odds_c = combo.get("odds", combo.get("combo_odds"))
                ev_c   = combo.get("ev")
                rel_c  = combo.get("reliability_score", combo.get("avg_reliability"))

                lines.append(f"\nCombinada {i} ({len(legs)} patas):")
                if odds_c:
                    lines.append(f"  Cuota: {float(odds_c):.2f}" +
                                 (f" · EV: {float(ev_c)*100:+.1f}%" if ev_c else "") +
                                 (f" · Fiabilidad: {int(rel_c)}" if rel_c else ""))
                for leg in legs:
                    lh    = leg.get("home_team", leg.get("home", "?"))
                    la    = leg.get("away_team", leg.get("away", "?"))
                    lpick = leg.get("pick", "?")
                    lodds = leg.get("odds")
                    ledge = leg.get("edge")
                    leg_str = f"  • {lh} vs {la} — {lpick}"
                    if lodds:
                        leg_str += f" @ {float(lodds):.2f}"
                    if ledge:
                        leg_str += f" · Edge {float(ledge)*100:+.1f}%"
                    lines.append(leg_str)

        # --- Historial reciente ---
        settled = [p for p in (recent_results or []) if p.get("status") in ("WIN", "LOSS")]
        if settled:
            lines.append(f"\n== HISTORIAL RECIENTE (últimos {min(len(settled), 10)}) ==")
            for p in settled[-10:]:
                status = p.get("status", "?")
                icon   = "✅" if status == "WIN" else "❌"
                match  = f"{p.get('home_team','')} vs {p.get('away_team','')}"
                pick   = p.get("pick", "")
                odds   = p.get("odds")
                clv    = p.get("clv")
                s = f"{icon} {match} — {pick}"
                if odds:
                    s += f" @ {float(odds):.2f}"
                if clv is not None:
                    s += f" · CLV: {float(clv)*100:+.1f}%"
                lines.append(s)

        # --- CLV stats ---
        if clv_stats:
            avg      = clv_stats.get("avg_clv")
            pct      = clv_stats.get("pct_positive")
            wins_r   = clv_stats.get("win_rate")
            roi_r    = clv_stats.get("roi")
            stat_parts = []
            if avg is not None:
                stat_parts.append(f"CLV medio: {float(avg)*100:+.1f}%")
            if pct is not None:
                stat_parts.append(f"CLV+: {float(pct)*100:.0f}%")
            if wins_r is not None:
                stat_parts.append(f"Acierto: {float(wins_r)*100:.0f}%")
            if roi_r is not None:
                stat_parts.append(f"ROI: {float(roi_r)*100:+.1f}%")
            if stat_parts:
                lines.append("\n== ESTADÍSTICAS ==\n" + " · ".join(stat_parts))

        # --- Backtest / métricas del modelo ---
        if backtest_summary:
            lines.append("\n== MÉTRICAS DEL MODELO (BACKTEST OOS) ==")
            for div, metrics in list(backtest_summary.items())[:5]:
                roi  = metrics.get("roi")
                acc  = metrics.get("accuracy")
                brier = metrics.get("brier_score")
                parts = [f"Liga {div}:"]
                if roi is not None:
                    parts.append(f"ROI {float(roi)*100:+.1f}%")
                if acc is not None:
                    parts.append(f"Acierto {float(acc)*100:.0f}%")
                if brier is not None:
                    parts.append(f"Brier {float(brier):.3f}")
                lines.append("  " + " · ".join(parts))

        # --- Diagnósticos ---
        if diagnostics:
            lines.append("\n== DIAGNÓSTICO DEL SISTEMA ==")
            for d in diagnostics[:6]:
                lines.append(f"  • {d}")

        self._context_block = "\n".join(lines)

    # ── Chat ──────────────────────────────────────────────────────────────────

    def send(self, user_message: str) -> str:
        """
        Envía un mensaje a Claude y retorna la respuesta.
        BLOCKING — ejecutar siempre desde un hilo de fondo.
        Retorna string de error si falla (nunca lanza excepción al caller).
        """
        if not self.api_key:
            return "⚠ Configura la API key de Anthropic en ⚙️ Strategy para usar el chat."

        view_hint = ""
        if self._active_view == "quiniela":
            view_hint = (
                "El usuario está mirando la QUINIELA IA. Si pregunta por los picks, "
                "explica en detalle por qué cada partido tiene esa selección, "
                "qué probabilidades maneja el modelo y si fue decidido por ML o por Claude. "
            )
        elif self._active_view == "accumulator":
            view_hint = (
                "El usuario está mirando las COMBINADAS IA. Si pregunta por las combinadas, "
                "explica por qué se agruparon esas patas juntas, el EV combinado y la lógica de diversificación. "
            )
        elif self._active_view == "analysis":
            view_hint = (
                "El usuario está mirando el TRADING DESK con los picks del análisis. "
                "Si pregunta por picks concretos, detalla el edge, las probabilidades y las features más influyentes. "
            )
        elif self._active_view == "results":
            view_hint = (
                "El usuario está mirando su HISTORIAL DE RESULTADOS. "
                "Ayúdale a interpretar su ROI, CLV y racha reciente. "
            )

        # ── Fecha/hora real: el chat antes decía "no sé qué día es" ───────────
        from datetime import datetime as _dt
        fecha = _fecha_es(_dt.now())

        system = (
            "Eres un analista cuantitativo de fútbol experto en apuestas de valor. "
            "Formas parte de AlphaBet v15, un sistema con modelos ML (stacking "
            "HistGB+XGBoost+RF), Club ELO, xG Understat, Kelly fraccionado y CLV.\n\n"
            f"FECHA Y HORA ACTUAL DEL SISTEMA: {fecha}. "
            "Esta es la fecha real de AHORA — úsala como referencia temporal.\n\n"
            "TIENES HERRAMIENTAS — ÚSALAS en vez de excusarte:\n"
            "• buscar_web → para resultados de partidos, lesiones, alineaciones, "
            "fichajes o cualquier dato actual. Si el usuario pregunta por algo "
            "reciente, BUSCA antes de responder; no digas 'no tengo acceso'.\n"
            "• consultar_historial → para el rendimiento real del usuario "
            "(picks liquidados, ROI, CLV, combinadas, quinielas).\n"
            "NUNCA afirmes que no conoces la fecha o que no tienes acceso a datos: "
            "tienes la fecha arriba y las herramientas para buscar el resto.\n\n"
            + (view_hint if view_hint else "")
            + "DATOS ACTUALES DEL USUARIO (AlphaBet):\n"
            + (self._context_block or "Sin análisis cargado todavía.")
            + "\n\nResponde siempre en español, claro y preciso con los números."
        )

        messages = list(self._history) + [{"role": "user", "content": user_message}]

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)

            # Elegir el primer modelo disponible (los modernos soportan tools)
            model_idx = 0
            model = _MODELS_PREFERRED[0]
            final_text = ""

            for _step in range(6):   # loop agéntico acotado
                try:
                    msg = client.messages.create(
                        model=model,
                        max_tokens=2000,           # respuestas completas (antes 600)
                        system=system,
                        messages=messages,
                        tools=self._TOOLS,
                    )
                except anthropic.NotFoundError:
                    model_idx += 1
                    if model_idx >= len(_MODELS_PREFERRED):
                        return "⚠ Ningún modelo disponible con tu API key."
                    model = _MODELS_PREFERRED[model_idx]
                    continue

                _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                self._model_used = model

                if msg.stop_reason == "tool_use":
                    # Ejecutar las herramientas que pidió Claude y devolverle el resultado
                    messages.append({"role": "assistant", "content": msg.content})
                    results = []
                    for block in msg.content:
                        if getattr(block, "type", "") != "tool_use":
                            continue
                        name = block.name
                        inp  = block.input or {}
                        if name == "buscar_web":
                            out = _web_search(inp.get("query", "")) or "Sin resultados en la búsqueda web."
                        elif name == "consultar_historial":
                            out = self._consultar_historial(inp.get("tipo", "resumen"))
                        else:
                            out = "Herramienta desconocida."
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": out,
                        })
                    messages.append({"role": "user", "content": results})
                    continue

                # Respuesta final (end_turn)
                final_text = next(
                    (b.text for b in msg.content if getattr(b, "type", "") == "text"), ""
                ).strip()
                break

            if not final_text:
                return "⚠ No pude completar el análisis (demasiados pasos)."

            self._history.append({"role": "user",      "content": user_message})
            self._history.append({"role": "assistant",  "content": final_text})
            if len(self._history) > 40:
                self._history = self._history[-40:]

            return final_text

        except Exception as exc:
            logger.warning("FootballChat.send error: %s", exc)
            return f"⚠ Error al conectar con Claude: {exc}"

    def clear(self) -> None:
        """Limpia el historial de conversación (el contexto se mantiene)."""
        self._history.clear()

    @property
    def model(self) -> str:
        """Último modelo usado."""
        return self._model_used

    @property
    def turn_count(self) -> int:
        """Número de turnos en el historial actual."""
        return len(self._history) // 2
