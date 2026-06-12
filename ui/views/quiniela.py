# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/quiniela.py — Vista de Quinielas IA.

Carga la jornada oficial de La Quiniela (SELAE vía resultados-futbol.com)
y enriquece cada partido con las predicciones del modelo IA cuando estén
disponibles. Calcula picks, dobles, triples, coste y P(pleno).
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Optional

import customtkinter as ctk
import numpy as np
import pandas as pd

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ...core.elo import EloModel
from ...core.quiniela_lae import (
    enrich_with_api_odds, fetch_quiniela_fixture, match_with_predictions,
)
from ...core.quiniela_optimizer import (
    COSTE_BASE as _OPT_COSTE_BASE,
    coverage_label as _cov_label,
    multi_budget as _opt_multi_budget,
    optimize_boleto as _optimize_boleto,
)
from ..widgets import make_card, make_textbox, textbox_set

# Coste base por combinación en la quiniela española (€)
COSTE_BASE = 0.55

# Multiplicadores por tipo de pick (partidos 1-14)
MULT = {"1": 1, "X": 1, "2": 1, "1X": 2, "X2": 2, "12": 2, "1X2": 3,
        "0": 1, "M": 1}   # opciones Pleno al 15

# Picks simples para calcular probabilidad de acertar (partidos 1-14)
DESCOMPOSICION = {
    "1": ["H"], "X": ["D"], "2": ["A"],
    "1X": ["H", "D"], "X2": ["D", "A"], "12": ["H", "A"],
    "1X2": ["H", "D", "A"],
}

# ── Pleno al 15 ───────────────────────────────────────────────────────────────
# El partido 15 de la quiniela oficial usa rangos de goles totales:
#   "0" → 0-1 goles   "1" → 2-3 goles   "2" → 4-5 goles   "M" → 6+ goles
PLENO15_OPTIONS = ["0", "1", "2", "M"]


def _pick_matches(pick: str, real: str) -> bool:
    """
    Devuelve True si el resultado real está cubierto por el pick.

    Ejemplos:
      _pick_matches("1",   "1") → True
      _pick_matches("1X",  "X") → True
      _pick_matches("1X2", "2") → True
      _pick_matches("2",   "1") → False
      _pick_matches("1",   "X") → False
    """
    # Para picks simples (1, X, 2) y compuestos (1X, X2, 12, 1X2)
    return real in pick


def _pleno15_probs(
    p_h: float, p_d: float, p_a: float,
) -> tuple[float, float, float, float]:
    """
    Probabilidad de cada categoría del Pleno al 15 usando modelo Poisson/Dixon-Coles.

    Retorna (p0, p1, p2, pM) donde:
      p0 = P(0-1 goles totales)
      p1 = P(2-3 goles totales)
      p2 = P(4-5 goles totales)
      pM = P(6+ goles totales)

    Prior calibrado para LaLiga (Poisson μ≈2.75):
      p0≈24%  p1≈46%  p2≈24%  pM≈6%
    """
    if p_h <= 0:
        return 0.24, 0.46, 0.24, 0.06   # prior LaLiga Poisson(2.75)

    try:
        from ...core.poisson import score_matrix
        lh, la = _lambdas_from_probs(p_h, p_a, p_d)   # usa p_d para calibrar λ total
        mat    = score_matrix(lh, la)

        b = [0.0, 0.0, 0.0, 0.0]
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                total = i + j
                v     = float(mat[i, j])
                if   total <= 1: b[0] += v
                elif total <= 3: b[1] += v
                elif total <= 5: b[2] += v
                else:            b[3] += v

        s = sum(b)
        if s > 0:
            return tuple(round(x / s, 4) for x in b)   # type: ignore[return-value]
    except Exception:
        pass

    # Fallback: Poisson simple con lambda total
    try:
        import math
        lh, la = _lambdas_from_probs(p_h, p_a, p_d)
        mu     = lh + la

        def _pcdf(k: int) -> float:
            return sum(
                math.exp(-mu) * mu ** i / math.factorial(i)
                for i in range(k + 1)
            )

        p0 = _pcdf(1)
        p1 = _pcdf(3) - p0
        p2 = _pcdf(5) - p0 - p1
        pM = max(0.0, 1.0 - p0 - p1 - p2)
        s  = p0 + p1 + p2 + pM
        if s > 0:
            return round(p0/s, 4), round(p1/s, 4), round(p2/s, 4), round(pM/s, 4)
    except Exception:
        pass

    return 0.24, 0.46, 0.24, 0.06


def _pleno15_pick_ai(p_h: float, p_d: float, p_a: float) -> str:
    """Pick IA para el Pleno al 15: categoría de goles más probable."""
    p0, p1, p2, pM = _pleno15_probs(p_h, p_d, p_a)
    return max([("0", p0), ("1", p1), ("2", p2), ("M", pM)], key=lambda x: x[1])[0]


def _prob_acertar_pleno15(pick: str, p_h: float, p_d: float, p_a: float) -> float:
    """Probabilidad de acertar el Pleno al 15 con el pick dado."""
    p0, p1, p2, pM = _pleno15_probs(p_h, p_d, p_a)
    return {"0": p0, "1": p1, "2": p2, "M": pM}.get(pick, 0.0)


def _ai_pick(
    p_h: float,
    p_d: float,
    p_a: float,
    params: dict | None = None,
) -> str:
    """
    Pick cuantitativo para la quiniela.

    Algoritmo v2 — tres reglas calibradas (parámetros auto-aprendidos):

    1. Corrección de sesgo de empate (draw_bias, default ×1.05):
       los empates están ligeramente infravalorados en modelos europeos.

    2. TRIPLE si max(prob) < triple_threshold (default 0.42):
       no hay favorito claro → cubrir las tres opciones.

    3. DOBLE si 2ª prob >= double_threshold (default 0.28):
       hay dos resultados plausibles → cubrir ambos.

    4. SIMPLE: hay un claro favorito.

    Los thresholds se calibran automáticamente con datos históricos SP1/SP2
    y con los boletos verificados del usuario.
    """
    _p          = params if params else {}
    triple_th   = _p.get("triple_threshold", 0.42)
    double_th   = _p.get("double_threshold", 0.28)
    draw_b      = _p.get("draw_bias",        1.05)

    if p_h <= 0:
        return "1"   # sin datos: local por ventaja estadística histórica

    # ── Corrección sesgo de empate ────────────────────────────────────────────
    p_d_adj = min(p_d * draw_b, 1.0)
    total   = p_h + p_d_adj + p_a
    ph, pd_, pa = p_h / total, p_d_adj / total, p_a / total

    # ── Ordenar por probabilidad ──────────────────────────────────────────────
    ranking = sorted(
        [("H", ph), ("D", pd_), ("A", pa)],
        key=lambda x: x[1], reverse=True,
    )
    best_r,   best_p   = ranking[0]
    second_r, second_p = ranking[1]

    # ── Triple: sin favorito claro ────────────────────────────────────────────
    if best_p < triple_th:
        return "1X2"

    # ── Doble: segunda opción suficientemente probable ────────────────────────
    if second_p >= double_th:
        top2 = {best_r, second_r}
        if top2 == {"H", "D"}:  return "1X"
        if top2 == {"D", "A"}:  return "X2"
        if top2 == {"H", "A"}:  return "12"

    # ── Simple: hay un claro favorito ────────────────────────────────────────
    return "1" if best_r == "H" else ("X" if best_r == "D" else "2")


def _prob_acertar(pick: str, p_h: float, p_d: float, p_a: float) -> float:
    """Probabilidad de que el pick sea correcto."""
    prob_map = {"H": p_h, "D": p_d, "A": p_a}
    return sum(prob_map.get(r, 0) for r in DESCOMPOSICION.get(pick, []))


def _lambdas_from_probs(
    p_home: float,
    p_away: float,
    p_draw: float = 0.27,
) -> tuple[float, float]:
    """
    Estima λ_home y λ_away del modelo Poisson a partir de probabilidades 1X2.

    Mejora sobre la versión anterior: usa p_draw para calibrar λ_total.
    Relación empírica LaLiga: más empates → menos goles totales.
      λ_total ≈ 3.5 - 2.8 × P(draw)   [rango típico 1.8–3.4 según jornada]
    """
    # λ total ajustado por la tasa de empate del partido
    p_draw_clamped = min(max(p_draw, 0.05), 0.50)
    total_prior    = max(1.6, 3.5 - 2.8 * p_draw_clamped)

    try:
        from scipy.optimize import minimize
        from ...core.poisson import score_matrix, probs_from_matrix

        def loss(x: np.ndarray) -> float:
            lh = max(x[0], 0.1)
            la = max(x[1], 0.1)
            mat = score_matrix(lh, la, rho=-0.10)
            ph, pd_, pa = probs_from_matrix(mat)
            # Incluir p_draw en la función de pérdida para mejor calibración
            return (ph - p_home) ** 2 + (pa - p_away) ** 2 + 0.3 * (pd_ - p_draw) ** 2

        ratio = (p_home / max(p_away, 0.05)) ** 0.4
        lh0 = total_prior * ratio / (1.0 + ratio)
        la0 = total_prior / (1.0 + ratio)
        res  = minimize(
            loss, [lh0, la0], method="Nelder-Mead",
            options={"xatol": 0.05, "fatol": 1e-4, "maxiter": 400},
        )
        return max(float(res.x[0]), 0.1), max(float(res.x[1]), 0.1)
    except Exception:
        ratio = (p_home / max(p_away, 0.05)) ** 0.5
        lh = round(total_prior * ratio / (1.0 + ratio), 2)
        la = round(total_prior / (1.0 + ratio), 2)
        return max(lh, 0.1), max(la, 0.1)


def _predict_exact_scores(
    p_h: float, p_d: float, p_a: float, n: int = 6,
) -> list[tuple[int, int, float]]:
    """Top-N marcadores más probables usando Dixon-Coles Poisson."""
    if p_h <= 0:
        return []
    try:
        from ...core.poisson import score_matrix
        lh, la  = _lambdas_from_probs(p_h, p_a, p_d)
        mat     = score_matrix(lh, la)
        scores  = [
            (i, j, float(mat[i, j]))
            for i in range(mat.shape[0])
            for j in range(mat.shape[1])
        ]
        scores.sort(key=lambda x: x[2], reverse=True)
        return scores[:n]
    except Exception:
        return []


def _picks_for_n_doubles(
    rows: list,
    n_doubles: int,
    params: dict | None = None,
) -> list[str]:
    """
    Asigna exactamente n_doubles dobles a los partidos más inciertos.

    Criterio v2: entropía de Shannon normalizada en lugar del gap simple.
    Mayor entropía = mayor incertidumbre = mejor candidato para un doble.
    El sesgo de empate se aplica desde los parámetros calibrados.
    """
    _p      = params if params else {}
    draw_b  = _p.get("draw_bias", 1.05)

    def _uncertainty(r) -> float:
        """Incertidumbre: diferencia entre el 1º y 2º más probable (tras draw bias).
        Menor gap = mayor incertidumbre = mejor candidato para doble."""
        if r.p_h <= 0:
            return 0.0   # sin datos: incertidumbre media
        p_d_adj = min(r.p_d * draw_b, 1.0)
        total   = r.p_h + p_d_adj + r.p_a
        ph, pd_, pa = r.p_h / total, p_d_adj / total, r.p_a / total
        top2 = sorted([ph, pd_, pa], reverse=True)[:2]
        return top2[0] - top2[1]  # gap pequeño = más incierto

    # Orden ASCENDENTE por gap: los de menor gap (más inciertos) reciben los dobles
    order      = sorted(range(len(rows)), key=lambda i: _uncertainty(rows[i]))
    double_set = set(order[:min(n_doubles, len(rows))])

    picks = []
    for i, r in enumerate(rows):
        if r.p_h > 0:
            p_d_adj = min(r.p_d * draw_b, 1.0)
            total   = r.p_h + p_d_adj + r.p_a
            ph, pd_, pa = r.p_h / total, p_d_adj / total, r.p_a / total
        else:
            ph, pd_, pa = 0.45, 0.27, 0.28   # prior histórico ligues europeas

        ranking = sorted(
            [("H", ph), ("D", pd_), ("A", pa)],
            key=lambda x: x[1], reverse=True,
        )
        top2 = {ranking[0][0], ranking[1][0]}

        if i in double_set:
            if   top2 == {"H", "D"}: picks.append("1X")
            elif top2 == {"D", "A"}: picks.append("X2")
            else:                    picks.append("12")
        else:
            best_r = ranking[0][0]
            picks.append("1" if best_r == "H" else ("X" if best_r == "D" else "2"))

    return picks


def _upgrade_with_ml(
    enriched: list[dict],
    future_df: pd.DataFrame,
) -> list[dict]:
    """
    Mejora opcional: si el Trading Desk ya tiene predicciones ML para algún partido
    de la quiniela, sustituye la fuente por ML (más calibrada que odds en ligas con datos).
    Solo actúa sobre partidos que NO tienen ya una fuente de calidad.
    """
    from ...core.quiniela_lae import normalize as _norm

    df = future_df.copy()
    df["_nh"] = df["home_team"].astype(str).map(_norm)
    df["_na"] = df["away_team"].astype(str).map(_norm)

    result = []
    for match in enriched:
        entry = dict(match)
        # Fuente actual: si ya tiene odds_api con buenas probs, dejar como está
        if entry.get("p_source") == "odds_api" and entry.get("p_home"):
            result.append(entry)
            continue

        local_norms = {_norm(entry.get("local", "")),
                       _norm(entry.get("local_en", entry.get("local", "")))}
        visit_norms = {_norm(entry.get("visitante", "")),
                       _norm(entry.get("visitante_en", entry.get("visitante", "")))}

        found = None
        for _, row in df.iterrows():
            if (any(ln and (ln in row["_nh"] or row["_nh"] in ln) for ln in local_norms)
                    and any(vn and (vn in row["_na"] or row["_na"] in vn) for vn in visit_norms)):
                found = row
                break

        if found is not None and found.get("p_home") is not None:
            entry.update({
                "p_home":      found.get("p_home"),
                "p_draw":      found.get("p_draw"),
                "p_away":      found.get("p_away"),
                "model_pick":  found.get("pick"),
                "odds_h":      found.get("B365H") or found.get("odds"),
                "odds_d":      found.get("B365D"),
                "odds_a":      found.get("B365A"),
                "reliability": found.get("reliability_score", 0),
                "p_source":    "ml",
            })

        result.append(entry)
    return result


# ── Análisis profundo con Claude ──────────────────────────────────────────────

# Peso que tiene Claude al mezclar con las probs del modelo según su confianza
_CONFIDENCE_WEIGHTS: dict[int, float] = {
    5: 0.72,   # muy seguro   → Claude domina 72 %
    4: 0.55,   # probable     → ligera mayoría Claude
    3: 0.38,   # moderado     → blend equilibrado
    2: 0.22,   # incierto     → modelo sigue siendo base
    1: 0.10,   # muy incierto → casi no modifica las probs del modelo
}

# Distribución de prob implícita al decir "resultado X con alta confianza"
_RESULT_PRIORS: dict[str, tuple[float, float, float]] = {
    "1": (0.82, 0.12, 0.06),
    "X": (0.12, 0.76, 0.12),
    "2": (0.06, 0.12, 0.82),
}


def _blend_with_claude(
    p_h: float, p_d: float, p_a: float,
    resultado: str, confianza: int,
) -> tuple[float, float, float]:
    """
    Mezcla las probabilidades del modelo con la predicción de Claude.

    Mayor confianza → Claude domina el blend.
    Confianza 1     → el modelo apenas cambia.
    Sin probs previas (p_h=0) → usa sólo el prior de Claude.
    """
    w    = _CONFIDENCE_WEIGHTS.get(max(1, min(5, confianza)), 0.38)
    c_h, c_d, c_a = _RESULT_PRIORS.get(resultado, (0.40, 0.33, 0.27))

    if p_h <= 0:
        b_h, b_d, b_a = c_h, c_d, c_a
    else:
        b_h = (1.0 - w) * p_h + w * c_h
        b_d = (1.0 - w) * p_d + w * c_d
        b_a = (1.0 - w) * p_a + w * c_a

    total = b_h + b_d + b_a
    if total <= 0:
        return 0.40, 0.33, 0.27
    return round(b_h / total, 4), round(b_d / total, 4), round(b_a / total, 4)


