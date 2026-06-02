"""
ui/views/analysis.py — Vista principal: Trading Desk con tabla de picks.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk
import numpy as np
import pandas as pd

from ...core.config import (
    ACCENT, ACCENT_2, BG, BORDER, CARD, CARD_2,
    LEAGUE_MAP, MUTED, TEXT,
)
from ..widgets import make_card, make_textbox, textbox_set


class _ColumnTooltip:
    """Muestra un tooltip al pasar el ratón por las cabeceras del Treeview."""
    TIPS: dict = {
        "edge":              "Ventaja del modelo vs el mercado (>3% = valor estadístico)",
        "clv":               "Closing Line Value — si la cuota bajó tras tu pick, el mercado te dio la razón",
        "model_prob":        "Probabilidad ensemble (ML 60% + Dixon-Coles 40%)",
        "fair_prob":         "Probabilidad implícita del mercado sin el margen de la casa",
        "ev":                "Expected Value: ganancia media por cada €1 apostado",
        "bankroll_pct":      "Kelly fraccionado: % de bankroll sugerido por la fórmula Kelly",
        "reliability_score": "0–99 — calidad de la predicción (≥74: sólida, <58: descartada)",
        "consensus_edge":    "Edge vs promedio de 20+ casas. Más fiable que una sola casa.",
        "open_overround":    "Sobreround de apertura (>1.08 = margen alto, mercado menos eficiente)",
        "market_entropy":    "Entropía del mercado: alto = partido muy incierto",
        "p_home":            "P(Local gana) — probabilidad final del ensemble",
        "p_away":            "P(Visitante gana) — probabilidad final del ensemble",
        "p_over25":          "P(+2.5 goles) — del modelo GradientBoosting calibrado",
    }

    def __init__(self, tree: ttk.Treeview) -> None:
        self._tree = tree
        self._tw: "tk.Toplevel | None" = None
        tree.bind("<Motion>", self._on_motion)
        tree.bind("<Leave>",  self._hide)

    def _on_motion(self, event) -> None:
        region = self._tree.identify_region(event.x, event.y)
        if region != "heading":
            self._hide()
            return
        col = self._tree.identify_column(event.x)
        col_id = self._tree.column(col, "id") if col else ""
        tip = self.TIPS.get(col_id, "")
        if not tip:
            self._hide()
            return
        self._show(tip, event.x_root + 14, event.y_root + 14)

    def _show(self, text: str, x: int, y: int) -> None:
        self._hide()
        self._tw = tw = tk.Toplevel(self._tree)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=text, justify="left",
            background="#0f2914", foreground="#f0fff4",
            relief="flat", padx=10, pady=6,
            font=("Segoe UI", 10),
            wraplength=320,
        ).pack()

    def _hide(self, *_) -> None:
        if self._tw:
            self._tw.destroy()
            self._tw = None


TREE_HEADERS = {
    "date": "Fecha", "league": "Liga", "home_team": "Local",
    "away_team": "Visitante", "pick": "Pick", "odds": "Cuota",
    "edge": "Edge", "model_prob": "P(Modelo)", "fair_prob": "P(Mercado)",
    "open_fair_prob": "P(Apertura)", "close_fair_prob": "P(Cierre)",
    "clv": "CLV", "open_overround": "Overround",
    "ev": "EV", "reliability_score": "Fiabilidad",
    "bankroll_pct": "Kelly%", "analysis": "Análisis",
}

TREE_COLUMNS = [
    "date", "league", "home_team", "away_team",
    "pick", "odds", "edge", "model_prob", "fair_prob",
    "open_fair_prob", "close_fair_prob", "clv",
    "open_overround", "ev", "reliability_score",
    "bankroll_pct", "analysis",
]

TREE_WIDTHS = {
    "date": 95, "league": 80, "home_team": 145, "away_team": 145,
    "pick": 88, "odds": 62, "edge": 62, "model_prob": 78,
    "fair_prob": 78, "open_fair_prob": 88, "close_fair_prob": 88,
    "clv": 62, "open_overround": 88, "ev": 62,
    "reliability_score": 85, "bankroll_pct": 80, "analysis": 320,
}


class AnalysisView(ctk.CTkFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()

    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_left_panel()
        self._build_center_panel()

    # ── Left panel ─────────────────────────────────────────────────────────────

    def _build_left_panel(self):
        left = ctk.CTkFrame(self, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))

        card = make_card(left, "Ligas y control")
        card.pack(fill="x", pady=(0, 10))

        lb = ctk.CTkFrame(card, fg_color="transparent")
        lb.pack(fill="x", padx=12, pady=(0, 12))

        # Liga checkboxes
        self.league_vars: dict[str, tk.BooleanVar] = {}
        default_on = {"Premier League", "La Liga"}
        for name in LEAGUE_MAP:
            var = tk.BooleanVar(value=name in default_on)
            self.league_vars[name] = var
            ctk.CTkCheckBox(
                lb, text=name, variable=var,
                text_color=TEXT, fg_color=ACCENT,
            ).pack(anchor="w", pady=2)

        # Parámetros
        for label, var in [
            ("Edge 1X2",        self.app.edge1),
            ("Edge Over 2.5",   self.app.edge2),
            ("Bankroll base (€)", self.app.unit_stake),
        ]:
            ctk.CTkLabel(lb, text=label, text_color=MUTED).pack(anchor="w", pady=(8, 2))
            ctk.CTkEntry(
                lb, textvariable=var,
                fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            ).pack(fill="x")

        ctk.CTkCheckBox(
            lb, text="Solo verde premium",
            variable=self.app.only_green,
            command=self.app.apply_filters,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=(8, 2))

        ctk.CTkCheckBox(
            lb, text="Solo picks activos",
            variable=self.app.only_picks,
            command=self.app.apply_filters,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)

        ctk.CTkButton(
            lb, text="Guardar workspace",
            command=self.app.save_settings,
            fg_color="#0a2210",
        ).pack(fill="x", pady=(8, 0))

    # ── Center panel ───────────────────────────────────────────────────────────

    def _build_center_panel(self):
        self._iid_map: dict[str, str] = {}

        center = make_card(
            self, "Resultados",
            "Trading Desk principal con top picks, tabla y visión de valor",
        )
        center.grid(row=0, column=1, sticky="nsew")

        # Search bar + status
        bar = ctk.CTkFrame(center, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(0, 8))
        self.status_label = ctk.CTkLabel(bar, text="Listo", text_color=MUTED)
        self.status_label.pack(side="right")
        ctk.CTkEntry(
            bar, textvariable=self.app.search_var,
            placeholder_text="Buscar equipo, liga o pick",
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
        ).pack(side="left", fill="x", expand=True)
        self.app.search_var.trace_add("write", lambda *_: self.app.apply_filters())

        # KPI hero row
        hero = ctk.CTkFrame(
            center, fg_color="#060f07",
            border_color=BORDER, border_width=1, corner_radius=14,
        )
        hero.pack(fill="x", padx=14, pady=(0, 8))
        hero.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.metric_labels: list[ctk.CTkLabel] = []
        for idx, title in enumerate(["Matches", "Picks", "ROI (OOS)", "CLV picks"]):
            box = ctk.CTkFrame(hero, fg_color="#06100a", corner_radius=12)
            box.grid(row=0, column=idx, padx=6, pady=10, sticky="ew")
            ctk.CTkLabel(
                box, text=title, text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=12, pady=(10, 2))
            val = ctk.CTkLabel(
                box, text="—", text_color=TEXT,
                font=ctk.CTkFont(size=22, weight="bold"),
            )
            val.pack(anchor="w", padx=12, pady=(0, 10))
            self.metric_labels.append(val)

        # Backtest summary + diagnostics
        self.summary_box = make_textbox(center, height=110)
        self.summary_box.pack(fill="x", padx=14, pady=(0, 8))

        # Top picks + league ranking
        insight_row = ctk.CTkFrame(center, fg_color="transparent")
        insight_row.pack(fill="x", padx=14, pady=(0, 8))
        insight_row.grid_columnconfigure((0, 1), weight=1)

        tp = make_card(insight_row, "Top Picks", "Las mejores selecciones del análisis actual")
        tp.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.top_picks_box = make_textbox(tp, height=130)
        self.top_picks_box.pack(fill="x", padx=12, pady=(0, 12))

        lr = make_card(insight_row, "League Ranking", "Rendimiento por liga")
        lr.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.league_rank_box = make_textbox(lr, height=130)
        self.league_rank_box.pack(fill="x", padx=12, pady=(0, 12))

        # ── Panel de análisis IA (abajo) ──────────────────────────────────────
        detail_bar = ctk.CTkFrame(
            center, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        detail_bar.pack(side="bottom", fill="x", padx=14, pady=(4, 14))
        ctk.CTkLabel(
            detail_bar, text="🧠  Análisis Claude IA",
            text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 2))
        self._detail_box = make_textbox(detail_bar, height=60)
        self._detail_box.pack(fill="x", padx=12, pady=(0, 8))
        textbox_set(self._detail_box, "Selecciona un partido para ver el análisis IA.")

        # ── Main treeview ──────────────────────────────────────────────────────
        shell = ctk.CTkFrame(center, fg_color="#060f07")
        shell.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(shell, columns=TREE_COLUMNS, show="headings")
        for col in TREE_COLUMNS:
            self.tree.heading(col, text=TREE_HEADERS.get(col, col.upper()))
            self.tree.column(col, width=TREE_WIDTHS.get(col, 100), anchor="center")

        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(
            shell, orient="vertical", command=self.tree.yview
        ).grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("green",  background="#0e2d1d", foreground="#d6ffe6")
        self.tree.tag_configure("yellow", background="#3a2c0e", foreground="#fff0c2")
        self.tree.tag_configure("red",    background="#341313", foreground="#ffd3d3")
        self.tree.tag_configure("grey",   background="#06100a", foreground="#8fa3bf")

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self._col_tooltip = _ColumnTooltip(self.tree)

    # ── Refresh methods ────────────────────────────────────────────────────────

    def update_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def update_metrics(
        self,
        total: int,
        picks: int,
        avg_roi: float,
        clv_count: int,
    ) -> None:
        self.metric_labels[0].configure(text=str(total))
        self.metric_labels[1].configure(text=str(picks))
        self.metric_labels[2].configure(text=f"{avg_roi:.2%}")
        self.metric_labels[3].configure(text=str(clv_count))

    def fill_summary(
        self,
        backtest_summary: dict,
        diagnostics: list[str],
    ) -> None:
        lines = ["=== BACKTEST OOS POR LIGA ==="]
        for div, data in backtest_summary.items():
            lines.append(
                f"{div}: bets {data['bets']} | ROI {data['roi']:.2%} | "
                f"hit {data['hit']:.2%} | 1X2 ROI {data['market_1x2_roi']:.2%} | "
                f"O2.5 ROI {data['market_o25_roi']:.2%} | "
                f"eval_samples {data.get('eval_samples', '?')}"
            )
        lines += [
            "",
            "=== FILTROS ACTIVOS ===",
            f"Overround 1X2 ≤ 1.08 | Over/Under ≤ 1.10 | CLV ≥ -1% | Kelly 0.20 cap 1.5%",
            "",
            "=== DIAGNÓSTICO MODELO ===",
        ] + diagnostics
        textbox_set(self.summary_box, "\n".join(lines))

    def fill_tree(self, df: pd.DataFrame) -> None:
        self._iid_map = {}
        for row in self.tree.get_children():
            self.tree.delete(row)

        if df.empty:
            return

        sorted_df = df.sort_values(
            ["reliability_score", "ev", "edge"],
            ascending=[False, False, False],
            na_position="last",
        )

        for _, row in sorted_df.iterrows():
            no_model = (
                pd.isna(row.get("edge")) and
                pd.isna(row.get("model_prob")) and
                row.get("risk_light") == "ROJO"
            )
            tag = (
                "grey"   if no_model
                else "green"  if row["risk_light"] == "VERDE"
                else "yellow" if row["risk_light"] == "AMARILLO"
                else "red"
            )
            vals = []
            for col in TREE_COLUMNS:
                v = row.get(col, "")
                if col == "date" and pd.notna(v):
                    try:
                        v = pd.to_datetime(v).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                vals.append(v)
            iid = self.tree.insert("", "end", values=vals, tags=(tag,))
            key = f"{row.get('home_team', '')}::{row.get('away_team', '')}"
            self._iid_map[key] = iid

    def fill_top_picks(self, df: pd.DataFrame) -> None:
        if df.empty:
            textbox_set(self.top_picks_box, "Todavía no hay picks cargados.")
            return
        sort_cols = [c for c in ["reliability_score", "edge", "ev"] if c in df.columns]
        top = df.sort_values(sort_cols, ascending=False).head(5)
        lines = [
            f"{i}. {r.get('home_team','')} vs {r.get('away_team','')} | "
            f"{r.get('pick','NO BET')} @ {r.get('odds','')} | "
            f"Edge {r.get('edge','')} | EV {r.get('ev','')} | Rel {r.get('reliability_score','')}"
            for i, (_, r) in enumerate(top.iterrows(), 1)
        ]
        textbox_set(self.top_picks_box, "\n".join(lines))

    def update_pick_analysis(self, match_key: str, text: str) -> None:
        """Actualiza la columna Análisis de un partido cuando Claude responde."""
        iid = self._iid_map.get(match_key)
        if not iid:
            return
        try:
            vals = list(self.tree.item(iid, "values"))
            ai_idx = TREE_COLUMNS.index("analysis")
            vals[ai_idx] = text
            self.tree.item(iid, values=vals)
            if iid in self.tree.selection():
                textbox_set(self._detail_box, text)
        except Exception:
            pass

    def _on_row_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        if not vals:
            return
        try:
            ai_idx = TREE_COLUMNS.index("analysis")
            text = str(vals[ai_idx]) if vals[ai_idx] else "—"
            textbox_set(self._detail_box, text)
        except Exception:
            pass

    def fill_league_ranking(self, df: pd.DataFrame) -> None:
        if df.empty or "league" not in df.columns:
            textbox_set(self.league_rank_box, "Todavía no hay ligas analizadas.")
            return
        rank = (
            df.groupby("league")
            .agg(matches=("league", "size"), avg_edge=("edge", "mean"),
                 avg_ev=("ev", "mean"), avg_rel=("reliability_score", "mean"))
            .reset_index()
            .sort_values(["avg_rel", "avg_edge"], ascending=[False, False])
        )
        lines = [
            f"{r['league']} | Picks {int(r['matches'])} | "
            f"Edge {r['avg_edge']:.3f} | EV {r['avg_ev']:.3f} | Rel {r['avg_rel']:.1f}"
            for _, r in rank.iterrows()
        ]
        textbox_set(self.league_rank_box, "\n".join(lines))
