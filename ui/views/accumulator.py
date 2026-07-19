"""
ui/views/accumulator.py — Vista de Combinadas IA.

Muestra las mejores combinadas generadas por el motor IA con
probabilidad de acierto, EV esperado y detalle de cada selección.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List

import customtkinter as ctk
import pandas as pd
import numpy as np

from ...core.accumulator import build_smart_accumulators, build_recommended_combo
from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ..widgets import make_card


def _prob_color(prob: float) -> str:
    """Verde / amarillo / rojo según probabilidad combinada."""
    if prob >= 0.40:
        return "#00c853"
    if prob >= 0.25:
        return "#ffd600"
    return "#ff5252"


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
        ctrl.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            ctrl, text="⚡  Combinadas IA",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")

        ctk.CTkLabel(
            ctrl, text="Legs máx:", text_color=MUTED,
        ).grid(row=0, column=1, padx=(20, 6))

        self.max_legs_var = tk.StringVar(value="4")
        ctk.CTkOptionMenu(
            ctrl, variable=self.max_legs_var,
            values=["2", "3", "4"],
            fg_color=CARD_2, button_color=ACCENT,
            width=80,
        ).grid(row=0, column=2, padx=(0, 16))

        self.status_lbl = ctk.CTkLabel(ctrl, text="Ejecuta el análisis y pulsa Generar.", text_color=MUTED)
        self.status_lbl.grid(row=0, column=3, sticky="w", padx=8)

        ctk.CTkButton(
            ctrl, text="⚡  Generar combinadas",
            command=self.refresh,
            fg_color=ACCENT, hover_color=ACCENT_2, height=38,
        ).grid(row=0, column=4, padx=16, pady=14, sticky="e")

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

        # Limpiar cards anteriores
        for w in self.scroll.winfo_children():
            w.destroy()

        if df is None or df.empty:
            self.status_lbl.configure(text="Ejecuta el análisis primero.")
            self._show_empty("No hay datos de análisis.\nPulsa ▶  Run Analysis en el menú lateral.")
            return

        max_legs = int(self.max_legs_var.get())
        self._combos = build_smart_accumulators(df, max_legs=max_legs)

        # ── Apuesta recomendada 1.5-2.0 (triple filtro) ──────────────────────
        recommended = build_recommended_combo(df)
        row_offset = 0
        if recommended:
            self._build_recommended_card(recommended)
            row_offset = 1

        if not self._combos:
            self.status_lbl.configure(text="Sin picks suficientes para combinadas.")
            if not recommended:
                self._show_empty(
                    "⚠️  No hay picks con ventaja estadística suficiente.\n\n"
                    "Asegúrate de que el análisis ha generado picks VERDE o AMARILLO."
                )
            return

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

    # ── Cards de combinadas ───────────────────────────────────────────────────

    def _build_recommended_card(self, combo: Dict) -> None:
        """Card especial para la apuesta recomendada (cuota 1.45-2.10)."""
        prob  = combo["combined_prob"]
        odds  = combo["combined_odds"]
        ev    = combo["ev"]

        card = ctk.CTkFrame(
            self.scroll, fg_color="#0d2040", corner_radius=16,
            border_color="#3b82f6", border_width=2,
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        card.grid_columnconfigure(0, weight=1)

        # Cabecera destacada
        header = ctk.CTkFrame(card, fg_color="#0a1830", corner_radius=12)
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
            text_color="#3b82f6", font=ctk.CTkFont(size=11),
        ).pack(side="right")

        # KPIs
        kpi_frame = ctk.CTkFrame(header, fg_color="transparent")
        kpi_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 12))

        kpis = [
            ("Cuota total",  f"@ {odds:.2f}",         TEXT),
            ("Prob. ensemble", f"{prob:.1%}",          _prob_color(prob)),
            ("EV esperado",  f"{ev:+.1%}",             _ev_color(ev)),
            ("Metodología",  "ML+DC+Consenso",         "#3b82f6"),
        ]
        for k, (label, value, color) in enumerate(kpis):
            kpi = ctk.CTkFrame(kpi_frame, fg_color="#111f36", corner_radius=10)
            kpi.grid(row=0, column=k, padx=5, pady=4, sticky="ew")
            kpi_frame.grid_columnconfigure(k, weight=1)
            ctk.CTkLabel(kpi, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12, pady=(8, 1))
            ctk.CTkLabel(kpi, text=value, text_color=color,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=12, pady=(0, 8))

        # Legs
        legs_frame = ctk.CTkFrame(card, fg_color="transparent")
        legs_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        legs_frame.grid_columnconfigure(0, weight=1)

        for j, leg in enumerate(combo["legs"]):
            self._build_recommended_leg(legs_frame, j, leg)

    def _build_recommended_leg(self, parent, idx: int, leg) -> None:
        """Leg con desglose ML vs DC y consenso."""
        bg = "#0e1e38" if idx % 2 == 0 else "#0b1830"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10)
        row.grid(row=idx, column=0, sticky="ew", pady=3)
        row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row, text=f"  {idx + 1}  ",
            fg_color="#3b82f6", corner_radius=6,
            text_color="white", font=ctk.CTkFont(size=11, weight="bold"), width=30,
        ).grid(row=0, column=0, padx=(10, 10), pady=10)

        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=6)
        ctk.CTkLabel(
            info,
            text=f"{leg.get('home_team', '?')} vs {leg.get('away_team', '?')}",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")

        # Desglose del ensemble
        p_ml  = leg.get("p_home_ml") or leg.get("model_prob", 0)
        p_dc  = leg.get("p_home_dc")
        p_ens = leg.get("model_prob", 0)
        cons  = leg.get("consensus_edge")
        n_bks = leg.get("n_bookmakers", 0)

        detail_parts = [f"Liga: {leg.get('league','')}"]
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

        card = ctk.CTkFrame(
            self.scroll, fg_color=CARD, corner_radius=16,
            border_color=BORDER, border_width=1,
        )
        card.grid(row=idx, column=0, sticky="ew", pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        self._build_card_header(card, n, prob, odds, ev, avg_rel)
        self._build_card_legs(card, combo["legs"])

    def _build_card_header(
        self, card, n: int, prob: float, odds: float, ev: float, avg_rel: float
    ) -> None:
        header = ctk.CTkFrame(card, fg_color="#0d1e35", corner_radius=12)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        # Título
        ctk.CTkLabel(
            header,
            text=f"  {'★' * n}  COMBINADA  {n}  SELECCIONES",
            text_color=TEXT, font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, padx=14, pady=(12, 8), sticky="w")

        # KPIs
        kpi_frame = ctk.CTkFrame(header, fg_color="transparent")
        kpi_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 12))

        kpis = [
            ("Cuota total",  f"@ {odds:.2f}",           TEXT),
            ("Prob. IA",     f"{prob:.1%}",              _prob_color(prob)),
            ("EV esperado",  f"{ev:+.1%}",               _ev_color(ev)),
            ("Fiabilidad",   f"{avg_rel:.0f} / 99",      MUTED),
            ("Selecciones",  str(n),                     ACCENT),
        ]
        for k, (label, value, color) in enumerate(kpis):
            kpi = ctk.CTkFrame(kpi_frame, fg_color="#111f36", corner_radius=10)
            kpi.grid(row=0, column=k, padx=5, pady=4, sticky="ew")
            kpi_frame.grid_columnconfigure(k, weight=1)
            ctk.CTkLabel(
                kpi, text=label, text_color=MUTED,
                font=ctk.CTkFont(size=10),
            ).pack(anchor="w", padx=12, pady=(8, 1))
            ctk.CTkLabel(
                kpi, text=value, text_color=color,
                font=ctk.CTkFont(size=18, weight="bold"),
            ).pack(anchor="w", padx=12, pady=(0, 8))

    def _build_card_legs(self, card, legs: list) -> None:
        legs_frame = ctk.CTkFrame(card, fg_color="transparent")
        legs_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))
        legs_frame.grid_columnconfigure(0, weight=1)

        for j, leg in enumerate(legs):
            self._build_leg_row(legs_frame, j, leg)

    def _build_leg_row(self, parent, idx: int, leg) -> None:
        bg = "#0e1c2f" if idx % 2 == 0 else "#0b1525"
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=10)
        row.grid(row=idx, column=0, sticky="ew", pady=3)
        row.grid_columnconfigure(1, weight=1)

        # Número
        ctk.CTkLabel(
            row, text=f"  {idx + 1}  ",
            fg_color=ACCENT, corner_radius=6,
            text_color="white", font=ctk.CTkFont(size=11, weight="bold"),
            width=30,
        ).grid(row=0, column=0, padx=(10, 10), pady=10)

        # Partido + liga
        info = ctk.CTkFrame(row, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=6)
        ctk.CTkLabel(
            info,
            text=f"{leg.get('home_team', '?')} vs {leg.get('away_team', '?')}",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            info,
            text=f"{leg.get('league', '')}  ·  {str(leg.get('date', ''))[:10]}",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(anchor="w")

        # Métricas del leg
        metrics = ctk.CTkFrame(row, fg_color="transparent")
        metrics.grid(row=0, column=2, padx=16, pady=6, sticky="e")

        pick = leg.get("pick", "—")
        odds = leg.get("odds", 0)
        edge = leg.get("edge", 0)
        prob = leg.get("model_prob", 0)
        rel  = leg.get("reliability_score", 0)

        metric_items = [
            ("Pick",   f"{pick} @ {float(odds):.2f}"),
            ("Edge",   f"{float(edge):.2%}"),
            ("P(IA)",  f"{float(prob):.1%}"),
            ("Rel",    f"{int(rel)} / 99"),
        ]
        for k, (lbl, val) in enumerate(metric_items):
            ctk.CTkLabel(
                metrics, text=lbl, text_color=MUTED,
                font=ctk.CTkFont(size=9),
            ).grid(row=0, column=k * 2, padx=(10, 2), sticky="e")
            ctk.CTkLabel(
                metrics, text=val, text_color=TEXT,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=k * 2 + 1, padx=(0, 10), sticky="w")