class QuilineaRow:
    """Estado de una fila de la quiniela (un partido)."""
    def __init__(self, match_data: pd.Series):
        self.data    = match_data
        self.pick_var = tk.StringVar(value="1")
        # Probabilidades del modelo — 0 si no disponibles (sin predicción)
        ph = match_data.get("p_home")
        pd_ = match_data.get("p_draw")
        pa = match_data.get("p_away")
        has_pred = (ph is not None and pd.notna(ph) and float(ph) > 0)
        self.p_h = float(ph) if has_pred else 0.0
        self.p_d = float(pd_) if (pd_ is not None and pd.notna(pd_)) else 0.0
        self.p_a = float(pa) if (pa is not None and pd.notna(pa)) else 0.0


class QuinielaView(ctk.CTkFrame):
    """Vista de generador de quinielas con IA."""

    PICK_OPTIONS = ["1", "X", "2", "1X", "X2", "12", "1X2"]
    MAX_MATCHES  = 15

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app               = app
        self._rows:         list[QuilineaRow] = []
        self._n_doubles        = tk.IntVar(value=0)
        self._jornada_fecha: str = ""
        self._historial_visible:    bool = False
        self._calibration_visible:  bool = False
        self._q_params:             dict = {}   # parámetros calibrados activos
        self._calibration_running:  bool = False
        self._build()
        self._load_calibrated_params()   # cargar al arrancar

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_controls()
        self._build_table()
        self._build_summary()
        self._build_pleno15_section()
        self._build_historial_section()
        self._build_calibration_section()

    def _build_controls(self) -> None:
        ctrl = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # ═══════════════════════════════════════════════════════════════════════
        # FILA 0 — pack horizontal: título izq · grupos de botones der
        # Usar pack (no grid) evita que columnas con weight=1 empujen los botones
        # fuera de la pantalla.
        # ═══════════════════════════════════════════════════════════════════════
        row0 = ctk.CTkFrame(ctrl, fg_color="transparent")
        row0.pack(fill="x", padx=10, pady=(8, 2))

        # Título — izquierda
        ctk.CTkLabel(
            row0, text="⚽  Quiniela IA",
            text_color=TEXT, font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left", padx=(4, 0))

        # Grupo IA — derecha (pack PRIMERO = queda más a la derecha)
        _grp_ai = ctk.CTkFrame(row0, fg_color="#08041a", corner_radius=10,
                                border_color="#3b1f6e", border_width=1)
        _grp_ai.pack(side="right", padx=(4, 0))
        ctk.CTkLabel(
            _grp_ai, text="IA", text_color="#4c2a8a",
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=(8, 2))
        ctk.CTkButton(
            _grp_ai, text="⚡ Picks",
            command=self.generate_ai,
            fg_color=ACCENT, hover_color=ACCENT_2, height=32, corner_radius=8,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=3, pady=5)
        self._claude_q_btn = ctk.CTkButton(
            _grp_ai, text="🧠 Profundo",
            command=self._start_deep_claude_analysis,
            fg_color="#1a0a2e", hover_color="#2a1050",
            border_color="#7c3aed", border_width=1, height=32, corner_radius=8,
            font=ctk.CTkFont(size=11),
        )
        self._claude_q_btn.pack(side="left", padx=3, pady=5)
        ctk.CTkButton(
            _grp_ai, text="💬 Chat",
            command=self._open_chat_with_context,
            fg_color="#1e1b4b", hover_color="#312e81",
            border_color="#818cf8", border_width=1,
            text_color="#c4b5fd", height=32, corner_radius=8,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(3, 8), pady=5)

        # Grupo CARGAR — derecha (pack SEGUNDO = queda entre título y grupo IA)
        _grp_load = ctk.CTkFrame(row0, fg_color="#050d06", corner_radius=10,
                                  border_color="#1a4d2a", border_width=1)
        _grp_load.pack(side="right", padx=(0, 6))
        ctk.CTkLabel(
            _grp_load, text="CARGAR", text_color="#2d6a3e",
            font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=(8, 2))
        ctk.CTkButton(
            _grp_load, text="📋 Jornada",
            command=self.load_official,
            fg_color="#0a2210", hover_color="#0f2e14", height=32, corner_radius=8,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=3, pady=5)
        self._ml_btn = ctk.CTkButton(
            _grp_load, text="🔬 ML",
            command=self._start_direct_ml,
            fg_color="#0a1a2a", hover_color="#0e2a3e", height=32, corner_radius=8,
            font=ctk.CTkFont(size=11),
        )
        self._ml_btn.pack(side="left", padx=(3, 8), pady=5)

        # ═══════════════════════════════════════════════════════════════════════
        # FILA 1 — Dobles izq · Status centro · Acciones der
        # ═══════════════════════════════════════════════════════════════════════
        row1 = ctk.CTkFrame(ctrl, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(0, 4))

        # ── Acciones — derecha (pack PRIMERO = más a la derecha) ─────────────
        _ACT_BTN = dict(height=28, corner_radius=8, font=ctk.CTkFont(size=10))
        _grp_act = ctk.CTkFrame(row1, fg_color="transparent")
        _grp_act.pack(side="right")
        ctk.CTkButton(
            _grp_act, text="🎯 Optimizar",
            command=self._open_optimizer_dialog,
            fg_color="#0a0a1a", hover_color="#12122a",
            border_color="#38bdf8", border_width=1,
            text_color="#7dd3fc", **_ACT_BTN,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            _grp_act, text="💾 Guardar",
            command=self.save_current_boleto,
            fg_color="#1a3010", hover_color="#224014",
            border_color="#22c55e", border_width=1, **_ACT_BTN,
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            _grp_act, text="📤 Exportar",
            command=self.export_picks,
            fg_color="#0a2210", hover_color="#0f2e14", **_ACT_BTN,
        ).pack(side="left", padx=2)
        self._hist_toggle_btn = ctk.CTkButton(
            _grp_act, text="📂 Historial",
            command=self._toggle_historial,
            fg_color="#0f1a10", hover_color="#162414", **_ACT_BTN,
        )
        self._hist_toggle_btn.pack(side="left", padx=2)
        self._cal_btn = ctk.CTkButton(
            _grp_act, text="🧬 Calibrar",
            command=self._toggle_calibration,
            fg_color="#0f0f1a", hover_color="#18182e",
            border_color="#818cf8", border_width=1, **_ACT_BTN,
        )
        self._cal_btn.pack(side="left", padx=2)
        ctk.CTkButton(
            _grp_act, text="✖ Limpiar",
            command=self.clear_picks,
            fg_color="#1a0a0a", hover_color="#2a0f0f", **_ACT_BTN,
        ).pack(side="left", padx=(2, 4))

        # ── Status — fill para ocupar el espacio central restante ────────────
        self.status_lbl = ctk.CTkLabel(
            row1,
            text="📋  Pulsa 'Jornada' para cargar la jornada oficial",
            text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w",
        )
        self.status_lbl.pack(side="left", fill="x", expand=True)

        # ═══════════════════════════════════════════════════════════════════════
        # FILA 1b — Selector de dobles (fila propia, siempre visible)
        # ═══════════════════════════════════════════════════════════════════════
        row_dbl = ctk.CTkFrame(ctrl, fg_color=CARD_2, corner_radius=8)
        row_dbl.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkLabel(
            row_dbl,
            text="  Nº Dobles en el boleto:",
            text_color=TEXT,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", padx=(6, 10), pady=6)

        self._doubles_btns: dict[int, ctk.CTkButton] = {}
        _dbl_opts = [(0, "Auto (IA)"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")]
        for _v, _lbl in _dbl_opts:
            _b = ctk.CTkButton(
                row_dbl,
                text=_lbl,
                width=60, height=30,
                font=ctk.CTkFont(size=11),
                fg_color="#112211",
                hover_color="#1a3a1a",
                text_color="#90d890",
                border_width=1,
                border_color="#2a5a2a",
                corner_radius=6,
                command=lambda v=_v: self._set_doubles(v),
            )
            _b.pack(side="left", padx=3, pady=5)
            self._doubles_btns[_v] = _b
        self._highlight_doubles_btn(0)

        # ═══════════════════════════════════════════════════════════════════════
        # FILA 2 — Patrón 1/X/2 + inteligencia de jornada
        # ═══════════════════════════════════════════════════════════════════════
        dist_bar = ctk.CTkFrame(ctrl, fg_color="#030a04", corner_radius=8)
        dist_bar.pack(fill="x", padx=10, pady=(0, 8))

        ctk.CTkLabel(
            dist_bar, text="Patrón 1/X/2:",
            text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(side="left", padx=(10, 6), pady=6)

        _dist_config = [
            ("1", "1 Local",  "5–9",  "#22c55e"),
            ("X", "X Empate", "3–6",  "#fbbf24"),
            ("2", "2 Visita", "2–5",  "#60a5fa"),
        ]
        self._dist_labels: dict[str, ctk.CTkLabel] = {}
        for key, name, rng, col in _dist_config:
            card = ctk.CTkFrame(dist_bar, fg_color="#050e1c", corner_radius=6)
            card.pack(side="left", padx=3, pady=4)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(padx=8, pady=3)
            ctk.CTkLabel(
                inner, text=name,
                text_color=col, font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(side="left", padx=(0, 5))
            val_lbl = ctk.CTkLabel(
                inner, text="—",
                text_color=MUTED, font=ctk.CTkFont(size=15, weight="bold"),
            )
            val_lbl.pack(side="left")
            ctk.CTkLabel(
                inner, text=f"/{rng}",
                text_color="#2a4030", font=ctk.CTkFont(size=9),
            ).pack(side="left")
            self._dist_labels[key] = val_lbl

        # Inteligencia de jornada
        self._jornada_intel_lbl = ctk.CTkLabel(
            dist_bar, text="",
            text_color="#64748b", font=ctk.CTkFont(size=10),
        )
        self._jornada_intel_lbl.pack(side="left", padx=(14, 0), pady=6)

        ctk.CTkLabel(
            dist_bar,
            text="Verde = rango  ·  Amarillo = ±1  ·  Rojo = lejos",
            text_color="#2d4a32", font=ctk.CTkFont(size=9),
        ).pack(side="right", padx=(0, 12), pady=6)

    def _build_table(self) -> None:
        # Estilo Treeview oscuro
        style = ttk.Style()
        style.configure("Quiniela.Treeview",
            background="#050e1c", fieldbackground="#050e1c",
            foreground="#f0fff4", rowheight=30,
            font=("Segoe UI", 10),
        )
        style.configure("Quiniela.Treeview.Heading",
            background="#091408", foreground="#aed6b8",
            font=("Segoe UI Semibold", 10),
        )
        style.map("Quiniela.Treeview",
                  background=[("selected", "#1a4d2a")])

        shell = ctk.CTkFrame(self, fg_color="#060f07", corner_radius=14)
        shell.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        # Nueva columna "conf" — confianza del modelo/IA
        cols = ("#", "local", "visitante", "p1", "px", "p2", "pick_ia", "conf", "tu_pick")
        self.tree = ttk.Treeview(
            shell, columns=cols, show="headings",
            style="Quiniela.Treeview", selectmode="browse",
        )

        heads = {
            "#":          ("#",          36),
            "local":      ("Local",     168),
            "visitante":  ("Visitante", 168),
            "p1":         ("P(1)",       60),
            "px":         ("P(X)",       60),
            "p2":         ("P(2)",       60),
            "pick_ia":    ("IA",         72),
            "conf":       ("Confianza",  90),
            "tu_pick":    ("Tu pick",    72),
        }
        for col, (label, width) in heads.items():
            self.tree.heading(col, text=label)
            anchor = "w" if col in ("local", "visitante") else "center"
            self.tree.column(col, width=width, anchor=anchor)

        # Tags de cobertura (color del texto)
        self.tree.tag_configure("single",   foreground="#d6ffe6")
        self.tree.tag_configure("double",   foreground="#fff0c2")
        self.tree.tag_configure("triple",   foreground="#ffd3d3")
        self.tree.tag_configure("even_row", background="#050e1c")
        self.tree.tag_configure("odd_row",  background="#091408")
        # Tags de confianza (subrayado visual en la columna IA — cambia bg de fila)
        self.tree.tag_configure("conf_high",   background="#061a0a")   # Claude 4-5
        self.tree.tag_configure("conf_med",    background="#121004")   # Claude 3
        self.tree.tag_configure("conf_low",    background="#160808")   # Claude 1-2

        self.tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview).grid(
            row=0, column=1, sticky="ns", pady=6,
        )

        # ── Panel de detalle del partido seleccionado (reemplaza edit bar) ────
        detail_bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                                   border_color=BORDER, border_width=1)
        detail_bar.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        detail_bar.grid_columnconfigure(1, weight=1)

        # — Izquierda: pick selector —
        pick_side = ctk.CTkFrame(detail_bar, fg_color="transparent")
        pick_side.grid(row=0, column=0, padx=10, pady=6, sticky="ns")
        ctk.CTkLabel(pick_side, text="Pick:", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        self._edit_var = tk.StringVar(value="1")
        self._pick_menu = ctk.CTkOptionMenu(
            pick_side, variable=self._edit_var,
            values=self.PICK_OPTIONS,
            fg_color=CARD_2, button_color=ACCENT,
            command=self._apply_pick_edit,
            width=90, height=30,
        )
        self._pick_menu.pack(side="left")

        # — Centro: información del partido seleccionado —
        self._detail_info_frame = ctk.CTkFrame(detail_bar, fg_color="transparent")
        self._detail_info_frame.grid(row=0, column=1, padx=8, pady=4, sticky="ew")
        self._detail_info_frame.grid_columnconfigure(0, weight=1)

        self._detail_match_lbl = ctk.CTkLabel(
            self._detail_info_frame,
            text="← Selecciona un partido para ver el análisis detallado",
            text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w",
        )
        self._detail_match_lbl.grid(row=0, column=0, sticky="ew")

        # Barras de probabilidad (texto art)
        self._detail_prob_lbl = ctk.CTkLabel(
            self._detail_info_frame, text="",
            text_color="#4ade80", font=ctk.CTkFont(size=10, family="Consolas"),
            anchor="w",
        )
        self._detail_prob_lbl.grid(row=1, column=0, sticky="ew")

        # Razón Claude / fuente del dato
        self._detail_reason_lbl = ctk.CTkLabel(
            self._detail_info_frame, text="",
            text_color="#a78bfa", font=ctk.CTkFont(size=10),
            anchor="w", wraplength=500,
        )
        self._detail_reason_lbl.grid(row=2, column=0, sticky="ew")

        # — Derecha: badge de fuente de datos —
        self._detail_src_lbl = ctk.CTkLabel(
            detail_bar, text="", text_color=MUTED,
            font=ctk.CTkFont(size=10, weight="bold"), anchor="e",
        )
        self._detail_src_lbl.grid(row=0, column=2, padx=(4, 12), pady=6, sticky="e")

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_summary(self) -> None:
        self.summary_frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        self.summary_frame.grid(row=3, column=0, sticky="ew")
        self.summary_frame.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self._kpi_labels: dict[str, ctk.CTkLabel] = {}
        kpis = [
            ("partidos",      "Partidos",       "0",      TEXT,    ""),
            ("combinaciones", "Combinaciones",  "0",      TEXT,    ""),
            ("coste",         "Coste boleto",   "0.00 €", TEXT,    ""),
            ("prob",          "P(pleno 15)",    "—",      TEXT,    ""),
            ("conf_avg",      "Confianza IA",   "—",      MUTED,   "Media de picks del modelo"),
            ("picks_ml",      "Picks con ML",   "0",      "#7dd3fc","Partidos con predicción ML"),
        ]
        for col, (key, title, default, color, hint) in enumerate(kpis):
            box = ctk.CTkFrame(self.summary_frame, fg_color="#050e1c", corner_radius=12)
            box.grid(row=0, column=col, padx=5, pady=8, sticky="ew")
            ctk.CTkLabel(box, text=title, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(anchor="w", padx=10, pady=(8, 1))
            lbl = ctk.CTkLabel(box, text=default, text_color=color,
                               font=ctk.CTkFont(size=18, weight="bold"))
            lbl.pack(anchor="w", padx=10, pady=(0, 8))
            self._kpi_labels[key] = lbl

    def _build_pleno15_section(self) -> None:
        """Panel inferior: marcador exacto predicho para el partido 15 (pleno al 15)."""
        frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        frame.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame,
            text="🎯  Pleno al 15 — Marcador partido 15:",
            text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=10, sticky="w")

        self._pleno15_lbl = ctk.CTkLabel(
            frame,
            text="Carga la jornada para ver los marcadores más probables del partido 15",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        )
        self._pleno15_lbl.grid(row=0, column=1, padx=8, pady=10, sticky="w")

    # ── Entrada manual de partidos ────────────────────────────────────────────

    def _open_manual_entry_dialog(self) -> None:
        """Abre un diálogo para introducir los 15 partidos manualmente desde SELAE."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("✏️ Introducir partidos manualmente")
        dlg.geometry("700x680")
        dlg.resizable(False, True)
        dlg.grab_set()
        dlg.configure(fg_color="#050d06")

        # ── Cabecera ──────────────────────────────────────────────────────────
        header = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=10)
        header.pack(fill="x", padx=16, pady=(14, 0))

        ctk.CTkLabel(
            header,
            text="Introduce los 15 partidos tal como aparecen en SELAE (loteriasyapuestas.es)",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=14, pady=10)

        # Jornada
        jor_frame = ctk.CTkFrame(header, fg_color="transparent")
        jor_frame.pack(side="right", padx=14, pady=8)
        ctk.CTkLabel(jor_frame, text="Jornada:", text_color=TEXT,
                     font=ctk.CTkFont(size=11)).pack(side="left")
        jornada_var = tk.StringVar(value="")
        ctk.CTkEntry(jor_frame, textvariable=jornada_var, width=55,
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(6, 0))

        # ── Tabla de partidos ─────────────────────────────────────────────────
        scroll_frame = ctk.CTkScrollableFrame(dlg, fg_color="#050d06")
        scroll_frame.pack(fill="both", expand=True, padx=16, pady=10)
        scroll_frame.grid_columnconfigure(1, weight=1)
        scroll_frame.grid_columnconfigure(2, weight=1)

        # Cabecera de columnas
        for col, txt, w in [(0, "#", 32), (1, "Local", 1), (2, "Visitante", 1)]:
            ctk.CTkLabel(
                scroll_frame, text=txt, text_color=MUTED,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=col, padx=6, pady=(4, 2), sticky="w")

        local_vars:     list[tk.StringVar] = []
        visit_vars:     list[tk.StringVar] = []

        for i in range(15):
            lv = tk.StringVar()
            vv = tk.StringVar()
            local_vars.append(lv)
            visit_vars.append(vv)

            row_color = "#050d06" if i % 2 == 0 else "#080f09"
            num_lbl = ctk.CTkLabel(
                scroll_frame, text=f"{'P15' if i == 14 else str(i+1):>3}",
                text_color="#fde047" if i == 14 else MUTED,
                font=ctk.CTkFont(size=11, weight="bold" if i == 14 else "normal"),
            )
            num_lbl.grid(row=i + 1, column=0, padx=6, pady=3, sticky="e")

            ent_local = ctk.CTkEntry(
                scroll_frame, textvariable=lv,
                placeholder_text="Local",
                font=ctk.CTkFont(size=12), height=30,
                fg_color=row_color,
            )
            ent_local.grid(row=i + 1, column=1, padx=(4, 3), pady=3, sticky="ew")

            ctk.CTkLabel(scroll_frame, text="vs", text_color=MUTED,
                         font=ctk.CTkFont(size=10)).grid(row=i + 1, column=2, padx=0)

            ent_visit = ctk.CTkEntry(
                scroll_frame, textvariable=vv,
                placeholder_text="Visitante",
                font=ctk.CTkFont(size=12), height=30,
                fg_color=row_color,
            )
            ent_visit.grid(row=i + 1, column=3, padx=(3, 4), pady=3, sticky="ew")
            scroll_frame.grid_columnconfigure(3, weight=1)

        # ── Botones ───────────────────────────────────────────────────────────
        btn_bar = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(4, 14))

        ctk.CTkButton(
            btn_bar, text="Cancelar", width=100,
            fg_color="#1a0a0a", hover_color="#2a0f0f",
            command=dlg.destroy,
        ).pack(side="left")

        def _on_load():
            matches = []
            for i, (lv, vv) in enumerate(zip(local_vars, visit_vars), 1):
                loc = lv.get().strip()
                vis = vv.get().strip()
                if not loc and not vis:
                    continue  # omitir filas vacías
                matches.append({
                    "num":         i,
                    "local":       loc or "?",
                    "visitante":   vis or "?",
                    "local_en":    loc or "?",
                    "visitante_en": vis or "?",
                    "url":         "",
                    "fecha_partido": "",
                })

            if len(matches) < 14:
                self.status_lbl.configure(
                    text="⚠  Introduce al menos 14 partidos antes de cargar."
                )
                return

            jornada = jornada_var.get().strip() or "?"
            dlg.destroy()
            # Usar el mismo pipeline de predicciones sin fetch web
            self.status_lbl.configure(
                text=f"⏳  Cargando predicciones para jornada {jornada} (manual)…"
            )
            threading.Thread(
                target=self._enrich_and_populate_worker,
                args=(jornada, matches, "", False),
                daemon=True,
            ).start()

        ctk.CTkButton(
            btn_bar, text="✅  Cargar partidos",
            command=_on_load,
            fg_color=ACCENT, hover_color=ACCENT_2,
        ).pack(side="right")

    # ── Optimizador de boleto ─────────────────────────────────────────────────

    def _open_optimizer_dialog(self) -> None:
        """
        Abre el diálogo de optimización de boleto.

        Calcula la distribución óptima de simples/dobles/triples para maximizar
        P(pleno 15) dentro de un presupuesto dado.
        Requiere que haya partidos cargados con probabilidades del modelo.
        """
        if not self._rows:
            self.status_lbl.configure(
                text="⚠  Carga primero la jornada oficial (📋 Cargar Jornada Oficial)."
            )
            return

        # ── Comprobar que hay probabilidades cargadas ─────────────────────────
        rows_with_probs = [r for r in self._rows if r.p_h > 0]
        if not rows_with_probs:
            self.status_lbl.configure(
                text="⚠  Sin probabilidades del modelo. Ejecuta ▶ Run Analysis "
                     "y luego ⚡ Generar picks IA.",
            )
            return

        # ── Extraer probabilidades ────────────────────────────────────────────
        match_probs_14 = []
        p15_data: tuple[float, float, float, float] | None = None

        for i, r in enumerate(self._rows[:15]):
            if i == 14:
                if r.p_h > 0:
                    p15_data = _pleno15_probs(r.p_h, r.p_d, r.p_a)
                continue
            match_probs_14.append({
                "p_home": r.p_h, "p_draw": r.p_d, "p_away": r.p_a,
            })

        # Rellenar hasta 14 si faltan partidos
        while len(match_probs_14) < 14:
            match_probs_14.append({"p_home": 0.0, "p_draw": 0.0, "p_away": 0.0})

        # ── Construir dialog ──────────────────────────────────────────────────
        dlg = ctk.CTkToplevel(self)
        dlg.title("🎯 Optimizador de Boleto — AlphaBet")
        dlg.geometry("1000x720")
        dlg.resizable(True, True)
        dlg.grab_set()
        dlg.configure(fg_color="#050a12")

        # Presupuesto seleccionado (€)
        budget_var = tk.DoubleVar(value=2.20)

        # ── Cabecera ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(dlg, fg_color="#0a1220", corner_radius=12)
        hdr.pack(fill="x", padx=16, pady=(14, 0))

        ctk.CTkLabel(
            hdr, text="🎯  Optimizador de Boleto",
            text_color="#7dd3fc", font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left", padx=16, pady=10)

        ctk.CTkLabel(
            hdr, text="Maximiza P(pleno 15) + VE del boleto · DP global",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 16), pady=10)

        # ── Selector de presupuesto ───────────────────────────────────────────
        bgt_frame = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=10)
        bgt_frame.pack(fill="x", padx=16, pady=(8, 0))

        ctk.CTkLabel(
            bgt_frame, text="Presupuesto:",
            text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(14, 8), pady=10)

        # Presets de presupuesto → nº de combinaciones
        _presets = [
            (0.55, "0.55€\n(1 comb.)"),
            (1.10, "1.10€\n(2 comb.)"),
            (2.20, "2.20€\n(4 comb.)"),
            (4.40, "4.40€\n(8 comb.)"),
            (8.80, "8.80€\n(16 comb.)"),
            (17.60, "17.60€\n(32 comb.)"),
        ]

        _budget_btns: list[ctk.CTkButton] = []

        def _set_budget(b: float) -> None:
            budget_var.set(b)
            for (bval, _), btn in zip(_presets, _budget_btns):
                is_sel = abs(bval - b) < 0.01
                btn.configure(
                    fg_color    = "#122040" if is_sel else "#0a1220",
                    border_color= "#38bdf8" if is_sel else "#1e3a5f",
                    text_color  = "#e0f2fe" if is_sel else TEXT,
                )
            _refresh_table()

        for bval, blabel in _presets:
            btn = ctk.CTkButton(
                bgt_frame, text=blabel,
                command=lambda bv=bval: _set_budget(bv),
                width=90, height=44,
                fg_color="#0a1220", hover_color="#122040",
                border_color="#1e3a5f", border_width=1,
                text_color=TEXT, font=ctk.CTkFont(size=10),
                corner_radius=8,
            )
            btn.pack(side="left", padx=4, pady=8)
            _budget_btns.append(btn)

        # Presupuesto personalizado
        ctk.CTkLabel(
            bgt_frame, text="o introduce:",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(12, 4), pady=10)

        custom_var = tk.StringVar(value="2.20")
        ctk.CTkEntry(
            bgt_frame, textvariable=custom_var, width=70,
            font=ctk.CTkFont(size=12), fg_color="#070f18",
        ).pack(side="left", padx=(0, 4), pady=10)

        ctk.CTkLabel(bgt_frame, text="€", text_color=MUTED).pack(side="left", pady=10)

        ctk.CTkButton(
            bgt_frame, text="Calcular",
            command=lambda: _set_budget(float(custom_var.get().replace(",", "."))),
            width=80, height=30,
            fg_color=ACCENT, hover_color=ACCENT_2,
        ).pack(side="left", padx=(6, 14), pady=10)

        # ── Tabla comparativa ─────────────────────────────────────────────────
        style = ttk.Style()
        style.configure(
            "Opt.Treeview",
            background="#060e18", fieldbackground="#060e18",
            foreground="#e2f0ff", rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Opt.Treeview.Heading",
            background="#0a1628", foreground="#7dd3fc",
            font=("Segoe UI Semibold", 10),
        )
        style.map("Opt.Treeview",
                  background=[("selected", "#1a3a6a")])

        tree_shell = ctk.CTkFrame(dlg, fg_color="#060e18", corner_radius=12)
        tree_shell.pack(fill="both", expand=True, padx=16, pady=8)
        tree_shell.grid_rowconfigure(0, weight=1)
        tree_shell.grid_columnconfigure(0, weight=1)

        cols = ("#", "local", "visitante",
                "p1", "px", "p2",
                "pick_actual", "pick_opt", "cobertura", "p_ok")
        tree = ttk.Treeview(
            tree_shell, columns=cols, show="headings",
            style="Opt.Treeview", selectmode="none", height=16,
        )
        heads = {
            "#":           ("#",           36),
            "local":       ("Local",       160),
            "visitante":   ("Visitante",   160),
            "p1":          ("P(1)",         55),
            "px":          ("P(X)",         55),
            "p2":          ("P(2)",         55),
            "pick_actual": ("Pick actual",  80),
            "pick_opt":    ("🎯 Óptimo",    80),
            "cobertura":   ("Cobertura",    80),
            "p_ok":        ("P(acertar)",   80),
        }
        for col, (label, width) in heads.items():
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="center")

        tree.tag_configure("single",   foreground="#d6ffe6")
        tree.tag_configure("double",   foreground="#fff0c2")
        tree.tag_configure("triple",   foreground="#ffd3d3")
        tree.tag_configure("p15",      foreground="#c4b5fd")
        tree.tag_configure("odd_row",  background="#060e18")
        tree.tag_configure("even_row", background="#080f1c")

        tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Scrollbar(
            tree_shell, orient="vertical", command=tree.yview,
        ).grid(row=0, column=1, sticky="ns", pady=6)

        # ── Panel de estadísticas ─────────────────────────────────────────────
        stats_frame = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=10)
        stats_frame.pack(fill="x", padx=16, pady=(0, 6))
        stats_frame.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        _stat_keys = [
            ("cost",   "Coste real",        "—"),
            ("combs",  "Combinaciones",     "—"),
            ("p15",    "P(pleno 15)",       "—"),
            ("p14",    "P(14 aciertos)",    "—"),
            ("p13",    "P(13 aciertos)",    "—"),
            ("ev",     "Valor Esperado",    "—"),
        ]
        _stat_lbls: dict[str, ctk.CTkLabel] = {}
        for col, (key, title, _default) in enumerate(_stat_keys):
            box = ctk.CTkFrame(stats_frame, fg_color="#050e1c", corner_radius=10)
            box.grid(row=0, column=col, padx=5, pady=8, sticky="ew")
            ctk.CTkLabel(
                box, text=title, text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).pack(anchor="w", padx=10, pady=(8, 1))
            val_lbl = ctk.CTkLabel(
                box, text="—", text_color="#7dd3fc",
                font=ctk.CTkFont(size=16, weight="bold"),
            )
            val_lbl.pack(anchor="w", padx=10, pady=(0, 8))
            _stat_lbls[key] = val_lbl

        # Nota informativa
        info_lbl = ctk.CTkLabel(
            dlg,
            text="Verde = simple  ·  Amarillo = doble  ·  Rojo = triple  ·  "
                 "Lila = P15",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        info_lbl.pack(pady=(0, 4))

        # ── Botones de acción ─────────────────────────────────────────────────
        btn_bar = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_bar.pack(fill="x", padx=16, pady=(0, 14))

        _apply_state: dict = {"result": None}

        def _apply():
            res = _apply_state.get("result")
            if not res:
                return
            picks = res["picks"]
            for i, r in enumerate(self._rows[:15]):
                if i < len(picks):
                    r.pick_var.set(picks[i])
            self._refresh_tree()   # refresca tabla + KPIs
            dlg.destroy()
            _ev_part = ""
            if res.get("ev") is not None:
                _ev_part = f" · VE {res['ev']:+.2f} €"
            self.status_lbl.configure(
                text=f"🎯 Boleto optimizado aplicado — "
                     f"{res['combinations']} comb. · {res['cost']:.2f} € · "
                     f"P(pleno) {res['p_correct']:.4%}{_ev_part}"
            )

        ctk.CTkButton(
            btn_bar, text="✅  Aplicar al boleto",
            command=_apply,
            fg_color="#0a2210", hover_color="#0f2e14",
            border_color="#22c55e", border_width=1,
            height=38, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_bar, text="❌  Cerrar",
            command=dlg.destroy,
            fg_color="#1a0a0a", hover_color="#2a0f0f",
            height=38,
        ).pack(side="left")

        # Nota sobre cómo leer el resultado
        ctk.CTkLabel(
            btn_bar,
            text="💡  «Aplicar» actualiza tus picks en la tabla principal "
                 "pero no los guarda automáticamente.",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(side="left", padx=16)

        # ── Función de actualización de la tabla ──────────────────────────────
        def _refresh_table() -> None:
            try:
                budget = float(budget_var.get())
            except (ValueError, tk.TclError):
                return

            # Ejecutar optimizador
            try:
                res = _optimize_boleto(match_probs_14, p15_data, budget)
            except Exception as exc:
                for lbl in _stat_lbls.values():
                    lbl.configure(text="Error")
                return

            _apply_state["result"] = res
            opt_picks  = res["picks"]
            opt_cov    = res["coverage"]

            # Limpiar árbol
            for iid in tree.get_children():
                tree.delete(iid)

            # Llenar filas
            for i, r in enumerate(self._rows[:15]):
                is_p15 = (i == 14)
                num_str = "P15" if is_p15 else str(i + 1)

                home = str(r.data.get("home_team", r.data.get("local", "?")))[:22]
                away = str(r.data.get("away_team", r.data.get("visitante", "?")))[:22]

                if is_p15:
                    if r.p_h > 0:
                        p0, p1b, p2b, pMb = _pleno15_probs(r.p_h, r.p_d, r.p_a)
                        p1_s = f"{p0:.0%}"
                        px_s = f"{p1b:.0%}"
                        p2_s = f"{p2b:.0%}+{pMb:.0%}"
                    else:
                        p1_s = px_s = p2_s = "—"
                    if p15_data and opt_picks[i] in ("0", "1", "2", "M"):
                        try:
                            p_ok_val = p15_data[["0", "1", "2", "M"].index(opt_picks[i])]
                        except (ValueError, IndexError):
                            p_ok_val = 0.0
                    else:
                        p_ok_val = 0.0
                else:
                    p1_s = f"{r.p_h:.0%}" if r.p_h > 0 else "—"
                    px_s = f"{r.p_d:.0%}" if r.p_d > 0 else "—"
                    p2_s = f"{r.p_a:.0%}" if r.p_a > 0 else "—"
                    p_ok_val = 0.0
                    if i < len(opt_picks):
                        p_ok_val = _prob_acertar(opt_picks[i], r.p_h, r.p_d, r.p_a)

                curr_pick = r.pick_var.get() if self._rows else "—"
                opt_pick  = opt_picks[i] if i < len(opt_picks) else "—"
                cov_val   = opt_cov[i]   if i < len(opt_cov)   else 1
                cov_str   = _cov_label(cov_val, is_p15)
                p_ok_s    = f"{p_ok_val:.1%}" if p_ok_val > 0 else "—"

                # Tag de color según cobertura
                if is_p15:
                    tag = "p15"
                elif cov_val == 3:
                    tag = "triple"
                elif cov_val == 2:
                    tag = "double"
                else:
                    tag = "single"

                row_bg = "even_row" if i % 2 == 0 else "odd_row"

                tree.insert(
                    "", "end",
                    values=(num_str, home, away,
                            p1_s, px_s, p2_s,
                            curr_pick, opt_pick, cov_str, p_ok_s),
                    tags=(tag, row_bg),
                )

            # Actualizar estadísticas
            _stat_lbls["cost"].configure(text=f"{res['cost']:.2f} €")
            _stat_lbls["combs"].configure(text=str(res["combinations"]))
            p_c = res["p_correct"]
            p14 = res["p_14"]
            p13 = res["p_13"]

            # Escala adaptativa para P(pleno) — puede ser muy pequeña
            if p_c >= 0.001:
                _stat_lbls["p15"].configure(text=f"{p_c:.3%}")
            elif p_c >= 0.0001:
                _stat_lbls["p15"].configure(text=f"{p_c:.4%}")
            else:
                _stat_lbls["p15"].configure(text=f"{p_c:.2e}")

            _stat_lbls["p14"].configure(text=f"{p14:.3%}" if p14 >= 0.001 else f"{p14:.2e}")
            _stat_lbls["p13"].configure(text=f"{p13:.2%}" if p13 >= 0.001 else f"{p13:.2e}")

            # Valor Esperado
            ev = res.get("ev")
            if ev is not None:
                if ev >= 0:
                    ev_txt = f"+{ev:.2f} €"
                    ev_col = "#4ade80"
                else:
                    ev_txt = f"{ev:.2f} €"
                    ev_col = "#f87171"
                _stat_lbls["ev"].configure(text=ev_txt, text_color=ev_col)
            else:
                _stat_lbls["ev"].configure(text="—")

        # Highlight del botón por defecto (2.20€)
        _set_budget(2.20)

    # ── Carga jornada oficial SELAE ───────────────────────────────────────────

    def load_official(self) -> None:
        """Descarga la jornada oficial en hilo de fondo para no bloquear la UI."""
        self.status_lbl.configure(text="⏳  Descargando jornada oficial de La Quiniela…")
        threading.Thread(target=self._fetch_official_worker, daemon=True).start()

    def _fetch_official_worker(self) -> None:
        """
        Hilo de fondo — pipeline completo de la jornada oficial:
          1. SELAE  → 15 partidos oficiales (scraping)
          2. Enriquece con ELO + Odds API + ML (via _enrich_and_populate_worker)
        """
        data = fetch_quiniela_fixture(timeout=20)
        if not data:
            self.app.after(0, lambda: self.status_lbl.configure(
                text="⚠  No se pudo obtener la jornada oficial. Comprueba la conexión."
            ))
            return

        self._enrich_and_populate_worker(
            jornada=data["jornada"],
            matches=data["matches"],
            fecha=data.get("fecha", ""),
            ya_jugada=data.get("ya_jugada", False),
            jornada_anterior=data.get("jornada_anterior", ""),
        )

    def _enrich_and_populate_worker(
        self,
        jornada: str,
        matches: list[dict],
        fecha: str = "",
        ya_jugada: bool = False,
        jornada_anterior: str = "",
    ) -> None:
        """
        Hilo de fondo compartido por carga automática y entrada manual.
        Enriquece los partidos con Odds API + Club ELO + ELO nacional + ML
        y luego llama a _populate_official en el hilo principal.
        """
        # ── 1. Cuotas en tiempo real (The Odds API) ───────────────────────────
        api_key = self.app.storage.get_setting("odds_api_key", "")
        if api_key:
            self.app.after(0, lambda: self.status_lbl.configure(
                text="⏳  Obteniendo cuotas en tiempo real (The Odds API)…"
            ))
            matches = enrich_with_api_odds(matches, api_key, timeout=12)
        else:
            self.app.after(0, lambda: self.status_lbl.configure(
                text="⏳  Cargando ratings Elo… (sin API key — configúrala en ⚙️ Strategy)"
            ))

        # ── 2. Club ELO (clubelo.com) para partidos de clubes sin cuotas ──────
        self.app.after(0, lambda: self.status_lbl.configure(
            text="⏳  Cargando Club ELO (clubelo.com)…"
        ))
        from ...core.club_elo import ClubEloModel
        club_elo = ClubEloModel()
        club_elo.load(timeout=8)

        # ── 3. ELO nacional para selecciones (fallback final) ─────────────────
        self.app.after(0, lambda: self.status_lbl.configure(
            text="⏳  Cargando ratings Elo de selecciones…"
        ))
        elo = EloModel()
        elo.load_ratings(timeout=6)

        # match_with_predictions: Odds API → ML → Club ELO → ELO nacional
        enriched = match_with_predictions(
            matches, results_df=None,
            elo_model=elo, club_elo_model=club_elo,
        )

        # ── 4. Opcional: re-enriquecer con ML si el Trading Desk ya fue ejecutado
        raw_df = getattr(self.app, "results", None)
        if raw_df is not None and not raw_df.empty:
            future_df = self.app._future_results_only(raw_df)
            if not future_df.empty:
                enriched = _upgrade_with_ml(enriched, future_df)

        self.app.after(
            0,
            lambda: self._populate_official(
                jornada, enriched, fecha,
                ya_jugada=ya_jugada,
                jornada_anterior=jornada_anterior,
            ),
        )

    def _populate_official(
        self,
        jornada: str,
        matches: list[dict],
        fecha: str = "",
        ya_jugada: bool = False,
        jornada_anterior: str = "",
    ) -> None:
        """Llamado en el hilo principal tras recibir los datos oficiales."""
        self._jornada_fecha = fecha
        self._rows = []
        for m in matches:
            row_data = {
                "home_team":    m["local"],
                "home_team_en": m.get("local_en", m["local"]),
                "away_team":    m["visitante"],
                "away_team_en": m.get("visitante_en", m["visitante"]),
                "league":       "Quiniela Oficial",
                "date":         "",
                "p_home":       m.get("p_home"),
                "p_draw":       m.get("p_draw"),
                "p_away":       m.get("p_away"),
                "p_source":     m.get("p_source"),   # "ml", "elo", or None
                "elo_home":     m.get("elo_home"),
                "elo_away":     m.get("elo_away"),
                "pick":         m.get("model_pick") or "NO BET",
                "odds":         m.get("odds_h"),
                "B365H":        m.get("odds_h"),
                "B365D":        m.get("odds_d"),
                "B365A":        m.get("odds_a"),
                "reliability_score": m.get("reliability", 0),
            }
            row = QuilineaRow(pd.Series(row_data))
            self._rows.append(row)

        self._apply_picks()
        self._refresh_tree()

        with_ml   = sum(1 for r in self._rows if r.data.get("p_source") == "ml")
        with_odds = sum(1 for r in self._rows if r.data.get("p_source") == "odds_api")
        with_celo = sum(1 for r in self._rows if r.data.get("p_source") == "club_elo")
        with_elo  = sum(1 for r in self._rows if r.data.get("p_source") == "elo")
        no_pred   = len(matches) - with_ml - with_odds - with_celo - with_elo

        parts = [f"✓  Jornada {jornada} · {len(matches)} partidos"]
        if with_ml:   parts.append(f"{with_ml} ML")
        if with_odds: parts.append(f"{with_odds} cuotas")
        if with_celo: parts.append(f"{with_celo} ClubELO")
        if with_elo:  parts.append(f"{with_elo} ELO nac.")
        if no_pred:   parts.append(f"{no_pred} sin predicción")
        status_text = " · ".join(parts)

        # ── Aviso si la jornada ya fue jugada ─────────────────────────────────
        if ya_jugada:
            prev = f" (jornada {jornada_anterior})" if jornada_anterior and jornada_anterior != "?" else ""
            status_text = (
                f"⚠  Jornada {jornada} aún no publicada en SELAE — "
                f"mostrando última jornada jugada{prev}. "
                f"Vuelve a intentarlo cuando SELAE publique la nueva jornada (normalmente martes/miércoles)."
            )

        self.status_lbl.configure(text=status_text)

        # ── Auto-trigger ML si hay muchos partidos sin predicción ─────────────
        if no_pred >= 3 and not ya_jugada:
            self.app.after(400, self._auto_trigger_ml)

        # Actualizar caché del bot (hilo principal — acceso seguro a widgets)
        if hasattr(self.app, "update_bot_cache"):
            self.app.after(100, self.app.update_bot_cache)

    # ── Generación IA ─────────────────────────────────────────────────────────

    def generate_ai(self, df: pd.DataFrame | None = None) -> None:
        """
        Genera/refresca picks IA.

        Fuente de partidos: siempre la jornada oficial de SELAE (cargada con 📋).
        Fuente de predicciones (orden de prioridad):
          1. The Odds API (cuotas reales)
          2. ML del Trading Desk si ya se ejecutó el análisis (opcional)
          3. ELO ratings (fallback)

        Si la jornada aún no está cargada → pide al usuario que la cargue primero.
        """
        if not self._rows:
            self.status_lbl.configure(
                text="⚠  Pulsa 📋 Cargar Jornada Oficial para obtener los partidos de SELAE."
            )
            return

        # Re-enriquecer con ML si el análisis principal fue ejecutado recientemente
        if df is None:
            df = getattr(self.app, "results", None)
        if df is not None and not df.empty:
            future_df = self.app._future_results_only(df)
            if not future_df.empty:
                self._enrich_from_analysis(future_df)

        # Contar fuentes y aplicar picks
        src_counts: dict[str, int] = {}
        for r in self._rows:
            src = r.data.get("p_source") or "sin datos"
            src_counts[src] = src_counts.get(src, 0) + 1

        self._apply_picks()
        self._refresh_tree()

        src_parts = []
        if src_counts.get("ml"):        src_parts.append(f"{src_counts['ml']} ML")
        if src_counts.get("odds_api"):  src_parts.append(f"{src_counts['odds_api']} cuotas")
        if src_counts.get("elo"):       src_parts.append(f"{src_counts['elo']} Elo")
        if src_counts.get("sin datos"): src_parts.append(f"{src_counts['sin datos']} sin datos")

        n    = self._n_doubles.get()
        mode = f"{n} doble{'s' if n > 1 else ''}" if n > 0 else "modo auto"
        self.status_lbl.configure(
            text=f"✓  Picks generados ({mode}) · " + " · ".join(src_parts)
        )
        # Refrescar caché del bot con los picks actualizados
        if hasattr(self.app, "update_bot_cache"):
            self.app.after(100, self.app.update_bot_cache)

    def _enrich_from_analysis(self, df: pd.DataFrame) -> None:
        """
        Re-enriquece las filas existentes con predicciones ML (opcional).
        Solo actúa si el Trading Desk fue ejecutado y hay partidos futuros con predicciones.
        df debe llegar ya filtrado por fecha.
        """
        raw = [
            {
                "local":        str(r.data.get("home_team", "")),
                # home_team_en tiene el nombre en inglés guardado en _populate_official
                "local_en":     str(r.data.get("home_team_en",
                                               r.data.get("home_team", ""))),
                "visitante":    str(r.data.get("away_team", "")),
                "visitante_en": str(r.data.get("away_team_en",
                                               r.data.get("away_team", ""))),
            }
            for r in self._rows
        ]
        enriched = match_with_predictions(raw, df)

        for r, m in zip(self._rows, enriched):
            ph  = m.get("p_home")
            pd_ = m.get("p_draw")
            pa  = m.get("p_away")
            if ph is not None and pd.notna(ph) and float(ph) > 0:
                r.p_h = float(ph)
                r.p_d = float(pd_) if (pd_ is not None and pd.notna(pd_)) else 0.0
                r.p_a = float(pa)  if (pa  is not None and pd.notna(pa))  else 0.0
            else:
                # Fallback: usar probabilidades implícitas de las cuotas si existen
                oh = r.data.get("B365H")
                od = r.data.get("B365D")
                oa = r.data.get("B365A")
                if oh and od and oa and float(oh) > 1:
                    tot = 1/float(oh) + 1/float(od) + 1/float(oa)
                    r.p_h = round((1/float(oh)) / tot, 4)
                    r.p_d = round((1/float(od)) / tot, 4)
                    r.p_a = round((1/float(oa)) / tot, 4)

    # ── Selector de dobles ────────────────────────────────────────────────────

    def _highlight_doubles_btn(self, selected: int) -> None:
        """Resalta el botón activo y apaga los demás."""
        for v, btn in self._doubles_btns.items():
            if v == selected:
                btn.configure(
                    fg_color="#0f4a20", border_color="#22c55e",
                    text_color="#4ade80",
                )
            else:
                btn.configure(
                    fg_color="#0a120a", border_color="#1a3a1a",
                    text_color=TEXT,
                )

    def _set_doubles(self, n: int) -> None:
        """Selecciona el número de dobles y actualiza UI + picks."""
        self._n_doubles.set(n)
        self._highlight_doubles_btn(n)
        self._on_doubles_change(float(n))

    def _on_doubles_seg(self, value: str) -> None:
        """Compatibilidad — no usado desde la nueva UI."""
        n = 0 if value == "Auto" else int(value)
        self._set_doubles(n)

    def _step_doubles(self, delta: int) -> None:
        """Mueve el selector de dobles en ±1."""
        n = max(0, min(5, self._n_doubles.get() + delta))
        self._set_doubles(n)

    def _on_doubles_change(self, val: float) -> None:
        """Re-aplica picks IA con el nuevo número de dobles."""
        n = int(round(float(val)))
        self._n_doubles.set(n)
        if self._rows:
            self._apply_picks()
            self._refresh_tree()

    def _apply_picks(self) -> None:
        """Aplica picks a todas las filas según el nº de dobles seleccionado."""
        n  = self._n_doubles.get()
        qp = self._q_params  # parámetros calibrados activos

        # prior histórico: usa las tasas empíricas calibradas si están disponibles
        ph0 = qp.get("home_rate", 0.45)
        pd0 = qp.get("draw_rate", 0.27)
        pa0 = qp.get("away_rate", 0.28)

        # ── Partidos 1-14 (resultado 1/X/2) ──────────────────────────────────
        rows_14 = self._rows[:14]
        if n == 0:
            for r in rows_14:
                r.pick_var.set(
                    _ai_pick(r.p_h, r.p_d, r.p_a, qp) if r.p_h > 0
                    else _ai_pick(ph0, pd0, pa0, qp)
                )
        else:
            for r, pick in zip(rows_14, _picks_for_n_doubles(rows_14, n, qp)):
                r.pick_var.set(pick)

        # ── Partido 15 — Pleno al 15 (goles: 0/1/2/M) ────────────────────────
        if len(self._rows) >= 15:
            r15 = self._rows[14]
            r15.pick_var.set(_pleno15_pick_ai(r15.p_h, r15.p_d, r15.p_a))

    def _on_tree_select(self, event=None) -> None:
        """Actualiza el pick selector Y el panel de detalle del partido seleccionado."""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])

        # ── Pick selector ─────────────────────────────────────────────────────
        if idx == 14:  # Pleno al 15
            self._pick_menu.configure(values=PLENO15_OPTIONS)
            if len(self._rows) > 14:
                cur = self._rows[14].pick_var.get()
                self._edit_var.set(cur if cur in PLENO15_OPTIONS else "1")
        else:
            self._pick_menu.configure(values=self.PICK_OPTIONS)
            if 0 <= idx < len(self._rows):
                self._edit_var.set(self._rows[idx].pick_var.get())

        if not (0 <= idx < len(self._rows)):
            return
        r   = self._rows[idx]
        p_h = r.p_h
        p_d = r.p_d
        p_a = r.p_a

        # ── Detail panel: nombre del partido ─────────────────────────────────
        home = str(r.data.get("home_team", "?"))
        away = str(r.data.get("away_team", "?"))
        num_str = "P15" if idx == 14 else str(idx + 1)
        self._detail_match_lbl.configure(
            text=f"  #{num_str}  {home}  vs  {away}",
            text_color="#7dd3fc",
            font=ctk.CTkFont(size=12, weight="bold"),
        )

        # ── Detail panel: barras de probabilidad ─────────────────────────────
        if p_h > 0 and idx < 14:
            bar1 = self._prob_bar(p_h)
            barX = self._prob_bar(p_d)
            bar2 = self._prob_bar(p_a)
            prob_text = f"  1 {bar1}   X {barX}   2 {bar2}"
            self._detail_prob_lbl.configure(text=prob_text, text_color="#4ade80")
        elif p_h > 0 and idx == 14:
            p0, p1b, p2b, pM = _pleno15_probs(p_h, p_d, p_a)
            prob_text = (
                f"  0-1 {self._prob_bar(p0, 8)}   "
                f"2-3 {self._prob_bar(p1b, 8)}   "
                f"4-5 {self._prob_bar(p2b, 8)}   "
                f"6+ {self._prob_bar(pM, 8)}"
            )
            self._detail_prob_lbl.configure(text=prob_text, text_color="#c4b5fd")
        else:
            self._detail_prob_lbl.configure(
                text="  Sin datos de probabilidad — usa 📋 Jornada + ⚡ Picks IA",
                text_color=MUTED,
            )

        # ── Detail panel: razón Claude / fuente ──────────────────────────────
        source     = r.data.get("p_source") or "—"
        claude_rea = r.data.get("claude_reason") or ""
        claude_con = r.data.get("claude_confidence")

        if source == "claude" and claude_rea:
            stars = "★" * int(claude_con) if claude_con else ""
            reason_txt = f"🧠 Claude {stars}: {claude_rea}"
            self._detail_reason_lbl.configure(text=reason_txt, text_color="#a78bfa")
        elif source == "ml":
            best_p  = max(p_h, p_d, p_a) if p_h > 0 else 0
            best_lbl = "1 Local" if p_h == max(p_h, p_d, p_a) else ("X Empate" if p_d == max(p_h, p_d, p_a) else "2 Visita")
            self._detail_reason_lbl.configure(
                text=f"🔬 Modelo ML · Favorito: {best_lbl} ({best_p:.0%})",
                text_color="#67e8f9",
            )
        elif source in ("club_elo", "elo"):
            elo_h = r.data.get("elo_home", "")
            elo_a = r.data.get("elo_away", "")
            elo_txt = f"  ELO: {home}={elo_h}  ·  {away}={elo_a}" if elo_h else "  Ratings ELO"
            self._detail_reason_lbl.configure(text=elo_txt, text_color="#94a3b8")
        elif source == "odds_api":
            bh = r.data.get("B365H") or "—"
            bd = r.data.get("B365D") or "—"
            ba = r.data.get("B365A") or "—"
            self._detail_reason_lbl.configure(
                text=f"  Cuotas: {bh} / {bd} / {ba}  (The Odds API)",
                text_color="#fbbf24",
            )
        else:
            self._detail_reason_lbl.configure(
                text="  Sin fuente de predicción. Ejecuta ⚡ Picks IA o 🔬 ML.",
                text_color=MUTED,
            )

        # Badge de fuente
        _src_map = {
            "claude":    ("🧠 Claude",    "#a78bfa"),
            "ml":        ("🔬 ML",        "#67e8f9"),
            "club_elo":  ("ELO Club",     "#94a3b8"),
            "elo":       ("ELO Nac.",     "#94a3b8"),
            "odds_api":  ("API Odds",     "#fbbf24"),
        }
        badge, badge_col = _src_map.get(source, ("Sin datos", MUTED))
        self._detail_src_lbl.configure(text=badge, text_color=badge_col)

    def clear_picks(self) -> None:
        for i, r in enumerate(self._rows):
            r.pick_var.set("1" if i != 14 else "1")   # Pleno al 15: "1" (2-3 goles, más probable)
        self._refresh_tree()

    # ── Análisis profundo IA (Claude) ────────────────────────────────────────

    def _start_deep_claude_analysis(self) -> None:
        """
        Análisis profundo con Claude: analiza los 15 partidos partido a partido,
        mezcla sus predicciones con las probs del modelo y regenera los picks
        respetando el número de dobles elegido por el usuario.
        """
        if not self._rows:
            self.status_lbl.configure(text="⚠  Carga primero la jornada oficial.")
            return
        api_key = self.app.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            self.status_lbl.configure(
                text="⚠  Configura la API key de Claude en ⚙️ Strategy para usar el análisis IA."
            )
            return
        self._claude_q_btn.configure(state="disabled", text="⏳ Analizando…")
        self.status_lbl.configure(text="🧠  Claude analizando los 15 partidos en profundidad…")
        threading.Thread(
            target=self._deep_claude_worker,
            args=(api_key,),
            daemon=True,
        ).start()

    def _build_deep_prompt(self) -> str:
        """
        Construye el prompt para el análisis profundo de los 15 partidos.
        Incluye equipos, probabilidades del modelo, cuotas y el nº de dobles elegido.
        """
        lines = [
            "Eres un analista experto en fútbol y La Quiniela española (SELAE). "
            "Tu misión es predecir con la máxima precisión los 15 partidos de la jornada.",
            "",
            "Usa TODO tu conocimiento de los equipos, ligas, forma reciente, rivalidades "
            "y posición en tabla. Contrasta con las probabilidades del modelo IA y las "
            "cuotas de mercado cuando estén disponibles. "
            "Si discrepas del modelo, refléjalo con confianza baja (1 o 2).",
            "",
            "PARTIDOS DE LA JORNADA:",
        ]

        for i, r in enumerate(self._rows, 1):
            home = r.data.get("home_team", "?")
            away = r.data.get("away_team", "?")
            src  = r.data.get("p_source") or "sin datos"
            parts = [f"{i:2d}. {home} vs {away}"]

            if r.p_h > 0:
                parts.append(
                    f"modelo({src}): {r.p_h:.0%}/{r.p_d:.0%}/{r.p_a:.0%}"
                )
            try:
                bh = float(r.data.get("B365H") or 0)
                bd = float(r.data.get("B365D") or 0)
                ba = float(r.data.get("B365A") or 0)
                if bh > 1 and bd > 1 and ba > 1:
                    parts.append(f"cuotas: {bh:.2f}/{bd:.2f}/{ba:.2f}")
            except (TypeError, ValueError):
                pass

            lines.append("  ".join(parts))

        n = self._n_doubles.get()
        lines += [
            "",
            f"El usuario jugará {n} doble{'s' if n != 1 else ''} "
            + ("(los partidos más inciertos recibirán doble cobertura)."
               if n > 0 else "(modo auto — IA decide los dobles)."),
            "",
            "ESCALA DE CONFIANZA (1–5):",
            "5 = muy seguro — favorito muy claro, cuota baja, sin sorpresas esperadas",
            "4 = probable    — ligera ventaja, alguna incertidumbre",
            "3 = moderado   — partido equilibrado con leve favorito",
            "2 = incierto   — ambos equipos con opciones reales",
            "1 = muy incierto — empate o sorpresa muy posible, cualquier resultado válido",
            "",
            "IMPORTANTE: Los partidos de menor confianza serán candidatos al doble.",
            "Responde ÚNICAMENTE con JSON válido (sin texto antes ni después):",
            '{"partidos": [{"num": 1, "resultado": "1", "confianza": 4, '
            '"razon": "frase corta"}, ...], "resumen": "una frase sobre la jornada"}',
            "",
            "resultado: '1' local gana · 'X' empate · '2' visitante gana",
        ]
        return "\n".join(lines)

    def _deep_claude_worker(self, api_key: str) -> None:
        """Hilo de fondo: llama a Claude, parsea la respuesta JSON y la aplica."""
        import json as _json
        import re  as _re

        try:
            import anthropic
            from ...core.ai_analysis import _MODELS_PREFERRED, _track

            prompt      = self._build_deep_prompt()
            client      = anthropic.Anthropic(api_key=api_key)
            result_text = None
            used_model  = None

            for model in _MODELS_PREFERRED:
                try:
                    msg = client.messages.create(
                        model=model,
                        max_tokens=1400,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    result_text = msg.content[0].text.strip()
                    _track(model, msg.usage.input_tokens, msg.usage.output_tokens)
                    used_model = model
                    break
                except anthropic.NotFoundError:
                    continue

            if not result_text:
                raise ValueError("Claude no devolvió respuesta")

            # Extraer JSON aunque venga envuelto en ```json ... ```
            json_match = _re.search(r'\{.*\}', result_text, _re.DOTALL)
            if not json_match:
                raise ValueError("No se encontró JSON válido en la respuesta")

            data = _json.loads(json_match.group())
            self.app.after(0, lambda d=data, m=used_model: self._apply_claude_analysis(d, m))
            self.app.after(0, self.app._update_claude_counter)

        except Exception as exc:
            self.app.after(0, lambda e=exc: (
                self._claude_q_btn.configure(state="normal", text="🧠 IA Profundo"),
                self.status_lbl.configure(text=f"⚠  Error en análisis IA: {e}"),
            ))

    def _apply_claude_analysis(self, data: dict, model_name: str) -> None:
        """
        Aplica el análisis de Claude al hilo principal:
          1. Mezcla probabilidades Claude + modelo
          2. Marca la fuente como 'claude'
          3. Regenera picks respetando el slider de dobles
        """
        try:
            partidos  = data.get("partidos", data.get("matches", []))
            resumen   = data.get("resumen",  data.get("summary", ""))
            n_updated = 0

            for item in partidos:
                num       = int(item.get("num", 0)) - 1          # 0-indexed
                resultado = str(item.get("resultado",
                                         item.get("result", "1"))).upper()
                if resultado not in ("1", "X", "2"):
                    resultado = "1"
                confianza = max(1, min(5, int(item.get("confianza",
                                                        item.get("confidence", 3)))))
                razon     = str(item.get("razon", item.get("reason", "")))

                if 0 <= num < len(self._rows):
                    r = self._rows[num]
                    new_ph, new_pd, new_pa = _blend_with_claude(
                        r.p_h, r.p_d, r.p_a, resultado, confianza,
                    )
                    r.p_h = new_ph
                    r.p_d = new_pd
                    r.p_a = new_pa

                    new_data = r.data.to_dict()
                    new_data["p_source"]          = "claude"
                    new_data["claude_result"]     = resultado
                    new_data["claude_confidence"] = confianza
                    new_data["claude_reason"]     = razon
                    r.data = pd.Series(new_data)
                    n_updated += 1

            # Regenerar picks con el estado actualizado (respeta slider de dobles)
            self._apply_picks()
            self._refresh_tree()

            self._claude_q_btn.configure(state="normal", text="🧠 IA Profundo")

            n     = self._n_doubles.get()
            mode  = f"{n} doble{'s' if n != 1 else ''}" if n > 0 else "auto"
            mname = (model_name or "").split("-")
            short = mname[1] if len(mname) > 1 else (model_name or "claude")
            msg   = f"✓ Claude ({short}) · {n_updated}/15 partidos · modo {mode}"
            if resumen:
                msg += f"  —  {resumen}"
            self.status_lbl.configure(text=msg)

            if hasattr(self.app, "update_bot_cache"):
                self.app.after(100, self.app.update_bot_cache)

        except Exception as exc:
            self._claude_q_btn.configure(state="normal", text="🧠 IA Profundo")
            self.status_lbl.configure(text=f"⚠  Error al aplicar análisis: {exc}")

    def export_picks(self) -> None:
        """Exporta la quiniela formateada a un archivo .txt."""
        if not self._rows:
            self.status_lbl.configure(text="⚠  No hay partidos cargados para exportar.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Guardar quiniela",
        )
        if not path:
            return

        # Calcular combinaciones y coste
        total_mult = 1
        total_prob = 1.0
        has_probs  = True
        for i, r in enumerate(self._rows):
            pick = r.pick_var.get()
            total_mult *= MULT.get(pick, 1)
            prob = (_prob_acertar_pleno15(pick, r.p_h, r.p_d, r.p_a)
                    if i == 14
                    else _prob_acertar(pick, r.p_h, r.p_d, r.p_a))
            if prob <= 0:
                has_probs = False
            total_prob *= prob
        coste = round(total_mult * COSTE_BASE, 2)
        prob_str = f"{total_prob:.3%}" if has_probs and self._rows else "?"

        # Detectar jornada desde el status label si está disponible
        status_text = self.status_lbl.cget("text") if hasattr(self.status_lbl, "cget") else ""
        jornada = "?"
        import re
        m = re.search(r"Jornada\s+(\S+)", status_text)
        if m:
            jornada = m.group(1)

        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        sep = "═" * 55

        lines = [
            sep,
            f"QUINIELA IA — {today} — Jornada {jornada}",
            sep,
        ]
        for i, r in enumerate(self._rows):
            pick = r.pick_var.get()
            home = r.data.get("home_team", "?")
            away = r.data.get("away_team", "?")
            if i == 14:   # Pleno al 15: mostrar rangos de goles
                if r.p_h > 0:
                    p0, p1b, p2b, pMb = _pleno15_probs(r.p_h, r.p_d, r.p_a)
                    prob_str = f"0:{p0:.0%} 1:{p1b:.0%} 2:{p2b:.0%} M:{pMb:.0%}"
                else:
                    prob_str = "sin datos"
                lines.append(
                    f"{i+1:>2}. {home:<20} vs {away:<20} [{pick:^3}]  "
                    f"[Pleno al 15 — goles] ({prob_str})"
                )
            else:
                ph_s = f"{r.p_h:.0%}" if r.p_h > 0 else "  ?"
                pd_s = f"{r.p_d:.0%}" if r.p_d > 0 else "  ?"
                pa_s = f"{r.p_a:.0%}" if r.p_a > 0 else "  ?"
                lines.append(
                    f"{i+1:>2}. {home:<20} vs {away:<20} [{pick:^3}]  "
                    f"({ph_s}/{pd_s}/{pa_s})"
                )
        # Marcador exacto predicho para partido 15
        pleno15_line = ""
        if len(self._rows) >= 15:
            r15 = self._rows[14]
            scores = _predict_exact_scores(r15.p_h, r15.p_d, r15.p_a)
            if scores:
                parts = [f"{gh}-{ga}({p:.1%})" for gh, ga, p in scores[:5]]
                pleno15_line = "Pleno al 15 (marcador): " + "  ".join(parts)

        lines += [
            sep,
            f"Combinaciones: {total_mult} · Coste: {coste:.2f} €",
            f"P(pleno): {prob_str}",
        ]
        if pleno15_line:
            lines.append(pleno15_line)
        lines.append(sep)

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.status_lbl.configure(text=f"✓  Quiniela exportada → {path}")
        except OSError as exc:
            self.status_lbl.configure(text=f"⚠  Error al guardar: {exc}")

    # ── Edición de picks ──────────────────────────────────────────────────────

    # ── ML directo ────────────────────────────────────────────────────────────

    def _auto_trigger_ml(self) -> None:
        """
        Lanza ML directo automáticamente cuando la jornada oficial tiene
        3+ partidos sin predicción. Solo actúa si el botón está disponible.
        """
        try:
            state = self._ml_btn.cget("state")
        except Exception:
            state = "normal"
        if str(state) == "disabled":
            return  # ya está analizando
        self.status_lbl.configure(
            text="⚡  Auto-analizando con ML (partidos sin predicción detectados)…"
        )
        self._start_direct_ml()

    def _start_direct_ml(self) -> None:
        """
        Descarga SP1/SP2 y genera predicciones ML para la quiniela
        sin necesidad de haber ejecutado el Trading Desk previamente.

        Flujo:
          1. Descarga CSV histórico de SP1 y SP2 (football-data.co.uk)
          2. Descarga fixtures actuales
          3. Entrena / carga el modelo v12
          4. Genera predicciones para los partidos de la quiniela
          5. Actualiza la tabla de la quiniela con las nuevas probabilidades
        """
        if not self._rows:
            self.status_lbl.configure(
                text="⚠  Carga primero la jornada oficial (📋 Cargar Jornada Oficial)."
            )
            return
        self._ml_btn.configure(state="disabled", text="⏳ Analizando…")
        self.status_lbl.configure(text="⏳  Iniciando análisis ML para SP1/SP2…")
        import threading
        threading.Thread(target=self._direct_ml_worker, daemon=True).start()

    def _direct_ml_worker(self) -> None:
        """Hilo de fondo: descarga datos y ejecuta el modelo ML para la quiniela."""
        import logging as _log
        _logger = _log.getLogger(__name__)
        try:
            from ...core.analyzer import Analyzer
            from ...core.data import fetch_csv
            from ...core.config import LEAGUE_MAP, FIXTURES_URL

            def _status(msg: str) -> None:
                self.app.after(0, lambda m=msg: self.status_lbl.configure(text=f"⏳ {m}"))

            # ── Descargar histórico SP1 y SP2 ─────────────────────────────────
            hist: dict = {}
            for league_name in ["La Liga", "Segunda"]:
                div, csv_url, _ = LEAGUE_MAP[league_name]
                if csv_url:
                    _status(f"Descargando {league_name}…")
                    try:
                        hist[div] = fetch_csv(csv_url)
                    except Exception as exc:
                        _logger.warning("ML directo: error descargando %s: %s", league_name, exc)

            if not hist:
                self.app.after(0, lambda: self.status_lbl.configure(
                    text="⚠  No se pudieron descargar datos de SP1/SP2. Comprueba la conexión."
                ))
                return

            # ── Fixtures actuales ─────────────────────────────────────────────
            _status("Descargando fixtures…")
            try:
                fixtures_df = fetch_csv(FIXTURES_URL)
            except Exception as exc:
                _logger.warning("ML directo: error fixtures: %s", exc)
                self.app.after(0, lambda: self.status_lbl.configure(
                    text="⚠  Error al descargar los fixtures. Comprueba la conexión."
                ))
                return

            # ── Entrenar / cargar modelo ──────────────────────────────────────
            _status("Cargando/entrenando modelo ML v12…")
            analyzer = Analyzer(hist, fixtures_df)
            results  = analyzer.run(
                list(hist.keys()),
                edge_1x2 = 0.03,
                edge_ou  = 0.03,
                progress_cb = lambda m: _status(m),
            )

            if results.empty:
                self.app.after(0, lambda: self.status_lbl.configure(
                    text="⚠  El modelo no generó predicciones. Quizás no hay fixtures de SP1/SP2."
                ))
                return

            # ── Actualizar filas de la quiniela ───────────────────────────────
            self.app.after(0, lambda r=results: self._apply_ml_results(r))

        except Exception as exc:
            _logger.exception("ML directo quiniela: error inesperado")
            self.app.after(0, lambda e=exc: self.status_lbl.configure(
                text=f"⚠  Error en ML directo: {e}"
            ))
        finally:
            self.app.after(0, lambda: self._ml_btn.configure(
                state="normal", text="🔬 ML directo"
            ))

    def _apply_ml_results(self, results: pd.DataFrame) -> None:
        """
        Aplica predicciones ML a las filas de la quiniela (hilo principal).
        Solo actualiza los partidos que se encuentran en el DataFrame de resultados.
        """
        from ...core.quiniela_lae import normalize as _norm

        df = results.copy()
        df["_nh"] = df["home_team"].astype(str).map(_norm)
        df["_na"] = df["away_team"].astype(str).map(_norm)

        updated = 0
        for r in self._rows:
            local_norms = {
                _norm(str(r.data.get("home_team",    ""))),
                _norm(str(r.data.get("home_team_en", r.data.get("home_team", "")))),
            }
            visit_norms = {
                _norm(str(r.data.get("away_team",    ""))),
                _norm(str(r.data.get("away_team_en", r.data.get("away_team", "")))),
            }
            local_norms.discard("")
            visit_norms.discard("")

            found = None
            for _, row in df.iterrows():
                home_ok = any(ln and (ln in row["_nh"] or row["_nh"] in ln) for ln in local_norms)
                away_ok = any(vn and (vn in row["_na"] or row["_na"] in vn) for vn in visit_norms)
                if home_ok and away_ok:
                    found = row
                    break

            if found is not None and found.get("p_home") is not None:
                ph = float(found.get("p_home") or 0)
                pd_ = float(found.get("p_draw") or 0)
                pa  = float(found.get("p_away") or 0)
                if ph > 0:
                    r.p_h = ph
                    r.p_d = pd_
                    r.p_a = pa
                    # Actualizar metadatos de la fila
                    new_data = r.data.to_dict()
                    new_data["p_source"]        = "ml"
                    new_data["reliability_score"] = float(found.get("reliability_score", 0) or 0)
                    new_data["B365H"]            = found.get("B365H")
                    new_data["B365D"]            = found.get("B365D")
                    new_data["B365A"]            = found.get("B365A")
                    r.data = pd.Series(new_data)
                    updated += 1

        self._apply_picks()
        self._refresh_tree()

        with_ml      = sum(1 for r in self._rows if r.data.get("p_source") == "ml")
        with_celo    = sum(1 for r in self._rows if r.data.get("p_source") == "club_elo")
        with_elo     = sum(1 for r in self._rows if r.data.get("p_source") == "elo")
        no_pred      = len(self._rows) - with_ml - with_celo - with_elo

        parts = [f"✓  ML directo · {updated} partidos actualizados"]
        if with_celo: parts.append(f"{with_celo} ClubELO")
        if with_elo:  parts.append(f"{with_elo} ELO nacional")
        if no_pred:   parts.append(f"{no_pred} sin predicción")
        self.status_lbl.configure(text=" · ".join(parts))

    def _apply_pick_edit(self, _value: str = "") -> None:
        """Aplica el pick del menú a la fila seleccionada en el Treeview."""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._rows):
            new_pick = self._edit_var.get()
            self._rows[idx].pick_var.set(new_pick)
            self._refresh_tree()
            self.tree.selection_set(str(idx))
            self._on_tree_select()   # refresca panel de detalle

    # ── Refresco de tabla y KPIs ──────────────────────────────────────────────

    @staticmethod
    def _prob_bar(p: float, width: int = 10) -> str:
        """Mini barra de probabilidad en texto — '████░░░░░░ 42%'."""
        filled = round(p * width)
        return "█" * filled + "░" * (width - filled) + f" {p:.0%}"

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        total_prob  = 1.0
        total_mult  = 1
        has_probs   = True
        conf_sum    = 0.0
        conf_count  = 0
        ml_count    = 0

        for i, r in enumerate(self._rows):
            pick = r.pick_var.get()
            mult = MULT.get(pick, 1)
            total_mult *= mult

            p_h = r.p_h
            p_d = r.p_d
            p_a = r.p_a

            is_pleno15 = (i == 14)

            # ── Probabilidad de acertar ───────────────────────────────────────
            if is_pleno15:
                prob = _prob_acertar_pleno15(pick, p_h, p_d, p_a)
            else:
                prob = _prob_acertar(pick, p_h, p_d, p_a)
            if prob <= 0:
                has_probs = False
            total_prob *= prob

            source = r.data.get("p_source") or ""

            # Contar fuentes para KPIs
            if source == "ml":
                ml_count += 1

            # ── Columna de confianza ──────────────────────────────────────────
            claude_conf = r.data.get("claude_confidence")
            if source == "claude" and claude_conf:
                c = int(claude_conf)
                conf_sum   += c
                conf_count += 1
                stars = "★" * c + "☆" * (5 - c)
                conf_str = stars
                conf_tag  = "conf_high" if c >= 4 else "conf_med" if c == 3 else "conf_low"
            elif source == "ml":
                # Confianza implícita del modelo ML = max(p_h, p_d, p_a)
                implicit = max(p_h, p_d, p_a) if p_h > 0 else 0
                conf_sum   += implicit * 5  # escalar a 1-5
                conf_count += 1
                conf_str = f"ML {implicit:.0%}"
                conf_tag  = "conf_high" if implicit >= 0.55 else "conf_med" if implicit >= 0.40 else "conf_low"
            elif source in ("club_elo", "elo"):
                conf_str  = "ELO"
                conf_tag  = "even_row"
            elif source == "odds_api":
                conf_str  = "API ↯"
                conf_tag  = "even_row"
            else:
                conf_str  = "—"
                conf_tag  = "even_row"

            # ── Pick IA a mostrar ─────────────────────────────────────────────
            if p_h > 0:
                if is_pleno15:
                    ai_pick = _pleno15_pick_ai(p_h, p_d, p_a)
                elif self._n_doubles.get() > 0:
                    ai_pick = pick
                else:
                    ai_pick = _ai_pick(p_h, p_d, p_a)
            else:
                ai_pick = "—"

            tag     = "triple" if mult == 3 else "double" if mult == 2 else "single"
            row_alt = "even_row" if i % 2 == 0 else "odd_row"
            home    = r.data.get("home_team", "?")
            away    = r.data.get("away_team", "?")

            # ── Columnas de probabilidad ──────────────────────────────────────
            if is_pleno15:
                if p_h > 0:
                    p0, p1b, p2b, pMb = _pleno15_probs(p_h, p_d, p_a)
                    p1_str = f"0:{p0:.0%}"
                    px_str = f"1:{p1b:.0%}"
                    p2_str = f"2:{p2b:.0%}"
                else:
                    p1_str = px_str = p2_str = "—"
            else:
                p1_str = f"{p_h:.0%}" if p_h > 0 else "—"
                px_str = f"{p_d:.0%}" if p_d > 0 else "—"
                p2_str = f"{p_a:.0%}" if p_a > 0 else "—"

            # Tags combinados: cobertura + confianza
            tags = (tag, conf_tag)

            self.tree.insert("", "end", iid=str(i), tags=tags, values=(
                "P15" if is_pleno15 else i + 1,
                home[:24],
                away[:24],
                p1_str,
                px_str,
                p2_str,
                ai_pick,
                conf_str,
                pick,
            ))

        # ── Actualizar KPIs ───────────────────────────────────────────────────
        n       = len(self._rows)
        coste   = round(total_mult * COSTE_BASE, 2)
        prob_str = f"{total_prob:.3%}" if has_probs and n > 0 else "—"

        self._kpi_labels["partidos"].configure(text=str(n))
        self._kpi_labels["combinaciones"].configure(text=str(total_mult))
        self._kpi_labels["coste"].configure(text=f"{coste:.2f} €")
        self._kpi_labels["prob"].configure(
            text=prob_str,
            text_color="#00c853" if has_probs and total_prob > 0.01
            else "#ffd600" if has_probs else MUTED,
        )

        # Confianza media
        if conf_count > 0:
            avg_conf = conf_sum / conf_count
            # Normalizar: ML da 0-5×implicit, Claude da 1-5 directo
            avg_norm = avg_conf / 5.0
            conf_color = "#4ade80" if avg_norm >= 0.65 else "#fbbf24" if avg_norm >= 0.45 else "#f87171"
            self._kpi_labels["conf_avg"].configure(
                text=f"{avg_norm:.0%}",
                text_color=conf_color,
            )
        else:
            self._kpi_labels["conf_avg"].configure(text="—", text_color=MUTED)

        # Picks con ML
        self._kpi_labels["picks_ml"].configure(
            text=f"{ml_count}/{n}",
            text_color="#7dd3fc" if ml_count > 0 else MUTED,
        )

        # ── Pleno al 15: marcador exacto para el partido 15 ───────────────────
        if hasattr(self, "_pleno15_lbl") and len(self._rows) >= 15:
            r15    = self._rows[14]
            home15 = r15.data.get("home_team", "?")
            away15 = r15.data.get("away_team", "?")
            scores = _predict_exact_scores(r15.p_h, r15.p_d, r15.p_a)
            if scores:
                parts = [f"{gh}-{ga} ({p:.1%})" for gh, ga, p in scores[:5]]
                self._pleno15_lbl.configure(
                    text=f"{home15} vs {away15}  →  " + "  ·  ".join(parts),
                    text_color=TEXT,
                )
            else:
                self._pleno15_lbl.configure(
                    text=f"{home15} vs {away15}  →  sin datos de probabilidad",
                    text_color=MUTED,
                )

        # Actualizar panel de distribución después de cada refresco
        self._update_dist_panel()

    # ── Panel de distribución 1/X/2 ──────────────────────────────────────────

    def _update_dist_panel(self) -> None:
        """
        Actualiza los contadores de 1/X/2 en el panel de patrón histórico.

        Rangos históricos de La Quiniela española (14 partidos, SELAE):
          1 Local  → 5-9  (media ~6.2)
          X Empate → 3-6  (media ~3.8)
          2 Visita → 2-5  (media ~4.1)
        Fuera de estos rangos el boleto pierde valor estadístico.
        """
        if not hasattr(self, "_dist_labels") or not self._rows:
            return

        # Contar picks de los partidos 1-14 (excluir Pleno al 15)
        count = {"1": 0, "X": 0, "2": 0}
        for r in self._rows[:14]:
            p = r.pick_var.get()
            for k in ("1", "X", "2"):
                if k in p:              # captura también dobles (1X, X2, 12) y triples
                    count[k] += 1

        # Rangos históricos y color resultante
        _ranges = {"1": (5, 9), "X": (3, 6), "2": (2, 5)}
        for key, lbl in self._dist_labels.items():
            n = count[key]
            lo, hi = _ranges[key]
            if lo <= n <= hi:
                color, icon = "#22c55e", "✓"   # verde — dentro del rango
            elif (lo - 1) <= n <= (hi + 1):
                color, icon = "#fbbf24", "~"   # amarillo — justo fuera, aceptable
            else:
                color, icon = "#ef4444", "!"   # rojo — alejado del patrón histórico
            lbl.configure(text=f"{icon} {n}", text_color=color)

        # ── Inteligencia de jornada (etiqueta de resumen) ─────────────────────
        if hasattr(self, "_jornada_intel_lbl") and self._rows:
            rows_with_probs = [r for r in self._rows[:14] if r.p_h > 0]
            if rows_with_probs:
                # Claros: max(p_h, p_d, p_a) >= 0.55
                claros  = sum(1 for r in rows_with_probs if max(r.p_h, r.p_d, r.p_a) >= 0.55)
                # Dudosos: max < 0.42
                dudosos = sum(1 for r in rows_with_probs if max(r.p_h, r.p_d, r.p_a) < 0.42)
                n_with  = len(rows_with_probs)
                intel_parts = []
                if claros:  intel_parts.append(f"✓ {claros} claros")
                if dudosos: intel_parts.append(f"? {dudosos} dudosos")
                rest = n_with - claros - dudosos
                if rest:    intel_parts.append(f"~ {rest} medios")
                intel_txt = "  ·  ".join(intel_parts)
                self._jornada_intel_lbl.configure(text=intel_txt, text_color="#64748b")
            else:
                self._jornada_intel_lbl.configure(text="", text_color=MUTED)

    # ── Motor de calibración IA ───────────────────────────────────────────────

    def _load_calibrated_params(self) -> None:
        """Carga los parámetros calibrados desde la base de datos."""
        try:
            from ...core.quiniela_calibrator import QuinielaCalibrator
            cal = QuinielaCalibrator(self.app.storage)
            self._q_params = cal.load_params()
        except Exception:
            self._q_params = {}

    def _build_calibration_section(self) -> None:
        """Construye el panel de calibración (oculto por defecto)."""
        self._cal_frame = ctk.CTkFrame(
            self, fg_color="#06060f", corner_radius=14,
            border_color="#4338ca", border_width=1,
        )
        self._cal_frame.grid_columnconfigure(0, weight=1)

        # Cabecera
        hdr = ctk.CTkFrame(self._cal_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="🧬  Motor de aprendizaje — Calibración automática de picks",
            text_color="#c4b5fd", font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            hdr, text="✕",
            command=self._toggle_calibration,
            fg_color="transparent", hover_color="#1a1a2e",
            text_color="#818cf8", width=30, height=26,
        ).grid(row=0, column=2, sticky="e")

        tk.Frame(self._cal_frame, bg="#4338ca", height=1).grid(
            row=1, column=0, sticky="ew", padx=14, pady=(0, 10)
        )

        # Body: stats + botón + log
        body = ctk.CTkFrame(self._cal_frame, fg_color="transparent")
        body.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        body.grid_columnconfigure(1, weight=1)

        # ── Columna izquierda: parámetros actuales ────────────────────────────
        params_card = ctk.CTkFrame(body, fg_color="#0a0a1a", corner_radius=10,
                                   border_color="#312e81", border_width=1)
        params_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=4)

        ctk.CTkLabel(
            params_card, text="Parámetros activos",
            text_color="#818cf8", font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self._cal_params_lbl = ctk.CTkLabel(
            params_card,
            text="Cargando…",
            text_color="#c4b5fd", font=ctk.CTkFont(size=11),
            justify="left",
        )
        self._cal_params_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Columna central: distribución histórica ───────────────────────────
        dist_card = ctk.CTkFrame(body, fg_color="#0a0a1a", corner_radius=10,
                                 border_color="#312e81", border_width=1)
        dist_card.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=4)

        ctk.CTkLabel(
            dist_card, text="Distribución empírica (SP1/SP2)",
            text_color="#818cf8", font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self._cal_dist_canvas = tk.Canvas(
            dist_card, bg="#0a0a1a", highlightthickness=0, height=70, width=200,
        )
        self._cal_dist_canvas.pack(padx=12, pady=(0, 8))

        # ── Columna derecha: botón + precisión boletos ─────────────────────────
        action_card = ctk.CTkFrame(body, fg_color="#0a0a1a", corner_radius=10,
                                   border_color="#312e81", border_width=1)
        action_card.grid(row=0, column=2, sticky="nsew", pady=4)

        ctk.CTkLabel(
            action_card, text="Tasa de acierto (boletos)",
            text_color="#818cf8", font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 4))

        self._cal_accuracy_lbl = ctk.CTkLabel(
            action_card, text="Sin datos",
            text_color="#c4b5fd", font=ctk.CTkFont(size=11),
            justify="left",
        )
        self._cal_accuracy_lbl.pack(anchor="w", padx=12)

        self._cal_run_btn = ctk.CTkButton(
            action_card, text="🔄 Recalibrar ahora",
            command=self._run_calibration,
            fg_color="#1e1b4b", hover_color="#312e81",
            border_color="#818cf8", border_width=1, height=32,
        )
        self._cal_run_btn.pack(padx=12, pady=(10, 4))

        self._cal_auto_lbl = ctk.CTkLabel(
            action_card,
            text="Auto-calibra con SP1/SP2\ny tus boletos verificados",
            text_color="#4338ca", font=ctk.CTkFont(size=9),
            justify="center",
        )
        self._cal_auto_lbl.pack(pady=(0, 8))

        # Log de calibración
        self._cal_log = ctk.CTkTextbox(
            self._cal_frame, height=80,
            fg_color="#030304", text_color="#6366f1",
            font=ctk.CTkFont(family="Consolas", size=10),
        )
        self._cal_log.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        self._cal_log.insert("end", "Pulsa 🔄 Recalibrar para entrenar con datos históricos SP1/SP2.\n")
        self._cal_log.configure(state="disabled")

    def _toggle_calibration(self) -> None:
        """Muestra u oculta el panel de calibración."""
        if self._calibration_visible:
            self._cal_frame.grid_remove()
            self._calibration_visible = False
            self._cal_btn.configure(text="🧬 Calibrar IA")
        else:
            # Colocar debajo del historial si está visible, si no, en fila 6
            self._cal_frame.grid(row=6, column=0, sticky="ew", pady=(8, 0))
            self._calibration_visible = True
            self._cal_btn.configure(text="✕ Cerrar Calibración")
            self._refresh_calibration_panel()

    def _refresh_calibration_panel(self) -> None:
        """Actualiza los widgets del panel con los parámetros actuales."""
        p = self._q_params
        if not p:
            return

        calibrated = p.get("calibrated", False)
        src        = p.get("calibration_source", "defaults")
        n_matches  = p.get("n_matches", 0)
        n_boletos  = p.get("n_boletos", 0)
        last_run   = p.get("last_run") or "Nunca"
        if last_run and last_run != "Nunca":
            last_run = last_run[:16].replace("T", " ")

        triple_th = p.get("triple_threshold", 0.42)
        double_th = p.get("double_threshold", 0.28)
        draw_b    = p.get("draw_bias", 1.05)

        status = "✓ Calibrado" if calibrated else "⚠ Sin calibrar (usando defaults)"
        src_map = {
            "defaults":         "Valores por defecto",
            "sp_history":       f"SP1/SP2 ({n_matches:,} partidos)",
            "boletos":          f"Boletos verificados ({n_boletos})",
            "sp_history+boletos": f"SP1/SP2 + {n_boletos} boletos ({n_matches:,} partidos)",
        }
        src_str = src_map.get(src, src)

        self._cal_params_lbl.configure(text=(
            f"Estado:   {status}\n"
            f"Fuente:   {src_str}\n"
            f"Última:   {last_run}\n"
            f"Triple<:  {triple_th:.2f}  (sin favorito claro)\n"
            f"Doble≥:   {double_th:.2f}  (2ª opción plausible)\n"
            f"Draw ×:   {draw_b:.3f}  (corrección sesgo empate)"
        ))

        # Distribución empírica con barras en canvas
        home_r = p.get("home_rate", 0.452)
        draw_r = p.get("draw_rate", 0.264)
        away_r = p.get("away_rate", 0.284)
        self._draw_dist_bars(home_r, draw_r, away_r)

        # Precisión boletos
        accuracy    = p.get("accuracy")
        detail      = p.get("accuracy_detail", {})
        if accuracy is not None:
            lines = [f"Global:  {accuracy:.1%}  ({n_boletos} boletos)"]
            if detail:
                if "simple" in detail: lines.append(f"Simple:  {detail['simple']:.1%}")
                if "doble"  in detail: lines.append(f"Doble:   {detail['doble']:.1%}")
                if "triple" in detail: lines.append(f"Triple:  {detail['triple']:.1%}")
            self._cal_accuracy_lbl.configure(
                text="\n".join(lines),
                text_color="#a5f3fc",
            )
        else:
            nb = p.get("n_boletos", 0)
            msg = f"Sin boletos verificados aún\n({nb} boleto(s), min. 5)" if nb < 5 else "Disponible tras calibrar"
            self._cal_accuracy_lbl.configure(text=msg, text_color="#4338ca")

    def _draw_dist_bars(self, h: float, d: float, a: float) -> None:
        """Dibuja las barras de distribución 1/X/2 en el canvas."""
        c = self._cal_dist_canvas
        c.delete("all")
        w, height = 200, 70
        bar_h = 16
        labels = [("1 Local", h, "#22c55e"), ("X Empate", d, "#fbbf24"), ("2 Visita", a, "#60a5fa")]
        y0 = 6
        for label, val, col in labels:
            bar_w = int(val * (w - 80))
            c.create_text(2, y0 + 8, text=label, anchor="w", fill="#6b7280", font=("Segoe UI", 8))
            c.create_rectangle(55, y0, 55 + bar_w, y0 + bar_h, fill=col, outline="")
            c.create_text(58 + bar_w, y0 + 8, text=f"{val:.1%}", anchor="w", fill=col, font=("Segoe UI", 8, "bold"))
            y0 += bar_h + 4

    def _run_calibration(self) -> None:
        """Lanza la calibración en un hilo de fondo."""
        if self._calibration_running:
            return
        self._calibration_running = True
        self._cal_run_btn.configure(state="disabled", text="⏳ Calibrando…")
        self._cal_log.configure(state="normal")
        self._cal_log.delete("1.0", "end")
        self._cal_log.configure(state="disabled")

        import threading
        threading.Thread(target=self._calibration_worker, daemon=True).start()

    def _calibration_worker(self) -> None:
        """Hilo de fondo para la calibración."""
        def _cb(msg: str) -> None:
            self.app.after(0, lambda m=msg: self._cal_log_append(m))

        try:
            from ...core.quiniela_calibrator import QuinielaCalibrator
            cal = QuinielaCalibrator(self.app.storage)
            params = cal.calibrate(cb=_cb)
            self.app.after(0, lambda p=params: self._on_calibration_done(p))
        except Exception as exc:
            self.app.after(0, lambda e=exc: self._cal_log_append(f"❌ Error: {e}"))
            self.app.after(0, self._on_calibration_error)

    def _cal_log_append(self, msg: str) -> None:
        """Añade una línea al log de calibración (hilo principal)."""
        try:
            self._cal_log.configure(state="normal")
            self._cal_log.insert("end", msg + "\n")
            self._cal_log.see("end")
            self._cal_log.configure(state="disabled")
        except Exception:
            pass

    def _on_calibration_done(self, params: dict) -> None:
        """Callback cuando la calibración termina correctamente."""
        self._q_params = params
        self._calibration_running = False
        self._cal_run_btn.configure(state="normal", text="🔄 Recalibrar ahora")
        self._refresh_calibration_panel()
        # Si hay partidos cargados, regenerar picks con los nuevos params
        if self._rows:
            self._apply_picks()
            self._refresh_tree()
            self.status_lbl.configure(
                text="✅  Calibración completada — picks regenerados con los nuevos parámetros"
            )

    def _on_calibration_error(self) -> None:
        self._calibration_running = False
        self._cal_run_btn.configure(state="normal", text="🔄 Recalibrar ahora")

    # ── Historial de boletos guardados ────────────────────────────────────────

    def _build_historial_section(self) -> None:
        """Construye el panel de historial (oculto por defecto)."""
        self._hist_frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        # No se añade al grid todavía — se muestra con _toggle_historial()
        self._hist_frame.grid_columnconfigure(0, weight=1)

        # Cabecera
        hdr = ctk.CTkFrame(self._hist_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="📂  Historial de boletos guardados",
            text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            hdr, text="🔄 Verificar todos ahora",
            command=self._verify_all_now,
            fg_color="#10301a", hover_color="#164020",
            border_color="#22c55e", border_width=1,
            text_color="#a7f3c0", width=170, height=26,
        ).grid(row=0, column=1, sticky="e", padx=(0, 8))

        ctk.CTkButton(
            hdr, text="✕ Cerrar",
            command=self._toggle_historial,
            fg_color="transparent", hover_color="#1a2a1a",
            text_color=MUTED, width=70, height=26,
        ).grid(row=0, column=2, sticky="e")

        # Separador
        tk.Frame(self._hist_frame, bg="#1a5c2a", height=1).grid(
            row=1, column=0, sticky="ew", padx=14, pady=(0, 8)
        )

        # Área scrollable con las tarjetas
        self._hist_scroll = ctk.CTkScrollableFrame(
            self._hist_frame, fg_color="transparent", height=220,
        )
        self._hist_scroll.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self._hist_scroll.grid_columnconfigure(0, weight=1)

        self._hist_empty_lbl = ctk.CTkLabel(
            self._hist_scroll,
            text="No hay boletos guardados todavía.\nPulsa 💾 Guardar Boleto para registrar el boleto actual.",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        )
        self._hist_empty_lbl.grid(row=0, column=0, pady=30)

    def _verify_all_now(self) -> None:
        """Dispara la verificación automática de todos los boletos pendientes."""
        try:
            self.app.verify_quinielas_now()
        except Exception:
            pass

    def _toggle_historial(self) -> None:
        """Muestra u oculta el panel de historial."""
        if self._historial_visible:
            self._hist_frame.grid_remove()
            self._historial_visible = False
            self._hist_toggle_btn.configure(text="📂 Historial")
        else:
            self._hist_frame.grid(row=5, column=0, sticky="ew", pady=(8, 0))
            self._historial_visible = True
            self._hist_toggle_btn.configure(text="✕ Cerrar Historial")
            self._load_historial()

    # Cuántas tarjetas mostrar por defecto (limita widgets en hilo principal)
    _HIST_PAGE = 10

    def _load_historial(self, limit: int | None = None) -> None:
        """
        Reconstruye las tarjetas del historial desde la base de datos.
        Por defecto muestra solo las últimas _HIST_PAGE para no bloquear la UI.
        """
        # Limpiar tarjetas anteriores
        for w in self._hist_scroll.winfo_children():
            w.destroy()

        page = limit or self._HIST_PAGE
        boletos = []
        try:
            boletos = self.app.storage.load_quinielas(limit=50)
        except Exception:
            pass

        if not boletos:
            ctk.CTkLabel(
                self._hist_scroll,
                text="No hay boletos guardados todavía.\nPulsa 💾 Guardar Boleto para registrar el boleto actual.",
                text_color=MUTED, font=ctk.CTkFont(size=12),
            ).grid(row=0, column=0, pady=30)
            return

        visible = boletos[:page]
        for idx, b in enumerate(visible):
            self._build_hist_card(self._hist_scroll, b, row=idx)

        # Botón "Ver más" si quedan boletos ocultos
        if len(boletos) > page:
            remaining = len(boletos) - page
            ctk.CTkButton(
                self._hist_scroll,
                text=f"▼  Ver {remaining} boleto(s) más",
                command=lambda: self._load_historial(limit=page + self._HIST_PAGE),
                fg_color="transparent", hover_color="#0f2a12",
                text_color=MUTED, border_color="#0a2030", border_width=1,
                height=30, font=ctk.CTkFont(size=11),
            ).grid(row=page, column=0, sticky="ew", padx=8, pady=6)
        else:
            total = len(boletos)
            ctk.CTkLabel(
                self._hist_scroll,
                text=f"— {total} boleto(s) en total —",
                text_color="#1a3a1a", font=ctk.CTkFont(size=10),
            ).grid(row=page, column=0, pady=(4, 8))

    def _build_hist_card(self, parent, b: dict, row: int) -> None:
        """Construye una tarjeta de historial para un boleto."""
        qid      = b.get("_db_id", 0)
        jornada  = b.get("jornada", "?")
        fecha    = b.get("fecha", "")
        saved_at = b.get("saved_at", "")[:16]
        coste    = b.get("coste", 0.0)
        status   = b.get("status", "PENDIENTE")
        aciertos = b.get("aciertos")
        categoria = b.get("categoria", "")
        partidos = b.get("partidos", [])

        # Color del borde según estado
        if status == "PENDIENTE":
            border_col = "#0a2030"
        elif aciertos is not None and aciertos >= 13:
            border_col = "#22c55e"
        elif aciertos is not None and aciertos >= 12:
            border_col = "#fbbf24"
        else:
            border_col = "#374151"

        card = ctk.CTkFrame(
            parent, fg_color="#040b16", corner_radius=10,
            border_color=border_col, border_width=1,
        )
        card.grid(row=row, column=0, sticky="ew", padx=4, pady=4)
        card.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # ── Columna izquierda: info general ──────────────────────────────────
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, sticky="nw", padx=12, pady=8)

        ctk.CTkLabel(
            info, text=f"Jornada {jornada}",
            text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            info, text=f"Guardado: {saved_at}",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(anchor="w")
        if fecha:
            ctk.CTkLabel(
                info, text=f"Fecha jornada: {fecha}",
                text_color=MUTED, font=ctk.CTkFont(size=10),
            ).pack(anchor="w")
        ctk.CTkLabel(
            info, text=f"Coste: {coste:.2f} €",
            text_color=ACCENT, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(4, 0))

        # ── Columna central: picks compactos ─────────────────────────────────
        picks_frame = ctk.CTkFrame(card, fg_color="transparent")
        picks_frame.grid(row=0, column=1, sticky="ew", padx=8, pady=8)

        picks_14 = [p.get("pick", "?") for p in partidos[:14]]
        pick_p15 = partidos[14].get("pick", "?") if len(partidos) >= 15 else "?"

        # Colores por pick
        _pick_colors = {
            "1": "#22c55e", "X": "#fbbf24", "2": "#60a5fa",
            "1X": "#a3e635", "X2": "#fb923c", "12": "#a78bfa", "1X2": "#f472b6",
            "0": "#94a3b8", "M": "#ef4444",
        }

        # Resultados reales para comparar (si verificado)
        res_reales = b.get("resultados_reales", []) or []

        row_chips = ctk.CTkFrame(picks_frame, fg_color="transparent")
        row_chips.pack(anchor="w")

        for i, pk in enumerate(picks_14):
            real = res_reales[i] if i < len(res_reales) else None
            # Si verificado, colorear según acierto
            if real is not None:
                # Un pick es correcto si el resultado real está en las opciones del pick
                correct = _pick_matches(pk, real)
                chip_color = "#22c55e" if correct else "#ef4444"
            else:
                chip_color = _pick_colors.get(pk, MUTED)

            chip = ctk.CTkLabel(
                row_chips, text=pk, width=28, height=20,
                fg_color="#061220", corner_radius=4,
                text_color=chip_color, font=ctk.CTkFont(size=10, weight="bold"),
            )
            chip.pack(side="left", padx=1)

        # Separador + pleno15
        sep_frame = ctk.CTkFrame(picks_frame, fg_color="transparent")
        sep_frame.pack(anchor="w", pady=(2, 0))

        ctk.CTkLabel(
            sep_frame, text="P15:",
            text_color=MUTED, font=ctk.CTkFont(size=9),
        ).pack(side="left", padx=(0, 3))

        real_p15 = res_reales[14] if len(res_reales) >= 15 else None
        if real_p15 is not None:
            correct_p15 = (pick_p15 == real_p15)
            p15_color = "#22c55e" if correct_p15 else "#ef4444"
        else:
            p15_color = "#94a3b8"

        ctk.CTkLabel(
            sep_frame, text=pick_p15, width=28, height=20,
            fg_color="#061220", corner_radius=4,
            text_color=p15_color, font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(side="left")

        # ── Columna derecha: estado + botones ─────────────────────────────────
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="ne", padx=12, pady=8)

        # Estado / resultado
        if status == "PENDIENTE":
            st_text  = "⏳ Pendiente"
            st_color = MUTED
        elif aciertos is not None:
            st_text  = f"✓ {aciertos}/15 · {categoria}"
            if aciertos >= 13:
                st_color = "#22c55e"
            elif aciertos >= 12:
                st_color = "#fbbf24"
            else:
                st_color = "#ef4444"
        else:
            st_text  = "✓ Verificado"
            st_color = ACCENT

        ctk.CTkLabel(
            actions, text=st_text,
            text_color=st_color, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="e", pady=(0, 6))

        ctk.CTkButton(
            actions, text="🏆 Verificar",
            command=lambda qid=qid, b=b: self._open_verify_dialog(qid, b),
            fg_color="#1a3010", hover_color="#224014",
            border_color="#22c55e", border_width=1,
            height=28, width=100, font=ctk.CTkFont(size=11),
        ).pack(anchor="e", pady=2)

        ctk.CTkButton(
            actions, text="🗑 Borrar",
            command=lambda qid=qid: self._delete_boleto(qid),
            fg_color="#1a0a0a", hover_color="#2a0e0e",
            text_color="#f87171", height=28, width=100,
            font=ctk.CTkFont(size=11),
        ).pack(anchor="e", pady=2)

    # ── Guardar boleto actual ─────────────────────────────────────────────────

    def save_current_boleto(self) -> None:
        """Guarda el boleto actual en el historial de la base de datos."""
        if not self._rows:
            self.status_lbl.configure(
                text="⚠  Carga primero la jornada oficial antes de guardar."
            )
            return

        import re
        from datetime import datetime as _dt

        # Construir payload completo
        total_mult = 1
        total_prob = 1.0
        has_probs  = True
        for i, r in enumerate(self._rows):
            pick = r.pick_var.get()
            total_mult *= MULT.get(pick, 1)
            prob = (_prob_acertar_pleno15(pick, r.p_h, r.p_d, r.p_a)
                    if i == 14
                    else _prob_acertar(pick, r.p_h, r.p_d, r.p_a))
            if r.p_h <= 0:
                has_probs = False
            else:
                total_prob *= prob

        coste    = round(total_mult * COSTE_BASE, 2)
        prob_val = round(total_prob, 8) if has_probs else 0.0

        # Jornada desde status label
        status_text = self.status_lbl.cget("text") if hasattr(self.status_lbl, "cget") else ""
        jornada = "?"
        m = re.search(r"Jornada\s+(\S+)", status_text)
        if m:
            jornada = m.group(1)

        partidos = []
        for i, r in enumerate(self._rows):
            partidos.append({
                "num":    i + 1,
                "home":   r.data.get("home_team", "?"),
                "away":   r.data.get("away_team", "?"),
                "pick":   r.pick_var.get(),
                "p_h":    round(r.p_h, 4),
                "p_d":    round(r.p_d, 4),
                "p_a":    round(r.p_a, 4),
            })

        payload = {
            "saved_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "jornada":  jornada,
            "fecha":    self._jornada_fecha,
            "partidos": partidos,
            "coste":    coste,
            "prob":     prob_val,
            "status":   "PENDIENTE",
        }

        try:
            qid = self.app.storage.save_quiniela(payload)
            self.status_lbl.configure(
                text=f"✅  Boleto guardado (ID #{qid}) — Jornada {jornada} · {coste:.2f} €  |  {len(self._rows)} partidos"
            )
        except Exception as exc:
            self.status_lbl.configure(text=f"⚠  Error al guardar: {exc}")
            return

        # Si el historial está abierto, refrescar
        if self._historial_visible:
            self._load_historial()

    def _delete_boleto(self, qid: int) -> None:
        """Borra un boleto del historial tras confirmación."""
        from tkinter import messagebox
        if not messagebox.askyesno(
            "Borrar boleto",
            f"¿Seguro que quieres borrar el boleto #{qid}?\nEsta acción no se puede deshacer.",
        ):
            return
        try:
            self.app.storage.delete_quiniela(qid)
        except Exception as exc:
            from tkinter import messagebox as mb
            mb.showerror("Error", f"No se pudo borrar el boleto: {exc}")
            return
        self._load_historial()

    # ── Diálogo de verificación ───────────────────────────────────────────────

    def _open_verify_dialog(self, qid: int, b: dict) -> None:
        """
        Abre un Toplevel para introducir los resultados reales de la jornada
        y calcular cuántos partidos se acertaron.
        """
        partidos  = b.get("partidos", [])
        if not partidos:
            return

        dlg = tk.Toplevel(self.winfo_toplevel())
        dlg.title(f"Verificar boleto #{qid} — Jornada {b.get('jornada', '?')}")
        dlg.configure(bg="#040c18")
        dlg.resizable(False, False)
        dlg.grab_set()

        # ── Cabecera ──────────────────────────────────────────────────────────
        hdr_frm = tk.Frame(dlg, bg="#040c18")
        hdr_frm.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(
            hdr_frm,
            text=f"🏆  Verificar Jornada {b.get('jornada', '?')}",
            bg="#040c18", fg="#f0fff4",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        tk.Label(
            hdr_frm,
            text="Introduce el resultado real de cada partido (1 local / X empate / 2 visitante)",
            bg="#040c18", fg="#6ee89a",
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(12, 0))

        # ── Área scrollable ───────────────────────────────────────────────────
        canvas_frm = tk.Frame(dlg, bg="#040c18")
        canvas_frm.pack(fill="both", expand=True, padx=16, pady=4)

        canvas = tk.Canvas(canvas_frm, bg="#040c18", highlightthickness=0, width=620, height=420)
        vsb    = ttk.Scrollbar(canvas_frm, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg="#040c18")
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Cabecera tabla
        _cols = ["#", "Local", "Visitante", "Tu pick", "Resultado real"]
        _widths = [30, 160, 160, 80, 120]
        for ci, (col, w) in enumerate(zip(_cols, _widths)):
            tk.Label(
                inner, text=col, bg="#040b16", fg="#6ee89a",
                font=("Segoe UI", 10, "bold"), width=w // 8, anchor="w",
            ).grid(row=0, column=ci, padx=4, pady=(4, 2), sticky="w")

        # Variables para resultados reales
        result_vars: list[tk.StringVar] = []

        for i, p in enumerate(partidos):
            pick   = p.get("pick", "?")
            home   = p.get("home", "?")
            away   = p.get("away", "?")
            is_p15 = (i == 14)
            opts   = PLENO15_OPTIONS if is_p15 else ["1", "X", "2"]
            label  = f"P15" if is_p15 else str(i + 1)

            # Leer resultado real ya guardado (si existe)
            res_reales = b.get("resultados_reales") or []
            pre_val = res_reales[i] if i < len(res_reales) else opts[0]
            var = tk.StringVar(value=pre_val)
            result_vars.append(var)

            row_bg = "#040b16" if i % 2 == 0 else "#040c18"
            for ci, (txt, w) in enumerate([
                (label, 30),
                (home[:20], 160),
                (away[:20], 160),
                (pick, 80),
            ]):
                tk.Label(
                    inner, text=txt, bg=row_bg, fg="#f0fff4" if ci > 0 else "#6ee89a",
                    font=("Segoe UI", 10), width=w // 8, anchor="w",
                ).grid(row=i + 1, column=ci, padx=4, pady=1, sticky="w")

            ttk.Combobox(
                inner, textvariable=var,
                values=opts, state="readonly", width=6,
            ).grid(row=i + 1, column=4, padx=8, pady=1, sticky="w")

        # ── Botones ───────────────────────────────────────────────────────────
        btn_frm = tk.Frame(dlg, bg="#040c18")
        btn_frm.pack(fill="x", padx=16, pady=(8, 14))

        result_lbl = tk.Label(
            btn_frm, text="", bg="#040c18", fg="#22c55e",
            font=("Segoe UI", 12, "bold"),
        )
        result_lbl.pack(side="left", padx=(0, 16))

        def _calculate() -> None:
            resultados = [v.get() for v in result_vars]
            aciertos_14 = sum(
                1 for i, p in enumerate(partidos[:14])
                if _pick_matches(p.get("pick", ""), resultados[i] if i < len(resultados) else "")
            )
            aciertos_p15 = 0
            if len(partidos) >= 15 and len(resultados) >= 15:
                aciertos_p15 = 1 if resultados[14] == partidos[14].get("pick", "") else 0
            total = aciertos_14 + aciertos_p15

            # Categoría
            if total == 15:
                cat = "1ª (¡Pleno!)"
                cat_color = "#ffd700"
            elif aciertos_14 == 14 and aciertos_p15 == 1:
                cat = "2ª"
                cat_color = "#ffd700"
            elif aciertos_14 == 14:
                cat = "3ª"
                cat_color = "#22c55e"
            elif aciertos_14 == 13:
                cat = "4ª"
                cat_color = "#22c55e"
            elif aciertos_14 == 12:
                cat = "Sin premio (12/14)"
                cat_color = "#fbbf24"
            else:
                cat = f"Sin premio ({aciertos_14}/14)"
                cat_color = "#ef4444"

            result_lbl.configure(
                text=f"✓ {total}/15 aciertos — {cat}",
                fg=cat_color,
            )
            # Guardarlo temporalmente en la ventana para el botón Guardar
            dlg._temp_result = (total, cat, [v.get() for v in result_vars])

        def _save_and_close() -> None:
            if not hasattr(dlg, "_temp_result"):
                _calculate()
            total, cat, resultados = dlg._temp_result
            try:
                self.app.storage.update_quiniela_result(
                    qid, total, cat, resultados
                )
            except Exception as exc:
                from tkinter import messagebox as mb
                mb.showerror("Error", f"No se pudo guardar: {exc}", parent=dlg)
                return
            dlg.destroy()
            self._load_historial()
            self.status_lbl.configure(
                text=f"✅  Jornada {b.get('jornada','?')} verificada — {total}/15 aciertos · {cat}"
            )

        tk.Button(
            btn_frm, text="Calcular aciertos",
            command=_calculate,
            bg="#1a4a1a", fg="#f0fff4",
            font=("Segoe UI", 11), relief="flat", padx=12, pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frm, text="💾 Guardar resultado",
            command=_save_and_close,
            bg="#0a2e0a", fg="#22c55e",
            font=("Segoe UI", 11, "bold"), relief="flat", padx=12, pady=4,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            btn_frm, text="Cancelar",
            command=dlg.destroy,
            bg="#1a0a0a", fg="#f87171",
            font=("Segoe UI", 11), relief="flat", padx=12, pady=4,
        ).pack(side="right")

    def _open_chat_with_context(self) -> None:
        """Abre el Chat IA con contexto de la quiniela actual y pregunta pre-cargada."""
        n_picks = len(self._rows)
        if n_picks == 0:
            from tkinter import messagebox
            messagebox.showinfo(
                "Chat IA",
                "Carga primero la jornada o genera picks para poder consultarlos con la IA."
            )
            return
        self.app.show_chat_view(
            source_view="quiniela",
            prefill="Explícame por qué elegiste estos picks de quiniela partido a partido",
        )
