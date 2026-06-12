# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/accumulator.py — Vista de Combinadas IA.

Muestra las mejores combinadas generadas por el motor IA con
probabilidad de acierto, EV esperado y detalle de cada selección.
"""

from __future__ import annotations

import re
import tkinter as tk
from typing import Dict, List

import customtkinter as ctk
import pandas as pd
import numpy as np

from ...core.accumulator import (
    build_smart_accumulators, build_safe_accumulators, build_recommended_combo,
    PICK_LABELS, MARKET_BADGE,
)
from ...core.accumulator_calibrator import get_calibrator, get_active_weights
from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ..widgets import make_card


_DIAS_ES   = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_MESES_ES  = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
              "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _fmt_fecha(date_val, time_val="") -> str:
    """
    Formatea fecha + hora de un partido de forma legible.
    Acepta Timestamp, str ISO ('2026-06-15'), str ES ('15/06/2026') o None.
    Devuelve p.ej. 'Sáb 14 Jun  20:45' o '—' si no hay dato.
    """
    import pandas as _pd
    from datetime import datetime as _dt, date as _date_cls

    # ── Descartar nulos (None, NaN, NaT) ─────────────────────────────────────
    try:
        if date_val is None or _pd.isna(date_val):
            return "—"
    except (TypeError, ValueError):
        pass   # pd.isna() lanza TypeError para algunos tipos — los seguimos procesando

    # ── Parsear fecha ──────────────────────────────────────────────────────────
    dt = None
    if isinstance(date_val, _pd.Timestamp):
        dt = date_val.to_pydatetime()
    elif isinstance(date_val, (_dt, _date_cls)):
        dt = date_val
    elif isinstance(date_val, str) and date_val.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = _dt.strptime(date_val.strip()[:19], fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return "—"

    dia  = _DIAS_ES[dt.weekday()]
    mes  = _MESES_ES[dt.month]
    base = f"{dia} {dt.day:02d} {mes}"

    # ── Parsear hora ───────────────────────────────────────────────────────────
    hora = ""
    t = str(time_val).strip() if time_val else ""
    if t and t not in ("nan", "NaT", "None", "0", "00:00"):
        # Normalizar a HH:MM
        if re.match(r'^\d{2}:\d{2}', t):
            hora = t[:5]

    return f"{base}  {hora}".rstrip() if hora else base


def _leg_explanation(leg: dict) -> str:
    """
    Genera una explicación breve y legible para un leg de combinada.
    No usa Claude — solo los datos ya calculados del modelo.
    """
    pick       = leg.get("pick", "")
    mtype      = leg.get("market_type", "1X2")
    prob       = float(leg.get("model_prob") or 0)
    edge       = float(leg.get("edge") or 0)
    rel        = int(leg.get("reliability_score") or 0)
    clv        = leg.get("clv")
    cons_edge  = leg.get("consensus_edge")
    n_bks      = int(leg.get("n_bookmakers") or 0)
    ph         = float(leg.get("p_home") or 0)
    pd_        = float(leg.get("p_draw") or 0)
    pa         = float(leg.get("p_away") or 0)
    no_bet     = str(leg.get("no_bet") or "NO")

    parts: list[str] = []

    # ── Descripción de la selección ───────────────────────────────────────────
    if mtype == "1X2":
        _lbl = {"1": "victoria local", "X": "empate", "2": "victoria visitante"}
        desc = _lbl.get(pick, pick)
        parts.append(f"Modelo: {prob:.0%} de {desc}")
        if ph > 0 and pd_ > 0 and pa > 0:
            parts.append(f"distribución {ph:.0%}/{pd_:.0%}/{pa:.0%} (1/X/2)")

    elif mtype == "double_chance":
        _lbl = {"1X": "Local o Empate", "X2": "Empate o Visitante", "12": "Local o Visitante"}
        desc = _lbl.get(pick, pick)
        parts.append(f"Doble oportunidad — {desc}: {prob:.0%}")

    elif mtype == "goals":
        _lbl = {"OVER2.5": "más de 2.5 goles", "UNDER2.5": "menos de 2.5 goles"}
        desc = _lbl.get(pick, pick)
        parts.append(f"El modelo predice {desc} ({prob:.0%})")

    # ── Edge y ventaja ────────────────────────────────────────────────────────
    if edge >= 0.02:
        parts.append(f"edge {edge:.1%} sobre el mercado")
    elif edge > 0:
        parts.append(f"ligera ventaja {edge:.1%}")

    # ── Consenso de casas ─────────────────────────────────────────────────────
    if cons_edge is not None and pd.notna(cons_edge) and n_bks >= 2:
        ce = float(cons_edge)
        if ce > 0:
            parts.append(f"consenso de {n_bks} casas confirma (+{ce:.1%})")
        elif ce < -0.01:
            parts.append(f"divergencia con {n_bks} casas ({ce:.1%})")

    # ── CLV ───────────────────────────────────────────────────────────────────
    if clv is not None and pd.notna(clv):
        cv = float(clv)
        if cv > 0.01:
            parts.append(f"CLV positivo +{cv:.1%}")

    # ── Fiabilidad ────────────────────────────────────────────────────────────
    if rel >= 70:
        parts.append(f"alta fiabilidad ({rel}/99)")
    elif rel >= 40:
        parts.append(f"fiabilidad media ({rel}/99)")
    elif rel > 0:
        parts.append(f"fiabilidad baja ({rel}/99) — sin histórico suficiente")

    # ── No-bet override ───────────────────────────────────────────────────────
    if no_bet == "SI":
        raw_reason = str(leg.get("analysis") or "")
        return f"⚠ No apostar — {raw_reason}" if raw_reason else "⚠ No apostar"

    if not parts:
        return ""
    return "  ·  ".join(parts)


def _prob_color(prob: float) -> str:
    """
    Escala honesta de colores para el % de acierto estimado.
    Verde solo cuando el modelo predice más del 55% de acierto real.
    """
    if prob >= 0.55:
        return "#00c853"   # verde: buena tasa de acierto
    if prob >= 0.38:
        return "#ffd600"   # amarillo: moderada
    if prob >= 0.22:
        return "#ff9500"   # naranja: baja (combinada arriesgada)
    return "#ff5252"       # rojo: muy baja


def _ev_color(ev: float) -> str:
    return "#00c853" if ev > 0 else "#ff5252"


class AccumulatorView(ctk.CTkFrame):
    """Vista dedicada a combinadas generadas por IA."""

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._combos: List[Dict] = []
        self._build()

    # ── Layout principal ───────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_controls()
        self._build_scroll_area()

    def _build_controls(self) -> None:
        ctrl = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctrl.grid_columnconfigure(4, weight=1)   # spacer entre dropdowns y botón

        # ── Fila 0: título · selectors · botón principal ─────────────────────
        ctk.CTkLabel(
            ctrl, text="⚡  Combinadas IA",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=(14, 4), sticky="w")

        ctk.CTkLabel(
            ctrl, text="Legs máx:", text_color=MUTED,
        ).grid(row=0, column=1, padx=(20, 6), pady=(14, 4))

        self.max_legs_var = tk.StringVar(value="4")
        ctk.CTkOptionMenu(
            ctrl, variable=self.max_legs_var,
            values=["2", "3", "4"],
            fg_color=CARD_2, button_color=ACCENT,
            width=80,
        ).grid(row=0, column=2, padx=(0, 12), pady=(14, 4))

        ctk.CTkLabel(
            ctrl, text="Modo:", text_color=MUTED,
        ).grid(row=0, column=3, padx=(8, 6), pady=(14, 4))

        self.mode_var = tk.StringVar(value="⚡ Inteligente (EV)")
        ctk.CTkOptionMenu(
            ctrl, variable=self.mode_var,
            values=["⚡ Inteligente (EV)", "🛡 Seguras (DC + Goles)"],
            fg_color=CARD_2, button_color=ACCENT,
            width=190,
        ).grid(row=0, column=4, padx=(0, 16), pady=(14, 4), sticky="w")

        ctk.CTkButton(
            ctrl, text="⚡  Generar combinadas",
            command=self.refresh,
            fg_color=ACCENT, hover_color=ACCENT_2, height=38,
        ).grid(row=0, column=5, padx=16, pady=(14, 4), sticky="e")

        # ── Fila 1: status · botones secundarios ─────────────────────────────
        self.status_lbl = ctk.CTkLabel(
            ctrl, text="Ejecuta el análisis y pulsa Generar.", text_color=MUTED,
            font=ctk.CTkFont(size=11),
        )
        self.status_lbl.grid(row=1, column=0, columnspan=4, sticky="w", padx=18, pady=(0, 10))

        btn_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        btn_row.grid(row=1, column=4, columnspan=2, sticky="e", padx=16, pady=(0, 10))

        ctk.CTkButton(
            btn_row,
            text="🧠 Consultar IA",
            command=self._open_chat_with_context,
            fg_color="#1e1b4b", hover_color="#312e81",
            border_color="#818cf8", border_width=1,
            text_color="#c4b5fd",
            height=30, corner_radius=10,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 8))

        self._calib_btn = ctk.CTkButton(
            btn_row,
            text="🔬 Calibrar pesos",
            command=self._calibrate_weights,
            fg_color="#1a1200", hover_color="#2a2000",
            border_color="#ca8a04", border_width=1,
            text_color="#fde047",
            height=30, corner_radius=10,
            font=ctk.CTkFont(size=11),
        )
        self._calib_btn.pack(side="left")
        self._update_calib_btn_label()

    def _build_scroll_area(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self, df: pd.DataFrame | None = None) -> None:
        """Regenera las combinadas a partir del DataFrame de resultados."""
        if df is None:
            df = self.app.results

        for w in self.scroll.winfo_children():
            w.destroy()

        if df is None or df.empty:
            self.status_lbl.configure(text="Ejecuta el análisis primero.")
            self._show_empty("No hay datos de análisis.\nPulsa ▶  Run Analysis en el menú lateral.")
            return

        max_legs = int(self.max_legs_var.get())
        safe_mode = self.mode_var.get().startswith("🛡")
        weights   = get_active_weights()
        # Calibrador de probabilidades (ajustado en el análisis). Crucial en
        # combinadas: corrige el sesgo del modelo antes de multiplicar las probs.
        calibrator = getattr(self.app, "_prob_calibrator", None)

        if safe_mode:
            self._combos = build_safe_accumulators(
                df, max_legs=min(max_legs, 3), weights=weights,
                prob_calibrator=calibrator)
            recommended  = None  # recomendada usa otro algoritmo — no aplica en modo seguro
        else:
            self._combos  = build_smart_accumulators(
                df, max_legs=max_legs, weights=weights, prob_calibrator=calibrator)
            recommended   = build_recommended_combo(
                df, weights=weights, prob_calibrator=calibrator)

        row_offset = 0

        # ── Cabecera de modo seguro ───────────────────────────────────────────
        if safe_mode:
            self._build_safe_mode_header()
            row_offset = 1

        # ── Apuesta recomendada (solo modo inteligente) ───────────────────────
        if recommended:
            self._build_recommended_card(recommended)
            row_offset += 1

        if not self._combos:
            msg = (
                "🛡  Sin combinadas seguras disponibles.\n\n"
                "El modelo necesita ver fixtures con cuotas DC y Goles (B365O25).\n"
                "Asegúrate de ejecutar el análisis con ligas que tengan datos históricos."
                if safe_mode else
                "⚠️  No hay picks con ventaja estadística suficiente.\n\n"
                "Asegúrate de que el análisis ha generado picks VERDE o AMARILLO."
            )
            self.status_lbl.configure(text="Sin combinadas para los filtros actuales.")
            if not recommended:
                self._show_empty(msg)
            return

        if safe_mode:
            n_dc    = sum(1 for c in self._combos for l in c["legs"] if l.get("market_type") == "double_chance")
            n_goals = sum(1 for c in self._combos for l in c["legs"] if l.get("market_type") == "goals")
            self.status_lbl.configure(
                text=f"✓  {len(self._combos)} combinadas seguras  ·  {n_dc} legs DC  ·  {n_goals} legs Goles  ·  Optimizado para % acierto"
            )
        else:
            self.status_lbl.configure(
                text=f"✓  {len(self._combos)} combinadas  ·  Ensemble ML+Poisson  ·  Consenso multi-casa"
            )

        for i, combo in enumerate(self._combos):
            self._build_combo_card(i + row_offset, combo)

    def _show_empty(self, msg: str) -> None:
        ctk.CTkLabel(
            self.scroll, text=msg,
            text_color=MUTED, font=ctk.CTkFont(size=14),
            justify="center",
        ).grid(row=0, column=0, pady=80)

    def _build_safe_mode_header(self) -> None:
        """Banner informativo del modo Seguras."""
        banner = ctk.CTkFrame(
            self.scroll, fg_color="#0c1a2e", corner_radius=12,
            border_color="#3b82f6", border_width=1,
        )
        banner.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        banner.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(banner, fg_color="transparent")
        inner.grid(row=0, column=0, padx=16, pady=10, sticky="ew")
        inner.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            inner, text="🛡  MODO SEGURAS",
            text_color="#60a5fa", font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            inner,
            text="Combinadas optimizadas para máximo % de acierto · Solo Doble Oportunidad (1X / X2 / 12) y Goles (Over/Under 2.5)",
            text_color="#93c5fd", font=ctk.CTkFont(size=10),
            wraplength=900, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        kpi_row = ctk.CTkFrame(inner, fg_color="transparent")
        kpi_row.grid(row=0, column=1, sticky="e", padx=(16, 0))
        for lbl, val in [("DC", "~65-75% hit"), ("Goles", "~55-62% hit"), ("2 patas", "~40-50% hit combinada")]:
            f = ctk.CTkFrame(kpi_row, fg_color="#1e3a5f", corner_radius=8)
            f.pack(side="left", padx=4)
            ctk.CTkLabel(f, text=lbl, text_color="#93c5fd", font=ctk.CTkFont(size=9)).pack(padx=8, pady=(4, 0))
            ctk.CTkLabel(f, text=val, text_color="#60a5fa", font=ctk.CTkFont(size=10, weight="bold")).pack(padx=8, pady=(0, 4))

    # ── Cards de combinadas ───────────────────────────────────────────────────

    def _build_recommended_card(self, combo: Dict) -> None:
        """Card especial para la apuesta recomendada (cuota 1.45-2.10)."""
        prob  = combo["combined_prob"]
        odds  = combo["combined_odds"]
        ev    = combo["ev"]

        card = ctk.CTkFrame(
            self.scroll, fg_color="#061220", corner_radius=16,
            border_color="#22c55e", border_width=2,
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        card.grid_columnconfigure(0, weight=1)

        # Cabecera destacada
        header = ctk.CTkFrame(card, fg_color="#060f07", corner_radius=12)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 6))
        ctk.CTkLabel(
            title_row,
            text="⭐  APUESTA RECOMENDADA  —  TRIPLE FILTRO  ⭐",
            text_color="#ffd700", font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            title_row,
            text="ML + Poisson + Consenso multi-casa",
            text_color="#22c55e", font=ctk.CTkFont(size=11),
        ).pack(side="right")

        # KPIs
        kpi_frame = ctk.CTkFrame(header, fg_color="transparent")
        kpi_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 12))

        kelly_pct   = float(combo.get("kelly_pct", 0) or 0)
        kelly_txt   = f"{kelly_pct:.1%}" if kelly_pct > 0 else "—"
        corr_info   = combo.get("corr_info", {})
        corr_sum    = corr_info.get("summary", "") if corr_info else ""

        kpis = [
            ("Cuota total",    f"@ {odds:.2f}",   TEXT),
            ("% Acierto Est.", f"{prob:.1%}",      _prob_color(prob)),
            ("EV esperado",    f"{ev:+.1%}",       _ev_color(ev)),
            ("¼ Kelly stake",  kelly_txt,          "#22d3ee" if kelly_pct > 0 else MUTED),
            ("Metodología",    "ML+DC+Consenso",   "#22c55e"),
        ]
        for k, (label, value, color) in enumerate(kpis):
            kpi = ctk.CTkFrame(kpi_frame, fg_color="#091408", corner_radius=10)
            kpi.grid(row=0, column=k, padx=5, pady=4, sticky="ew")
            kpi_frame.grid_columnconfigure(k, weight=1)
            ctk.CTkLabel(kpi, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12, pady=(8, 1))
            ctk.CTkLabel(kpi, text=value, text_color=color,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(0, 8))

        if corr_sum:
            corr_color = "#f59e0b" if corr_info.get("rho_max", 0) >= 0.15 else "#60a5fa"
            ctk.CTkLabel(
                header, text=corr_sum,
                text_color=corr_color, font=ctk.CTkFont(size=10),
            ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 8))

        # Legs
        legs_frame = ctk.CTkFrame(card, fg_color="transparent")
        legs_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        legs_frame.grid_columnconfigure(0, weight=1)

        for j, leg in enumerate(combo["legs"]):
            self._build_recommended_leg(legs_frame, j, leg)

        self._build_save_bar(card, combo)

    def _build_recommended_leg(self, parent, idx: int, leg) -> None:
        """Leg con desglose ML vs DC y consenso."""
        bg = "#050e1c" if idx % 2 == 0 else "#061220"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10)
        row.grid(row=idx, column=0, sticky="ew", pady=3)
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row, text=f"  {idx + 1}  ",
            fg_color="#22c55e", corner_radius=6,
            text_color="white", font=ctk.CTkFont(size=11, weight="bold"), width=30,
        ).grid(row=0, column=0, padx=(10, 10), pady=10)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=6)
        ctk.CTkLabel(
            info,
            text=f"{leg.get('home_team', '?')} vs {leg.get('away_team', '?')}",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")

        expl = _leg_explanation(leg)
        if expl:
            ctk.CTkLabel(
                info, text=expl,
                text_color="#7ecf9a",
                font=ctk.CTkFont(size=10),
                wraplength=420, justify="left",
            ).pack(anchor="w", pady=(2, 0))

        # Desglose del ensemble
        p_ml  = leg.get("p_home_ml") or leg.get("model_prob", 0)
        p_dc  = leg.get("p_home_dc")
        p_ens = leg.get("model_prob", 0)
        cons  = leg.get("consensus_edge")
        n_bks = leg.get("n_bookmakers", 0)

        fecha_str    = _fmt_fecha(leg.get("date"), leg.get("time", ""))
        detail_parts = [f"{leg.get('league','')}  ·  📅 {fecha_str}"]
        if p_dc is not None and pd.notna(p_dc):
            detail_parts.append(f"ML:{float(p_ml):.0%} DC:{float(p_dc):.0%} Ens:{float(p_ens):.0%}")
        if cons is not None and pd.notna(cons):
            detail_parts.append(f"ConsEdge:{float(cons):+.1%} ({n_bks} casas)")
        ctk.CTkLabel(
            info, text="  ·  ".join(detail_parts),
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(anchor="w")

        # Métricas
        metrics = ctk.CTkFrame(row, fg_color="transparent")
        metrics.grid(row=0, column=2, padx=16, pady=6, sticky="e")
        pick = leg.get("pick", "—")
        odds = leg.get("odds", 0)
        rel  = leg.get("reliability_score", 0)
        for k, (lbl, val) in enumerate([
            ("Pick",  f"{pick} @ {float(odds):.2f}"),
            ("Rel",   f"{int(rel)} / 99"),
        ]):
            ctk.CTkLabel(metrics, text=lbl, text_color=MUTED,
                         font=ctk.CTkFont(size=9)).grid(row=0, column=k*2, padx=(10, 2))
            ctk.CTkLabel(metrics, text=val, text_color=TEXT,
                         font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=k*2+1, padx=(0, 10))

    def _build_combo_card(self, idx: int, combo: Dict) -> None:
        n        = combo["n_legs"]
        prob     = combo["combined_prob"]
        odds     = combo["combined_odds"]
        ev       = combo["ev"]
        avg_rel  = combo["avg_reliability"]
        mix      = combo.get("market_mix", {})
        flags    = combo.get("flags")
        is_safe  = combo.get("safe_mode", False)

        border_color = "#3b82f6" if is_safe else BORDER
        card = ctk.CTkFrame(
            self.scroll, fg_color=CARD, corner_radius=16,
            border_color=border_color, border_width=1,
        )
        card.grid(row=idx, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        self._build_card_header(card, combo, safe_mode=is_safe)
        self._build_card_legs(card, combo["legs"], flags=flags)
        self._build_save_bar(card, combo)

    def _build_save_bar(self, card, combo: Dict) -> None:
        """Barra inferior con el botón Guardar en Portfolio (auto-liquidación)."""
        bar = ctk.CTkFrame(card, fg_color="transparent")
        bar.grid(row=98, column=0, sticky="ew", padx=14, pady=(0, 12))
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bar,
            text="Guárdala para seguir su resultado y que cuente en tu ROI",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            bar, text="💾  Guardar en Portfolio", width=190, height=30,
            fg_color="#10301a", hover_color="#164a26",
            border_color="#22c55e", border_width=1,
            text_color="#a7f3c0", font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda c=combo: self._on_save_combo(c),
        ).grid(row=0, column=1, sticky="e")

    def _on_save_combo(self, combo: Dict) -> None:
        """Delega en la app el guardado de la combinada IA en el Portfolio."""
        save = getattr(self.app, "save_ia_combo", None)
        if not callable(save):
            return
        try:
            save(combo)
        except Exception as exc:   # pragma: no cover — defensivo en UI
            import tkinter.messagebox as _mb
            _mb.showerror("Combinada IA", f"No se pudo guardar la combinada:\n{exc}")

    def _build_card_header(
        self, card, combo: Dict, safe_mode: bool = False,
    ) -> None:
        n       = combo["n_legs"]
        prob    = combo["combined_prob"]
        odds    = combo["combined_odds"]
        ev      = combo["ev"]
        avg_rel = combo["avg_reliability"]
        mix     = combo.get("market_mix", {})
        hbg = "#0c1a2e" if safe_mode else "#061220"
        header = ctk.CTkFrame(card, fg_color=hbg, corner_radius=12)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        # Título + badges de mercados incluidos
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")

        badge = "🛡 SEGURA" if safe_mode else f"{'★' * n}"
        label_color = "#60a5fa" if safe_mode else TEXT
        ctk.CTkLabel(
            title_row,
            text=f"  {badge}  COMBINADA  {n}  SELECCIONES",
            text_color=label_color, font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")

        # Badges de tipos de mercado en la combinada
        if mix:
            from ...core.accumulator import MARKET_BADGE as _MB
            for mtype, count in mix.items():
                lbl, bg = _MB.get(mtype, ("?", "#333"))
                ctk.CTkLabel(
                    title_row,
                    text=f"  {lbl}×{count}  ",
                    fg_color=bg, corner_radius=4,
                    text_color="white", font=ctk.CTkFont(size=9, weight="bold"),
                ).pack(side="left", padx=(6, 0))

        # KPIs
        kpi_frame = ctk.CTkFrame(header, fg_color="transparent")
        kpi_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

        kelly_pct  = combo.get("kelly_pct", 0.0) if hasattr(combo, "get") else 0.0
        corr_info  = combo.get("corr_info", {})  if hasattr(combo, "get") else {}
        kelly_pct  = float(kelly_pct or 0)
        kelly_txt  = f"{kelly_pct:.1%}" if kelly_pct > 0 else "—"
        kelly_col  = "#22d3ee" if kelly_pct > 0 else MUTED

        kpis = [
            ("Cuota total",    f"@ {odds:.2f}",       TEXT),
            ("% Acierto Est.", f"{prob:.1%}",          _prob_color(prob)),
            ("EV esperado",    f"{ev:+.1%}",           _ev_color(ev)),
            ("¼ Kelly stake",  kelly_txt,              kelly_col),
            ("Fiabilidad",     f"{avg_rel:.0f} / 99",  MUTED),
            ("Selecciones",    str(n),                 ACCENT),
        ]
        for k, (label, value, color) in enumerate(kpis):
            kpi = ctk.CTkFrame(kpi_frame, fg_color="#091408", corner_radius=10)
            kpi.grid(row=0, column=k, padx=5, pady=4, sticky="ew")
            kpi_frame.grid_columnconfigure(k, weight=1)
            ctk.CTkLabel(
                kpi, text=label, text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).pack(anchor="w", padx=12, pady=(8, 1))
            ctk.CTkLabel(
                kpi, text=value, text_color=color,
                font=ctk.CTkFont(size=16, weight="bold"),
            ).pack(anchor="w", padx=12, pady=(0, 8))

        # Aviso de correlación entre legs
        corr_summary = corr_info.get("summary", "") if corr_info else ""
        if corr_summary:
            corr_color = "#f59e0b" if corr_info.get("rho_max", 0) >= 0.15 else "#60a5fa"
            ctk.CTkLabel(
                header, text=corr_summary,
                text_color=corr_color, font=ctk.CTkFont(size=10),
            ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 8))

    def _build_card_legs(self, card, legs: list, flags: list | None = None) -> None:
        legs_frame = ctk.CTkFrame(card, fg_color="transparent")
        legs_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        legs_frame.grid_columnconfigure(0, weight=1)

        for j, leg in enumerate(legs):
            leg_flags = flags[j] if flags and j < len(flags) else None
            self._build_leg_row(legs_frame, j, leg, flags=leg_flags)

        # ── Nota de honestidad ────────────────────────────────────────────────
        ctk.CTkLabel(
            card,
            text="⚠ % acierto estimado por el modelo (calibración OOS) — no es probabilidad garantizada",
            text_color="#4a7a5a", font=ctk.CTkFont(size=9),
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 10))

    def _build_leg_row(self, parent, idx: int, leg, flags: dict | None = None) -> None:
        bg = "#050e1c" if idx % 2 == 0 else "#061220"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10)
        row.grid(row=idx, column=0, sticky="ew", pady=3)
        row.grid_columnconfigure(1, weight=1)

        # ── Badge de número con color por tipo de mercado ─────────────────────
        mtype = leg.get("market_type", "1X2")
        is_claude = str(leg.get("risk_light", "")) == "CLAUDE"
        if is_claude:
            badge_color = "#6d28d9"
        elif mtype == "double_chance":
            badge_color = "#1a4d8a"    # azul
        elif mtype == "goals":
            badge_color = "#7a3a0a"    # naranja oscuro
        else:
            badge_color = "#166534"    # verde

        ctk.CTkLabel(
            row, text=f"  {idx + 1}  ",
            fg_color=badge_color, corner_radius=6,
            text_color="white", font=ctk.CTkFont(size=11, weight="bold"),
            width=30,
        ).grid(row=0, column=0, padx=(10, 8), pady=10)

        # ── Info del partido ──────────────────────────────────────────────────
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=6)

        # Partido + badge de mercado
        match_row = ctk.CTkFrame(info, fg_color="transparent")
        match_row.pack(anchor="w")

        ctk.CTkLabel(
            match_row,
            text=f"{leg.get('home_team', '?')} vs {leg.get('away_team', '?')}",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")

        # Badge tipo mercado
        badge_lbl, badge_bg = MARKET_BADGE.get(mtype, ("1X2", "#1a4d2a"))
        ctk.CTkLabel(
            match_row, text=f"  {badge_lbl}  ",
            fg_color=badge_bg, corner_radius=4,
            text_color="white", font=ctk.CTkFont(size=9, weight="bold"),
        ).pack(side="left", padx=(8, 0))

        # Liga + fecha + hora + pick en español
        pick          = leg.get("pick", "—")
        pick_label    = PICK_LABELS.get(pick, pick)
        fecha_str     = _fmt_fecha(leg.get("date"), leg.get("time", ""))
        liga_str      = leg.get("league", "")
        meta_text     = f"{liga_str}  ·  📅 {fecha_str}" if liga_str else f"📅 {fecha_str}"
        ctk.CTkLabel(
            info,
            text=meta_text,
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(anchor="w")
        ctk.CTkLabel(
            info,
            text=f"📌 {pick_label}",
            text_color="#7ecf9a", font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", pady=(1, 0))

        # Indicadores de confirmación del análisis profundo
        if flags:
            conf_parts = []
            if flags.get("ml_dc_agree"):   conf_parts.append("ML+DC✓")
            if flags.get("has_consensus"): conf_parts.append("Cons✓")
            if flags.get("clv_positive"):  conf_parts.append("CLV✓")
            if flags.get("high_prob"):     conf_parts.append("P✓")
            if conf_parts:
                ctk.CTkLabel(
                    info, text="  ".join(conf_parts),
                    text_color=ACCENT, font=ctk.CTkFont(size=9),
                ).pack(anchor="w", pady=(1, 0))

        # Explicación IA del leg
        expl = _leg_explanation(leg)
        if expl:
            ctk.CTkLabel(
                info, text=expl,
                text_color="#5a9a6a",
                font=ctk.CTkFont(size=10),
                wraplength=420, justify="left",
            ).pack(anchor="w", pady=(2, 0))

        # ── Métricas ──────────────────────────────────────────────────────────
        metrics = ctk.CTkFrame(row, fg_color="transparent")
        metrics.grid(row=0, column=2, padx=12, pady=6, sticky="e")

        odds  = float(leg.get("odds", 0) or 0)
        edge  = float(leg.get("edge", 0) or 0)
        prob  = float(leg.get("model_prob", 0) or 0)
        rel   = int(leg.get("reliability_score", 0) or 0)
        mtype = leg.get("market_type", "1X2")

        # Mostrar P(IA) con contexto del mercado
        prob_label = "P(IA)" if mtype == "1X2" else ("P(modelo)" if mtype == "goals" else "P(DC)")

        metric_items = [
            ("Cuota",      f"{pick} @ {odds:.2f}"),
            (prob_label,   f"{prob:.1%}"),
            ("Edge",       f"{edge:.2%}"),
            ("Rel",        f"{rel}/99"),
        ]
        for k, (lbl, val) in enumerate(metric_items):
            ctk.CTkLabel(
                metrics, text=lbl, text_color=MUTED,
                font=ctk.CTkFont(size=9),
            ).grid(row=0, column=k * 2, padx=(8, 2), sticky="e")
            ctk.CTkLabel(
                metrics, text=val, text_color=TEXT,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=k * 2 + 1, padx=(0, 8), sticky="w")

    def _open_chat_with_context(self) -> None:
        """Abre el Chat IA con contexto de las combinadas actuales."""
        has_combos = hasattr(self, "_combos") and self._combos
        if not has_combos:
            from tkinter import messagebox
            messagebox.showinfo(
                "Chat IA",
                "Ejecuta primero un análisis para generar combinadas."
            )
            return
        n = len(self._combos)
        self.app.show_chat_view(
            source_view="accumulator",
            prefill=f"Tengo {n} combinadas generadas. ¿Por qué recomiendas estas patas juntas y cuál tiene mejor relación riesgo-recompensa?",
        )

    # ── Calibración de pesos ──────────────────────────────────────────────────

    def _update_calib_btn_label(self) -> None:
        """Actualiza el label del botón de calibración según el estado actual."""
        if not hasattr(self, "_calib_btn"):
            return
        cal = get_calibrator()
        if cal.is_calibrated:
            self._calib_btn.configure(
                text=f"🔬 Pesos calibrados ({cal.n_samples} picks)",
                fg_color="#0a1f0a", border_color="#22c55e", text_color="#86efac",
            )
        else:
            self._calib_btn.configure(
                text="🔬 Calibrar pesos",
                fg_color="#1a1200", border_color="#ca8a04", text_color="#fde047",
            )

    def _calibrate_weights(self) -> None:
        """Ejecuta la calibración de pesos con los picks históricos liquidados."""
        from tkinter import messagebox
        try:
            from ...core.config import DB_FILE
        except ImportError:
            DB_FILE = str(
                __import__("pathlib").Path(__file__).parent.parent.parent / "football_analyzer.db"
            )

        cal    = get_calibrator()
        result = cal.fit(DB_FILE)

        self._update_calib_btn_label()

        if result["ok"]:
            messagebox.showinfo(
                "Calibración completada",
                f"✓ Pesos actualizados con {result['n']} picks históricos.\n\n"
                "Vuelve a generar las combinadas para usar los nuevos pesos.",
            )
        else:
            n = result["n"]
            from ...core.accumulator_calibrator import MIN_SAMPLES
            faltan = max(0, MIN_SAMPLES - n)
            messagebox.showinfo(
                "Calibración — datos insuficientes",
                f"{result['msg']}\n\n"
                + (
                    f"Faltan {faltan} picks liquidados para activar la calibración.\n"
                    "Los picks se liquidan automáticamente desde la vista Portfolio."
                    if faltan > 0 else
                    result["msg"]
                ),
            )
