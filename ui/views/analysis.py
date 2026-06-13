# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
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


import logging

logger = logging.getLogger(__name__)


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


class _ShapTooltip:
    """
    Muestra un tooltip con los top-5 SHAP features al hacer hover sobre
    una fila del Treeview.  Requiere que el DataFrame subyacente contenga
    una columna 'shap_top' (lista de (nombre, valor) por fila).
    Si la columna no existe, el tooltip nunca se muestra.
    """

    _LABEL_ALIASES: dict[str, str] = {
        "f_elo_diff":        "ELO advantage",
        "f_home_win_streak": "home form",
        "f_rest_days":       "fatigue",
        "f_xg_hist":         "historical xG",
        "f_away_xg_hist":    "opponent xG",
        "f_form_diff":       "recent form diff",
        "f_h2h_home_rate":   "head-to-head rate",
        "f_league_tier":     "league quality",
        "f_home_goals_avg":  "home goals avg",
        "f_away_goals_avg":  "away goals avg",
    }

    def __init__(self, tree: ttk.Treeview) -> None:
        self._tree      = tree
        self._tw: "tk.Toplevel | None" = None
        self._df: "pd.DataFrame | None" = None
        self._last_iid: str = ""
        # Use "+" to append — _ColumnTooltip already bound <Motion> on the same widget
        tree.bind("<Motion>", self._on_motion, "+")
        tree.bind("<Leave>",  self._hide, "+")

    def set_dataframe(self, df: "pd.DataFrame") -> None:
        """Registra el DataFrame actual para buscar shap_top por fila."""
        self._df = df

    def _on_motion(self, event) -> None:
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            self._hide()
            return

        iid = self._tree.identify_row(event.y)
        if not iid or iid == self._last_iid:
            return

        self._last_iid = iid
        shap_data = self._get_shap(iid)
        if shap_data is None:
            self._hide()
            return

        self._show(shap_data, event.x_root + 18, event.y_root + 14)

    def _get_shap(self, iid: str):
        """Extrae shap_top de la fila del DataFrame que corresponde al iid."""
        if self._df is None or "shap_top" not in self._df.columns:
            return None
        try:
            vals = self._tree.item(iid, "values")
            if not vals:
                return None
            # Identificamos la fila por home_team + away_team (columnas 2 y 3)
            home_idx = TREE_COLUMNS.index("home_team")
            away_idx = TREE_COLUMNS.index("away_team")
            home = str(vals[home_idx]).strip()
            away = str(vals[away_idx]).strip()
            mask = (
                self._df["home_team"].astype(str).str.strip() == home
            ) & (
                self._df["away_team"].astype(str).str.strip() == away
            )
            matched = self._df[mask]
            if matched.empty:
                return None
            shap_top = matched.iloc[0].get("shap_top")
            if shap_top is None or (isinstance(shap_top, float) and pd.isna(shap_top)):
                return None
            if not isinstance(shap_top, (list, tuple)) or len(shap_top) == 0:
                return None
            return shap_top
        except Exception:
            return None

    def _show(self, shap_data, x: int, y: int) -> None:
        self._hide()
        self._tw = tw = tk.Toplevel(self._tree)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(background=CARD)

        # Borde exterior (frame contenedor)
        outer = tk.Frame(tw, background=BORDER, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, background=CARD, padx=10, pady=8)
        inner.pack()

        tk.Label(
            inner,
            text="Factores clave (SHAP)",
            font=("Segoe UI", 10, "bold"),
            foreground=BORDER,
            background=CARD,
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            inner,
            text="━" * 26,
            font=("Courier New", 9),
            foreground=BORDER,
            background=CARD,
            anchor="w",
        ).pack(fill="x")

        for feat_name, shap_val in shap_data:
            arrow = "↑" if shap_val >= 0 else "↓"
            alias = self._LABEL_ALIASES.get(feat_name, feat_name.replace("f_", ""))
            line  = f"{arrow} {feat_name:<22s}  {shap_val:+.3f}  ({alias})"
            color = ACCENT if shap_val >= 0 else "#ef4444"
            tk.Label(
                inner,
                text=line,
                font=("Courier New", 9),
                foreground=color,
                background=CARD,
                anchor="w",
                justify="left",
            ).pack(fill="x")

    def _hide(self, *_) -> None:
        if self._tw:
            try:
                self._tw.destroy()
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)
            self._tw = None
        self._last_iid = ""


TREE_HEADERS = {
    "date": "Fecha", "league": "Liga", "home_team": "Local",
    "away_team": "Visitante", "pick": "Pick", "odds": "Cuota",
    "edge": "Edge %", "model_prob": "P(Modelo)", "fair_prob": "P(Mercado)",
    "open_fair_prob": "P(Apert.)", "close_fair_prob": "P(Cierre)",
    "clv": "CLV", "open_overround": "Overround",
    "ev": "EV %", "reliability_score": "Fiabilidad",
    "bankroll_pct": "Kelly%",
    "xg_home": "xG Casa", "xg_away": "xG Vis.",
    "analysis": "Análisis",
}

TREE_COLUMNS = [
    "date", "league", "home_team", "away_team",
    "pick", "odds", "edge", "model_prob", "fair_prob",
    "open_fair_prob", "close_fair_prob", "clv",
    "open_overround", "ev", "reliability_score",
    "bankroll_pct", "xg_home", "xg_away", "analysis",
]

TREE_WIDTHS = {
    "date": 82, "league": 75, "home_team": 140, "away_team": 140,
    "pick": 84, "odds": 58, "edge": 66, "model_prob": 74,
    "fair_prob": 74, "open_fair_prob": 76, "close_fair_prob": 76,
    "clv": 62, "open_overround": 78, "ev": 66,
    "reliability_score": 80, "bankroll_pct": 68,
    "xg_home": 62, "xg_away": 62,
    "analysis": 300,
}


def _fmt_cell(col: str, v) -> str:
    """Formatea un valor de celda para la tabla. Convierte decimales a porcentajes."""
    import pandas as pd
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return "—"
    try:
        if col == "date":
            return pd.to_datetime(v).strftime("%d/%m/%y")
        if col in ("edge", "clv"):
            return f"{float(v) * 100:+.1f}%"
        if col in ("model_prob", "fair_prob", "open_fair_prob", "close_fair_prob"):
            return f"{float(v) * 100:.1f}%"
        if col == "ev":
            return f"{float(v) * 100:+.1f}%"
        if col == "bankroll_pct":
            return f"{float(v) * 100:.2f}%"
        if col == "odds":
            return f"{float(v):.2f}"
        if col == "reliability_score":
            return f"{int(v)}/99"
        if col == "open_overround":
            return f"{float(v):.3f}"
        if col in ("xg_home", "xg_away"):
            return f"{float(v):.2f}"
    except Exception:
        logger.debug("Excepción ignorada", exc_info=True)
    return str(v) if str(v) != "nan" else "—"


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

        # Parámetros (con texto de ayuda opcional)
        for label, var, helptext in [
            ("Edge mín. 1X2 (%)",      self.app.edge1,
             "ventaja mín. del modelo sobre la cuota · 3 = 3% (típico 2–5)"),
            ("Edge mín. Over 2.5 (%)", self.app.edge2,
             "igual, para Más/Menos 2.5 goles"),
            ("Peso modelo 0-1 (blend mercado)", self.app.blend_w, None),
            ("Bankroll base (€)", self.app.unit_stake, None),
        ]:
            ctk.CTkLabel(lb, text=label, text_color=MUTED).pack(anchor="w", pady=(8, 2))
            ctk.CTkEntry(
                lb, textvariable=var,
                fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            ).pack(fill="x")
            if helptext:
                ctk.CTkLabel(
                    lb, text=helptext, text_color=MUTED,
                    font=ctk.CTkFont(size=9), wraplength=200, justify="left",
                ).pack(anchor="w", pady=(1, 0))

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

        # Search bar + status + toggle vista
        bar = ctk.CTkFrame(center, fg_color="transparent")
        bar.pack(fill="x", padx=14, pady=(0, 8))
        self.status_label = ctk.CTkLabel(bar, text="Listo", text_color=MUTED)
        self.status_label.pack(side="right")

        # Toggle tabla / tarjetas
        self._view_mode = "table"   # "table" | "cards"
        self._view_toggle = ctk.CTkButton(
            bar, text="🃏 Cards",
            command=self._toggle_view_mode,
            fg_color=CARD_2, hover_color="#0d2a14",
            border_color=BORDER, border_width=1,
            text_color=MUTED, height=28, width=80, corner_radius=8,
            font=ctk.CTkFont(size=11),
        )
        self._view_toggle.pack(side="right", padx=(0, 8))

        ctk.CTkEntry(
            bar, textvariable=self.app.search_var,
            placeholder_text="Buscar equipo, liga o pick",
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
        ).pack(side="left", fill="x", expand=True)
        self.app.search_var.trace_add("write", lambda *_: self.app._schedule_filter())

        # KPI hero row — sigue la paleta del tema (antes verde LED fijo)
        hero = ctk.CTkFrame(
            center, fg_color=BG,
            border_color=BORDER, border_width=1, corner_radius=14,
        )
        hero.pack(fill="x", padx=14, pady=(0, 8))
        hero.grid_columnconfigure((0, 1, 2, 3), weight=1)

        _HERO_ICONS = ["📋", "🎯", "📈", "🟢"]
        self.metric_labels: list[ctk.CTkLabel] = []
        for idx, (icon, title) in enumerate(zip(_HERO_ICONS, ["Partidos", "Picks", "ROI (OOS)", "Verde / Amar."])):
            box = ctk.CTkFrame(
                hero, fg_color=CARD_2,
                border_color=BORDER, border_width=1, corner_radius=10,
            )
            box.grid(row=0, column=idx, padx=6, pady=8, sticky="ew")
            # Icono + título en la misma fila
            hdr = ctk.CTkFrame(box, fg_color="transparent")
            hdr.pack(anchor="w", padx=10, pady=(8, 0))
            ctk.CTkLabel(hdr, text=icon, font=ctk.CTkFont(size=13)).pack(side="left")
            ctk.CTkLabel(
                hdr, text=f"  {title}", text_color=MUTED,
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(side="left")
            # Valor: fuente monoespaciada tipo marcador LED
            val = ctk.CTkLabel(
                box, text="—", text_color=ACCENT,
                font=ctk.CTkFont(family="Consolas", size=20, weight="bold"),
            )
            val.pack(anchor="w", padx=12, pady=(2, 8))
            self.metric_labels.append(val)

        # ── Backtest summary + diagnostics (colapsable) ───────────────────────
        summary_hdr = ctk.CTkFrame(center, fg_color="transparent")
        summary_hdr.pack(fill="x", padx=14, pady=(0, 2))

        self._summary_collapsed = True          # empieza colapsado → treeview visible
        self._summary_toggle_btn = ctk.CTkButton(
            summary_hdr,
            text="▶  Backtest & Diagnóstico",   # ▶ = colapsado
            command=self._toggle_summary,
            fg_color="transparent", hover_color=CARD_2,
            text_color=MUTED, font=ctk.CTkFont(size=11),
            anchor="w", height=22, corner_radius=6,
        )
        self._summary_toggle_btn.pack(side="left")

        self._summary_frame = ctk.CTkFrame(center, fg_color="transparent")
        # NO se empaqueta aquí — empieza oculto; _toggle_summary lo mostrará
        self.summary_box = make_textbox(self._summary_frame, height=78)
        self.summary_box.pack(fill="x")

        # ── Top picks + league ranking (colapsable) ──────────────────────────
        insight_hdr = ctk.CTkFrame(center, fg_color="transparent")
        self._insight_hdr = insight_hdr   # referencia para el toggle de summary
        insight_hdr.pack(fill="x", padx=14, pady=(0, 2))

        self._insight_collapsed = True           # empieza colapsado
        self._insight_toggle_btn = ctk.CTkButton(
            insight_hdr,
            text="▶  Top Picks & League Ranking",
            command=self._toggle_insight,
            fg_color="transparent", hover_color=CARD_2,
            text_color=MUTED, font=ctk.CTkFont(size=11),
            anchor="w", height=22, corner_radius=6,
        )
        self._insight_toggle_btn.pack(side="left")

        self._insight_row = ctk.CTkFrame(center, fg_color="transparent")
        # NO se empaqueta aquí — empieza oculto
        self._insight_row.grid_columnconfigure((0, 1), weight=1)
        insight_row = self._insight_row

        tp = make_card(insight_row, "Top Picks", "Las mejores selecciones del análisis actual")
        tp.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._picks_scroll = ctk.CTkScrollableFrame(
            tp, fg_color="transparent", height=100,
        )
        self._picks_scroll.pack(fill="x", padx=10, pady=(0, 10))
        self._picks_scroll.grid_columnconfigure(0, weight=1)

        lr = make_card(insight_row, "League Ranking", "Rendimiento por liga")
        lr.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.league_rank_box = make_textbox(lr, height=100)
        self.league_rank_box.pack(fill="x", padx=12, pady=(0, 12))

        # ── Panel de análisis IA (abajo) ──────────────────────────────────────
        detail_bar = ctk.CTkFrame(
            center, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        detail_bar.pack(side="bottom", fill="x", padx=14, pady=(4, 14))
        _db_header = ctk.CTkFrame(detail_bar, fg_color="transparent")
        _db_header.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(
            _db_header, text="🧠  Análisis Claude IA",
            text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        self._sanity_btn = ctk.CTkButton(
            _db_header, text="🔍 Sanity Check",
            command=self._run_sanity_check,
            fg_color=CARD_2, hover_color="#0d1f10",
            border_color=BORDER, border_width=1,
            text_color=TEXT, height=26, corner_radius=8,
            font=ctk.CTkFont(size=10),
        )
        ctk.CTkButton(
            _db_header, text="💬 Chat IA",
            command=self._open_chat_with_context,
            fg_color="#1e1b4b", hover_color="#312e81",
            border_color="#818cf8", border_width=1,
            text_color="#c4b5fd",
            height=26, corner_radius=8,
            font=ctk.CTkFont(size=10),
        ).pack(side="right", padx=(0, 6))
        self._sanity_btn.pack(side="right")
        # ── Betfair Exchange ──────────────────────────────────────────────────
        self._betfair_btn = ctk.CTkButton(
            _db_header, text="🟢 Betfair",
            command=self._open_betfair_dialog,
            fg_color="#064e3b", hover_color="#065f46",
            border_color="#059669", border_width=1,
            text_color="#6ee7b7",
            height=26, corner_radius=8,
            font=ctk.CTkFont(size=10),
        )
        self._betfair_btn.pack(side="right", padx=(0, 4))
        self._detail_box = make_textbox(detail_bar, height=60)
        self._detail_box.pack(fill="x", padx=12, pady=(0, 8))
        textbox_set(self._detail_box, "Selecciona un partido para ver el análisis IA.")

        # ── Contenedor compartido tabla + tarjetas ────────────────────────────
        shell = ctk.CTkFrame(center, fg_color="#060f07")
        self._tree_shell = shell
        shell.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        # ── Vista TABLA (treeview) ─────────────────────────────────────────────
        self._table_frame = ctk.CTkFrame(shell, fg_color="transparent")
        self._table_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self._table_frame.grid_rowconfigure(0, weight=1)
        self._table_frame.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self._table_frame, columns=TREE_COLUMNS, show="headings")
        for col in TREE_COLUMNS:
            self.tree.heading(col, text=TREE_HEADERS.get(col, col.upper()))
            self.tree.column(col, width=TREE_WIDTHS.get(col, 100), anchor="center")

        self.tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(
            self._table_frame, orient="vertical", command=self.tree.yview
        ).grid(row=0, column=1, sticky="ns")

        self.tree.tag_configure("green",  background="#0e2d1d", foreground="#d6ffe6")
        self.tree.tag_configure("yellow", background="#3a2c0e", foreground="#fff0c2")
        self.tree.tag_configure("red",    background="#341313", foreground="#ffd3d3")
        self.tree.tag_configure("grey",   background="#050e1c", foreground="#8fa3bf")
        self.tree.tag_configure("claude", background="#16103a", foreground="#c4b5fd")

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self._col_tooltip  = _ColumnTooltip(self.tree)
        self._shap_tooltip = _ShapTooltip(self.tree)

        # ── Vista TARJETAS (match cards) ───────────────────────────────────────
        self._cards_outer = ctk.CTkScrollableFrame(
            shell, fg_color="#020d04",
            scrollbar_button_color="#0e4d6c",
            scrollbar_button_hover_color=ACCENT,
        )
        # empieza oculta — se muestra con _toggle_view_mode
        self._selected_card_key: str | None = None
        self._card_widgets: dict[str, ctk.CTkFrame] = {}
        self._card_rows: dict[str, pd.Series] = {}

        # ── Drift banner (oculto por defecto) ─────────────────────────────────
        self._drift_banner = tk.Label(
            center,
            text="",
            background="#7c3a00",
            foreground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=14,
            pady=6,
        )
        # No se empaqueta aquí — se muestra/oculta dinámicamente en show_drift_banner()

    # ── Collapse toggles ──────────────────────────────────────────────────────

    def _toggle_summary(self) -> None:
        self._summary_collapsed = not self._summary_collapsed
        if self._summary_collapsed:
            self._summary_frame.pack_forget()
            self._summary_toggle_btn.configure(text="▶  Backtest & Diagnóstico")
        else:
            # Re-insertar justo antes del bloque de insight_hdr (siempre visible)
            self._summary_frame.pack(
                fill="x", padx=14, pady=(0, 6),
                before=self._insight_hdr,
            )
            self._summary_toggle_btn.configure(text="▼  Backtest & Diagnóstico")

    def _toggle_insight(self) -> None:
        self._insight_collapsed = not self._insight_collapsed
        if self._insight_collapsed:
            self._insight_row.pack_forget()
            self._insight_toggle_btn.configure(text="▶  Top Picks & League Ranking")
        else:
            # Re-insertar justo antes del treeview (siempre visible)
            self._insight_row.pack(
                fill="x", padx=14, pady=(0, 6),
                before=self._tree_shell,
            )
            self._insight_toggle_btn.configure(text="▼  Top Picks & League Ranking")

    # ── Toggle tabla / tarjetas ────────────────────────────────────────────────

    def _toggle_view_mode(self) -> None:
        if self._view_mode == "table":
            self._view_mode = "cards"
            self._table_frame.grid_remove()
            self._cards_outer.grid(row=0, column=0, columnspan=2, sticky="nsew")
            self._view_toggle.configure(text="📊 Tabla", text_color=TEXT)
            # Construir tarjetas en este momento (lazy) — evita crear miles de
            # widgets CTk cuando la vista estaba oculta tras el análisis
            try:
                df = getattr(self.app, "filtered", pd.DataFrame())
                if df.empty:
                    df = getattr(self.app, "results", pd.DataFrame())
                if not df.empty:
                    self.fill_cards(df)
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)
        else:
            self._view_mode = "table"
            self._cards_outer.grid_remove()
            self._table_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
            self._view_toggle.configure(text="🃏 Cards", text_color=MUTED)

    # ── Match cards ────────────────────────────────────────────────────────────

    # Colores por liga (Premier League morado, La Liga naranja, etc.)
    _LEAGUE_COLORS: dict[str, str] = {
        "Premier League": "#7c3aed",
        "Championship":   "#2563eb",
        "La Liga":        "#f59e0b",
        "Segunda":        "#22c55e",
        "Serie A":        "#0891b2",
        "Bundesliga":     "#dc2626",
        "Ligue 1":        "#38bdf8",
        "Primeira Liga":  "#10b981",
        "Eredivisie":     "#f97316",
    }
    _RISK_COLORS: dict[str, tuple[str, str]] = {
        "VERDE":    ("#052e0f", "#22c55e"),   # (bg, fg)
        "AMARILLO": ("#2d1f02", "#fbbf24"),
        "ROJO":     ("#2a0a0a", "#ef4444"),
    }

    def fill_cards(self, df: pd.DataFrame) -> None:
        """Crea una tarjeta por partido, POR LOTES, para no congelar la UI:
        construye ~15 tarjetas y cede el control al event loop antes de seguir."""
        # Cancelar un render por lotes que pudiera estar en curso
        if getattr(self, "_cards_after_id", None):
            try:
                self.after_cancel(self._cards_after_id)
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)
            self._cards_after_id = None

        # Limpiar tarjetas anteriores
        for w in self._cards_outer.winfo_children():
            w.destroy()
        self._card_widgets.clear()
        self._card_rows.clear()
        self._selected_card_key = None

        if df.empty:
            ctk.CTkLabel(
                self._cards_outer,
                text="Sin resultados — pulsa ▶ Run Analysis",
                text_color=MUTED, font=ctk.CTkFont(size=13),
            ).pack(pady=40)
            return

        sorted_df = df.sort_values(
            ["reliability_score", "ev", "edge"],
            ascending=[False, False, False], na_position="last",
        )
        rows = list(sorted_df.iterrows())

        def _build_batch(start: int, batch: int = 15) -> None:
            try:
                if not self._cards_outer.winfo_exists():
                    return
            except Exception:
                return
            for idx in range(start, min(start + batch, len(rows))):
                _, row = rows[idx]
                key = f"{row.get('home_team', '')}::{row.get('away_team', '')}"
                card = self._make_match_card(self._cards_outer, row, key)
                card.pack(fill="x", padx=8, pady=(0, 6) if idx > 0 else (6, 6))
                self._card_widgets[key] = card
                self._card_rows[key]    = row
            # Seleccionar la primera tarjeta en cuanto está el primer lote
            if start == 0 and self._card_widgets:
                self._on_card_click(next(iter(self._card_widgets)))
            nxt = start + batch
            if nxt < len(rows):
                self._cards_after_id = self.after(1, lambda: _build_batch(nxt, batch))
            else:
                self._cards_after_id = None

        _build_batch(0)

    def _make_match_card(self, parent, row: pd.Series, key: str) -> ctk.CTkFrame:
        """Construye una tarjeta visual de partido."""
        home  = str(row.get("home_team", "?"))
        away  = str(row.get("away_team", "?"))
        league = str(row.get("league", row.get("div", "")))
        pick  = str(row.get("pick", "—"))
        risk  = str(row.get("risk_light", ""))
        date_s = str(row.get("date", ""))[:10]
        time_s = str(row.get("time", ""))[:5]

        try: odds = f"@{float(row.get('odds', 0)):.2f}"
        except Exception: odds = ""
        try:
            e = float(row.get("edge_1x2", None) or row.get("edge", 0) or 0)
            edge_s = f"+{e*100:.1f}%" if e > 0 else f"{e*100:.1f}%"
        except Exception: edge_s = ""
        try: kelly = f"{float(row.get('bankroll_pct', 0)):.1f}%"
        except Exception: kelly = ""
        try:
            p_h = float(row.get("p_home", 0) or 0)
            p_d = float(row.get("p_draw", 0) or 0)
            p_a = float(row.get("p_away", 0) or 0)
        except Exception: p_h = p_d = p_a = 0.0
        try: rel = int(float(row.get("reliability_score", 0) or 0))
        except Exception: rel = 0

        risk_bg, risk_fg = self._RISK_COLORS.get(risk, ("#1a1a1a", "#888888"))
        league_col = self._LEAGUE_COLORS.get(league, BORDER)

        # ── Outer card ─────────────────────────────────────────────────────────
        card = ctk.CTkFrame(
            parent, fg_color=CARD,
            border_color=league_col, border_width=2, corner_radius=12,
            cursor="hand2",
        )
        card.grid_columnconfigure(1, weight=1)

        # Barra de color de liga (izquierda)
        bar_stripe = ctk.CTkFrame(
            card, fg_color=league_col, width=5, corner_radius=0,
        )
        bar_stripe.grid(row=0, column=0, rowspan=4, sticky="nsw",
                        padx=(0, 10), pady=0)

        # ── Fila 1: equipos ────────────────────────────────────────────────────
        teams_row = ctk.CTkFrame(card, fg_color="transparent")
        teams_row.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(10, 2))
        teams_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            teams_row, text=home,
            text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            teams_row, text="vs",
            text_color=MUTED, font=ctk.CTkFont(size=11),
            anchor="center",
        ).grid(row=0, column=1, padx=8)

        ctk.CTkLabel(
            teams_row, text=away,
            text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"),
            anchor="e",
        ).grid(row=0, column=2, sticky="e")

        # ── Fila 2: liga + fecha + hora ────────────────────────────────────────
        meta_parts = [lg for lg in [league, date_s, time_s] if lg and lg not in ("", "nan")]
        ctk.CTkLabel(
            card, text="  ·  ".join(meta_parts),
            text_color=MUTED, font=ctk.CTkFont(size=10),
            anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(0, 4))

        # ── Fila 3: pick + odds + edge + kelly ────────────────────────────────
        pick_row = ctk.CTkFrame(card, fg_color="transparent")
        pick_row.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=(0, 6))

        # Badge del pick
        ctk.CTkFrame(
            pick_row, fg_color=risk_bg,
            border_color=risk_fg, border_width=1, corner_radius=6, width=36, height=26,
        ).pack(side="left")
        ctk.CTkLabel(
            pick_row, text=f" {pick} ",
            fg_color=risk_bg, text_color=risk_fg,
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=6,
        ).pack(side="left")

        for txt, col in [
            (odds,   TEXT),
            (edge_s, "#22c55e" if e > 0 else "#ef4444" if "e" in dir() else MUTED),
            (f"Kelly {kelly}" if kelly else "", MUTED),
        ]:
            if txt:
                ctk.CTkLabel(
                    pick_row, text=f"  {txt}",
                    text_color=col, font=ctk.CTkFont(size=11),
                ).pack(side="left")

        # ── Fila 4: barras de probabilidad ────────────────────────────────────
        prob_row = ctk.CTkFrame(card, fg_color="transparent")
        prob_row.grid(row=3, column=1, sticky="ew", padx=(0, 10), pady=(0, 8))
        prob_row.grid_columnconfigure((0, 1, 2), weight=1)

        for col_p, label_p, prob_p, color_p in [
            (0, "Local", p_h, "#22c55e"),
            (1, "Empate", p_d, "#fbbf24"),
            (2, "Visitante", p_a, "#ef4444"),
        ]:
            pf = ctk.CTkFrame(prob_row, fg_color="transparent")
            pf.grid(row=0, column=col_p, padx=(0 if col_p == 0 else 4, 0), sticky="ew")
            pf.grid_columnconfigure(0, weight=1)

            # Barra de probabilidad
            bar_bg = ctk.CTkFrame(pf, fg_color="#0a1a0a", height=6, corner_radius=3)
            bar_bg.pack(fill="x")
            bar_bg.grid_columnconfigure(0, weight=1)
            if prob_p > 0:
                bar_fill = ctk.CTkFrame(
                    bar_bg, fg_color=color_p, height=6, corner_radius=3,
                )
                bar_fill.place(relx=0, rely=0, relwidth=min(1.0, prob_p), relheight=1.0)

            ctk.CTkLabel(
                pf, text=f"{label_p} {prob_p*100:.0f}%",
                text_color=MUTED, font=ctk.CTkFont(size=9),
                anchor="center",
            ).pack(fill="x")

        # ── Badge riesgo + reliability (esquina derecha) ───────────────────────
        badge_col = ctk.CTkFrame(card, fg_color="transparent")
        badge_col.grid(row=0, column=2, rowspan=4, sticky="nse", padx=(0, 12), pady=10)

        ctk.CTkLabel(
            badge_col,
            text={"VERDE": "🟢 VERDE", "AMARILLO": "🟡 AMARILLO", "ROJO": "🔴 ROJO"}.get(risk, risk),
            text_color=risk_fg,
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="e")
        ctk.CTkLabel(
            badge_col, text=f"⭐ {rel}",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(anchor="e", pady=(4, 0))

        # Bind clic en toda la tarjeta
        for w in [card, teams_row, pick_row, prob_row, badge_col]:
            w.bind("<Button-1>", lambda _, k=key: self._on_card_click(k))

        return card

    def _on_card_click(self, key: str) -> None:
        """Selecciona una tarjeta y muestra su análisis IA."""
        # Deseleccionar anterior
        if self._selected_card_key and self._selected_card_key in self._card_widgets:
            prev = self._card_widgets[self._selected_card_key]
            row_prev = self._card_rows.get(self._selected_card_key)
            if row_prev is not None:
                league_col = self._LEAGUE_COLORS.get(
                    str(row_prev.get("league", row_prev.get("div", ""))), BORDER)
                prev.configure(border_color=league_col, border_width=2)

        # Seleccionar nueva
        self._selected_card_key = key
        if key in self._card_widgets:
            self._card_widgets[key].configure(
                border_color=TEXT, border_width=3)

        # Actualizar panel IA
        row = self._card_rows.get(key)
        if row is not None:
            analysis_text = str(row.get("analysis", "")) or \
                            "Selecciona un partido para ver el análisis IA."
            textbox_set(self._detail_box, analysis_text)

    # ── Refresh methods ────────────────────────────────────────────────────────

    def update_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def update_metrics(
        self,
        total: int,
        picks: int,
        avg_roi: float,
        verde_count: int,
        amar_count: int = 0,
    ) -> None:
        self.metric_labels[0].configure(text=str(total))
        self.metric_labels[1].configure(text=str(picks))
        roi_color = ACCENT if avg_roi >= 0 else "#ef4444"
        self.metric_labels[2].configure(text=f"{avg_roi:+.1%}", text_color=roi_color)
        split_txt = f"{verde_count} / {amar_count}"
        self.metric_labels[3].configure(text=split_txt)

    def fill_summary(
        self,
        backtest_summary: dict,
        diagnostics: list[str],
    ) -> None:
        # ── Determinar si todos los backtests son puros ──────────────────────
        all_pure = all(d.get("pure_wf", False) for d in backtest_summary.values())
        bt_label = "BACKTEST WALK-FORWARD PURO ✓" if all_pure else "BACKTEST OOS (pseudo)"
        bt_note  = (
            "Re-entrena por ventana — sin look-ahead bias"
            if all_pure
            else "⚠ Mismo modelo para todas las ventanas — ROI puede estar inflado"
        )

        lines = [f"=== {bt_label} ===", bt_note, ""]

        for div, data in backtest_summary.items():
            pure_tag = " [PURO]" if data.get("pure_wf") else " [pseudo-OOS]"
            roi_str  = f"{data['roi']:+.2%}"
            std_str  = f"σ={data.get('roi_std', 0):.2%}"
            lines.append(
                f"{div}{pure_tag}: {data['bets']} apuestas | ROI {roi_str} | "
                f"hit {data['hit']:.1%} | {std_str}"
            )
            lines.append(
                f"  1X2 ROI {data['market_1x2_roi']:+.2%} | "
                f"O2.5 ROI {data['market_o25_roi']:+.2%} | "
                f"eval_n {data.get('eval_samples', '?')}"
            )

            # Mini gráfico ASCII de ROI por ventana
            rois = data.get("roi_per_window", [])
            if rois:
                bars = []
                for r in rois:
                    if r > 0.10:    bar = "▓▓▓"
                    elif r > 0.04:  bar = "▓▓ "
                    elif r > 0.0:   bar = "▓  "
                    elif r == 0.0:  bar = "·  "
                    elif r > -0.04: bar = "░  "
                    else:           bar = "░░░"
                    bars.append(f"W{rois.index(r)+1}:{bar}{r:+.1%}")
                lines.append("  " + "  │  ".join(bars))
            lines.append("")

        lines += [
            "=== FILTROS ACTIVOS ===",
            "Overround 1X2 ≤ 1.08 | Over/Under ≤ 1.10 | CLV ≥ -1% | Kelly 0.20 cap 1.5%",
            "",
            "=== DIAGNÓSTICO MODELO ===",
        ] + diagnostics
        textbox_set(self.summary_box, "\n".join(lines))

    def fill_tree(self, df: pd.DataFrame) -> None:
        self._iid_map = {}
        for row in self.tree.get_children():
            self.tree.delete(row)

        # Registrar el DataFrame en el tooltip SHAP para búsquedas por fila
        self._shap_tooltip.set_dataframe(df)

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
                # Mapear columnas xG desde sus nombres reales en el DataFrame
                if col == "xg_home":
                    raw = row.get("xg_real_home", "")
                elif col == "xg_away":
                    raw = row.get("xg_real_away", "")
                else:
                    raw = row.get(col, "")
                vals.append(_fmt_cell(col, raw))
            iid = self.tree.insert("", "end", values=vals, tags=(tag,))
            key = f"{row.get('home_team', '')}::{row.get('away_team', '')}"
            self._iid_map[key] = iid

        # Auto-scroll: seleccionar y mostrar la primera fila
        first = self.tree.get_children()
        if first:
            self.tree.selection_set(first[0])
            self.tree.see(first[0])
            self.tree.focus(first[0])

    def fill_top_picks(self, df: pd.DataFrame) -> None:
        # Limpiar tarjetas anteriores
        for w in self._picks_scroll.winfo_children():
            w.destroy()

        verde_amarillo = df[
            df["risk_light"].isin(["VERDE", "AMARILLO"])
            & (df.get("pick", pd.Series(dtype=str)) != "NO BET")
        ] if "risk_light" in df.columns else pd.DataFrame()

        if verde_amarillo.empty:
            ctk.CTkLabel(
                self._picks_scroll,
                text="No hay picks VERDE/AMARILLO — prueba a bajar el umbral de edge.",
                text_color=MUTED, font=ctk.CTkFont(size=11),
            ).grid(row=0, column=0, sticky="w", pady=8)
            return

        sort_cols = [c for c in ["reliability_score", "edge", "ev"] if c in verde_amarillo.columns]
        top5 = verde_amarillo.sort_values(sort_cols, ascending=False).head(5)

        for row_idx, (_, r) in enumerate(top5.iterrows()):
            self._make_pick_card(row_idx, r)

    def _make_pick_card(self, idx: int, r: pd.Series) -> None:
        signal      = r.get("risk_light", "ROJO")
        sig_color   = "#22c55e" if signal == "VERDE" else "#eab308"
        bg_color    = "#07140b" if idx % 2 == 0 else "#060f07"

        card = ctk.CTkFrame(
            self._picks_scroll,
            fg_color=bg_color, corner_radius=8,
            border_color=sig_color, border_width=1,
        )
        card.grid(row=idx, column=0, sticky="ew", pady=(0, 3))
        card.grid_columnconfigure(1, weight=1)

        # Señal badge
        ctk.CTkLabel(
            card, text=signal[:4],
            text_color=sig_color,
            font=ctk.CTkFont(size=9, weight="bold"),
            width=38,
        ).grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6, sticky="w")

        # Partido + pick + cuota
        home = r.get("home_team", "")
        away = r.get("away_team", "")
        pick = r.get("pick", "—")
        odds = r.get("odds")
        odds_str = f" @ {float(odds):.2f}" if odds is not None and pd.notna(odds) else ""
        ctk.CTkLabel(
            card,
            text=f"{home} vs {away}  [{pick}]{odds_str}",
            text_color=TEXT,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(5, 1))

        # Stats
        edge  = r.get("edge")
        ev    = r.get("ev")
        rel   = r.get("reliability_score")
        xg_h  = r.get("xg_real_home")
        xg_a  = r.get("xg_real_away")
        parts = []
        if edge  is not None and pd.notna(edge):  parts.append(f"Edge {float(edge)*100:+.1f}%")
        if ev    is not None and pd.notna(ev):    parts.append(f"EV {float(ev)*100:+.1f}%")
        if rel   is not None and pd.notna(rel):   parts.append(f"Rel {int(rel)}/99")
        if xg_h  is not None and pd.notna(xg_h) and xg_a is not None and pd.notna(xg_a):
            parts.append(f"xG {float(xg_h):.1f}–{float(xg_a):.1f}")
        ctk.CTkLabel(
            card,
            text="  ·  ".join(parts) if parts else "",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 5))

    def update_pick_analysis(self, match_key: str, text: str) -> None:
        """Actualiza la columna Análisis cuando Claude responde (tabla + tarjeta activa)."""
        iid = self._iid_map.get(match_key)
        if iid:
            try:
                vals = list(self.tree.item(iid, "values"))
                ai_idx = TREE_COLUMNS.index("analysis")
                vals[ai_idx] = text
                self.tree.item(iid, values=vals)
                if iid in self.tree.selection():
                    textbox_set(self._detail_box, text)
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)
        # Actualizar en tarjeta si está seleccionada
        if match_key in self._card_rows:
            try:
                self._card_rows[match_key] = self._card_rows[match_key].copy()
                self._card_rows[match_key]["analysis"] = text
                if self._selected_card_key == match_key:
                    textbox_set(self._detail_box, text)
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)

    def update_grey_pick(self, match_key: str, analysis_text: str, pick: str) -> None:
        """Actualiza pick + análisis de una fila gris con la recomendación del tipster IA."""
        iid = self._iid_map.get(match_key)
        if not iid:
            return
        try:
            vals     = list(self.tree.item(iid, "values"))
            pick_idx = TREE_COLUMNS.index("pick")
            ai_idx   = TREE_COLUMNS.index("analysis")
            vals[pick_idx] = f"🧠 {pick}"
            vals[ai_idx]   = analysis_text
            self.tree.item(iid, values=vals, tags=("claude",))
            if iid in self.tree.selection():
                textbox_set(self._detail_box, analysis_text)
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

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
            logger.debug("Excepción ignorada", exc_info=True)

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

    def show_drift_banner(self, drift_info: "dict | None") -> None:
        """
        Muestra u oculta el banner de drift según el resultado de detect_model_drift.
        Llama este método desde app.py tras cargar los resultados del análisis.
        """
        if drift_info and drift_info.get("drift_detected"):
            msg = drift_info.get(
                "message",
                f"⚠️  Model drift detectado: ROI esperado "
                f"{drift_info.get('expected_roi', 0):+.1%} vs "
                f"EV actual {drift_info.get('current_ev', 0):+.1%}",
            )
            self._drift_banner.configure(text=msg)
            # Empaquetar encima del panel de análisis IA (side=bottom, before detail_bar)
            self._drift_banner.pack(fill="x", padx=14, pady=(0, 2))
        else:
            # Ocultar el banner si no hay drift
            try:
                self._drift_banner.pack_forget()
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)

    def _run_sanity_check(self) -> None:
        """Lanza el sanity check de picks VERDE con Claude IA."""
        import threading as _threading
        api_key = self.app.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            from tkinter import messagebox
            messagebox.showwarning(
                "Sanity Check",
                "Configura la API key de Anthropic en ⚙️ Strategy para usar esta función."
            )
            return

        if not hasattr(self.app, "results") or self.app.results.empty:
            from tkinter import messagebox
            messagebox.showinfo("Sanity Check", "Ejecuta primero un análisis (Run Analysis).")
            return

        # Filtrar picks VERDE
        df = self.app.results
        verde_mask = df["risk_light"] == "VERDE" if "risk_light" in df.columns else df.index < 0
        verde_picks = df[verde_mask].to_dict("records") if verde_mask.any() else []

        if not verde_picks:
            from tkinter import messagebox
            messagebox.showinfo("Sanity Check", "No hay picks VERDE en el análisis actual.")
            return

        self._sanity_btn.configure(state="disabled", text="⏳ Analizando...")

        _threading.Thread(
            target=self._sanity_worker,
            args=(verde_picks, api_key),
            daemon=True,
        ).start()

    def _sanity_worker(self, picks: list, api_key: str) -> None:
        from ...core.ai_analysis import sanity_check_picks
        results = sanity_check_picks(picks, api_key)
        self.app.after(0, lambda r=results: self._show_sanity_results(r))

    def _show_sanity_results(self, results: list) -> None:
        import tkinter as tk
        import customtkinter as ctk

        self._sanity_btn.configure(state="normal", text="🔍 Sanity Check")
        self.app._update_claude_counter()

        if not results:
            from tkinter import messagebox
            messagebox.showinfo("Sanity Check", "No se obtuvieron resultados. Comprueba la API key.")
            return

        # Ventana de resultados
        win = ctk.CTkToplevel(self.app)
        win.title("🔍 Sanity Check — Revisión de picks")
        win.geometry("720x520")
        win.configure(fg_color="#050e1c")
        win.grab_set()

        ctk.CTkLabel(
            win, text="🔍 Sanity Check · Revisión de picks VERDE",
            text_color=ACCENT, font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            win, text="Claude revisó tus picks como abogado del diablo. Verifica antes de apostar.",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=20, pady=(0, 12))

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        severity_colors = {
            "alta":  "#ef4444",
            "media": "#f59e0b",
            "baja":  "#22c55e",
            "ok":    "#98d4aa",
        }
        severity_icons = {
            "alta":  "🔴",
            "media": "🟡",
            "baja":  "🟢",
            "ok":    "✅",
        }

        has_flags = False
        for item in results:
            flag     = item.get("flag", False)
            severity = item.get("severity", "ok")
            match    = item.get("match", "?")
            pick     = item.get("pick", "?")
            concern  = item.get("concern", "Sin alertas")

            color = severity_colors.get(severity, "#98d4aa")
            icon  = severity_icons.get(severity, "✅")

            if flag:
                has_flags = True

            card = ctk.CTkFrame(
                scroll,
                fg_color="#0a1f0e" if flag else "#060f08",
                corner_radius=10,
                border_color=color if flag else BORDER,
                border_width=2 if flag else 1,
            )
            card.pack(fill="x", pady=(0, 8))

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=12, pady=(10, 2))

            ctk.CTkLabel(
                top_row,
                text=f"{icon} {match}",
                text_color=color if flag else TEXT,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(side="left")

            ctk.CTkLabel(
                top_row,
                text=f"Pick: {pick}",
                text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(side="right")

            ctk.CTkLabel(
                card,
                text=concern,
                text_color=color if flag else MUTED,
                font=ctk.CTkFont(size=11),
                wraplength=640,
                justify="left",
            ).pack(anchor="w", padx=12, pady=(0, 10))

        if not has_flags:
            ctk.CTkLabel(
                scroll,
                text="✅ Ninguna alerta grave detectada. Los picks parecen sólidos.",
                text_color=ACCENT, font=ctk.CTkFont(size=13, weight="bold"),
            ).pack(pady=20)

        ctk.CTkButton(
            win, text="Cerrar",
            command=win.destroy,
            fg_color=ACCENT_2, hover_color=ACCENT,
            height=36, corner_radius=10,
        ).pack(pady=(0, 16))

    def _open_chat_with_context(self) -> None:
        """Abre el Chat IA con contexto del análisis actual."""
        if not hasattr(self.app, "results") or self.app.results.empty:
            from tkinter import messagebox
            messagebox.showinfo(
                "Chat IA",
                "Ejecuta primero un análisis (Run Analysis) para tener picks disponibles."
            )
            return
        df = self.app.results
        n_verde = int((df.get("risk_light", "") == "VERDE").sum()) if "risk_light" in df.columns else 0
        self.app.show_chat_view(
            source_view="analysis",
            prefill=f"Analiza mis {n_verde} picks VERDE de hoy. ¿Cuáles tienen más valor real y cuál apostarías primero?",
        )

    def _open_betfair_dialog(self) -> None:
        """
        Abre el diálogo de confirmación para colocar una apuesta en Betfair Exchange.
        Requiere que haya una tarjeta o fila seleccionada.
        """
        from tkinter import messagebox

        # ── Obtener fila del pick seleccionado ────────────────────────────────
        row_data: dict | None = None
        if self._selected_card_key and self._selected_card_key in self._card_rows:
            row_data = self._card_rows[self._selected_card_key]
        else:
            # Intentar desde la tabla
            sel = self.tree.selection() if hasattr(self, "tree") else []
            if sel:
                vals = self.tree.item(sel[0], "values")
                if vals:
                    row_data = {}
                    for col, val in zip(TREE_COLUMNS, vals):
                        row_data[col] = val

        if not row_data:
            messagebox.showinfo(
                "Betfair Exchange",
                "Selecciona primero un pick (tarjeta o fila de la tabla)."
            )
            return

        home  = str(row_data.get("home_team", ""))
        away  = str(row_data.get("away_team", ""))
        pick  = str(row_data.get("pick", "")).lstrip("🧠 ").strip()
        odds  = float(row_data.get("odds", 0) or 0)
        edge  = float(row_data.get("edge", 0) or 0)

        if not home or not away or not pick:
            messagebox.showwarning(
                "Betfair Exchange", "Pick incompleto — home/away/pick vacíos."
            )
            return

        # ── Verificar credenciales ────────────────────────────────────────────
        app_key  = self.app.storage.get_setting("betfair_app_key", "")
        username = self.app.storage.get_setting("betfair_username", "")
        password = self.app.storage.get_setting("betfair_password", "")
        if not app_key or not username or not password:
            messagebox.showwarning(
                "Betfair Exchange",
                "Configura tus credenciales de Betfair en ⚙️ Strategy → Betfair Exchange."
            )
            self.app.show_settings_view()
            return

        # ── Abrir diálogo de confirmación ─────────────────────────────────────
        _BetfairConfirmDialog(
            parent  = self.winfo_toplevel(),
            app     = self.app,
            home    = home,
            away    = away,
            pick    = pick,
            odds    = odds,
            edge    = edge,
            app_key = app_key,
            username= username,
            password= password,
        )


# ── Betfair Exchange Confirmation Dialog ──────────────────────────────────────

class _BetfairConfirmDialog(ctk.CTkToplevel):
    """
    Diálogo modal de confirmación antes de colocar una apuesta real en Betfair.

    ⚠️  El usuario debe leer el resumen y hacer clic en CONFIRMAR.
    Nunca se ejecuta automáticamente.
    """

    def __init__(
        self, parent, app,
        home: str, away: str, pick: str,
        odds: float, edge: float,
        app_key: str, username: str, password: str,
    ) -> None:
        super().__init__(parent)
        self.app      = app
        self.home     = home
        self.away     = away
        self.pick     = pick
        self.odds     = odds
        self.edge     = edge
        self.app_key  = app_key
        self.username = username
        self.password = password

        self._client       = None   # BetfairClient — se crea al confirmar
        self._market_id    = tk.StringVar(value="")
        self._selection_id = tk.IntVar(value=0)
        self._live_price   = tk.StringVar(value="Buscando…")
        self._status_text  = tk.StringVar(value="")

        self.title("🟢  Betfair Exchange — Confirmar apuesta")
        self.geometry("520x560")
        self.resizable(False, False)
        self.configure(fg_color="#060f1e")
        self.grab_set()  # modal

        self._build()
        self._lookup_market()

    # ── Construcción de la UI ─────────────────────────────────────────────────

    def _build(self) -> None:
        # Título
        ctk.CTkLabel(
            self, text="⚠️  APUESTA CON DINERO REAL",
            text_color="#f87171", font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(16, 4))

        ctk.CTkLabel(
            self,
            text="Revisa los datos. Esta acción NO se puede deshacer.",
            text_color="#94a3b8", font=ctk.CTkFont(size=11),
        ).pack(pady=(0, 10))

        # Resumen del pick
        summary = ctk.CTkFrame(self, fg_color="#0a1624", corner_radius=10,
                                border_color="#1e3a5f", border_width=1)
        summary.pack(fill="x", padx=20, pady=(0, 8))

        def _row(label: str, value: str, color: str = "#e2e8f0") -> None:
            row = ctk.CTkFrame(summary, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text=label, text_color="#64748b",
                         font=ctk.CTkFont(size=11), width=130, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=value, text_color=color,
                         font=ctk.CTkFont(size=11, weight="bold"), anchor="w").pack(side="left")

        ctk.CTkFrame(summary, fg_color="#1e3a5f", height=1).pack(fill="x", pady=(10, 2))
        _row("Partido",  f"{self.home}  vs  {self.away}", "#7dd3fc")
        _row("Pick",     self.pick, "#4ade80")
        _row("Edge",     f"{self.edge:.1%}", "#facc15")
        ctk.CTkFrame(summary, fg_color="#1e3a5f", height=1).pack(fill="x", pady=(2, 0))

        # Precio en vivo
        price_row = ctk.CTkFrame(summary, fg_color="transparent")
        price_row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(price_row, text="Cuota en Betfair",
                     text_color="#64748b", font=ctk.CTkFont(size=11),
                     width=130, anchor="w").pack(side="left")
        ctk.CTkLabel(price_row, textvariable=self._live_price,
                     text_color="#34d399", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        ctk.CTkFrame(summary, fg_color="#1e3a5f", height=1).pack(fill="x", pady=(0, 8))

        # Stake
        stake_row = ctk.CTkFrame(self, fg_color="transparent")
        stake_row.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(stake_row, text="Importe (€)", text_color="#94a3b8",
                     font=ctk.CTkFont(size=11), width=100, anchor="w").pack(side="left")
        unit = float(self.app.storage.get_setting("unit_stake", "10") or 10)
        self._stake_var = tk.StringVar(value=str(round(unit, 2)))
        self._stake_entry = ctk.CTkEntry(
            stake_row, textvariable=self._stake_var,
            fg_color="#0a1624", border_color="#1e3a5f", text_color="#e2e8f0",
            width=100,
        )
        self._stake_entry.pack(side="left", padx=(8, 0))
        self._potential_lbl = ctk.CTkLabel(
            stake_row, text="", text_color="#94a3b8", font=ctk.CTkFont(size=10)
        )
        self._potential_lbl.pack(side="left", padx=(12, 0))
        self._stake_var.trace_add("write", self._update_potential)

        # Status
        self._status_lbl = ctk.CTkLabel(
            self, textvariable=self._status_text,
            text_color="#facc15", font=ctk.CTkFont(size=11), wraplength=460,
        )
        self._status_lbl.pack(pady=(4, 0))

        # Botones
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(12, 8))

        ctk.CTkButton(
            btn_row, text="✖  Cancelar",
            command=self.destroy,
            fg_color="#1e2535", hover_color="#2d3748",
            text_color="#94a3b8", height=38, width=170, corner_radius=8,
        ).pack(side="left", padx=6)

        self._confirm_btn = ctk.CTkButton(
            btn_row, text="✅  CONFIRMAR — Colocar apuesta",
            command=self._confirm,
            fg_color="#065f46", hover_color="#059669",
            text_color="#6ee7b7", height=38, width=270, corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",  # se habilita cuando se encuentra el mercado
        )
        self._confirm_btn.pack(side="left", padx=6)

        ctk.CTkLabel(
            self,
            text=(
                "AlphaBet nunca coloca apuestas sin tu confirmación explícita.\n"
                "Asegúrate de tener fondos suficientes en tu cuenta Betfair."
            ),
            text_color="#475569", font=ctk.CTkFont(size=9), justify="center",
        ).pack(pady=(4, 12))

        self._update_potential()

    def _update_potential(self, *_) -> None:
        try:
            stake = float(self._stake_var.get())
            price_str = self._live_price.get()
            if price_str and price_str[0].isdigit():
                price = float(price_str.split()[0])
                profit = round(stake * (price - 1), 2)
                self._potential_lbl.configure(
                    text=f"→  Retorno potencial: €{stake + profit:.2f}  (+ €{profit:.2f})"
                )
            else:
                self._potential_lbl.configure(text="")
        except Exception:
            self._potential_lbl.configure(text="")

    # ── Búsqueda de mercado (fondo) ───────────────────────────────────────────

    def _lookup_market(self) -> None:
        import threading
        threading.Thread(target=self._lookup_worker, daemon=True).start()

    def _lookup_worker(self) -> None:
        try:
            from ...core.betfair import BetfairClient
            client = BetfairClient(self.app_key, self.username, self.password)
            ok, msg = client.login()
            if not ok:
                self.after(0, lambda m=msg: self._live_price.set(f"❌ Login: {m}"))
                return
            self._client = client

            markets = client.find_football_market(self.home, self.away, self.pick)
            if not markets:
                self.after(0, lambda: self._live_price.set("Sin mercado disponible"))
                return

            best = markets[0]
            mid  = best["market_id"]
            sid  = best["selection_id"]
            self._market_id.set(mid)
            self._selection_id.set(sid)

            price = client.get_best_back_price(mid, sid)
            if price:
                ev_name = best["event_name"]
                self.after(0, lambda p=price, ev=ev_name: [
                    self._live_price.set(f"{p:.2f}  ({ev})"),
                    self._confirm_btn.configure(state="normal"),
                    self._update_potential(),
                ])
            else:
                self.after(0, lambda: self._live_price.set("Sin liquidez en este momento"))
        except Exception as exc:
            self.after(0, lambda e=exc: self._live_price.set(f"Error: {e}"))

    # ── Confirmación y colocación ─────────────────────────────────────────────

    def _confirm(self) -> None:
        try:
            stake = float(self._stake_var.get())
        except ValueError:
            self._status_text.set("Importe inválido.")
            return

        if stake < 2.0:
            self._status_text.set("El importe mínimo en Betfair es €2.00")
            return

        market_id    = self._market_id.get()
        selection_id = self._selection_id.get()
        if not market_id or not selection_id:
            self._status_text.set("Mercado no encontrado. Espera o cierra y reintenta.")
            return

        price_str = self._live_price.get()
        try:
            min_price = float(price_str.split()[0]) * 0.98  # tolerar ±2%
        except Exception:
            min_price = 1.01

        self._confirm_btn.configure(state="disabled")
        self._status_text.set("Colocando apuesta…")

        import threading
        threading.Thread(
            target=self._place_worker,
            args=(market_id, selection_id, stake, min_price),
            daemon=True,
        ).start()

    def _place_worker(
        self, market_id: str, selection_id: int,
        stake: float, min_price: float,
    ) -> None:
        if self._client is None:
            self.after(0, lambda: self._status_text.set("Sin sesión Betfair."))
            return

        result = self._client.place_bet(market_id, selection_id, stake, min_price)
        status = result.get("status", "ERROR")
        error  = result.get("error", "")
        bet_id = result.get("bet_id", "")

        if status in ("EXECUTABLE", "EXECUTION_COMPLETE") and not error:
            # Persistir en BD
            try:
                req_price = float(self._live_price.get().split()[0])
            except Exception:
                req_price = min_price / 0.98

            self.app.storage.save_betfair_bet({
                "market_id":       market_id,
                "selection_id":    selection_id,
                "event_name":      f"{self.home} vs {self.away}",
                "pick":            self.pick,
                "stake":           stake,
                "requested_price": req_price,
                "average_price":   result.get("average_price", 0),
                "size_matched":    result.get("size_matched", 0),
                "bet_id":          bet_id,
                "status":          "PLACED",
            })

            msg = (
                f"✅  Apuesta colocada  |  Bet ID: {bet_id}  |  "
                f"Emparejado: €{result.get('size_matched', 0):.2f} "
                f"@ {result.get('average_price', 0):.2f}"
            )
            self.after(0, lambda m=msg: [
                self._status_text.set(m),
                self._confirm_btn.configure(text="✅  Apuesta colocada"),
            ])
        else:
            msg = f"❌  Error: {error or status}"
            self.after(0, lambda m=msg: [
                self._status_text.set(m),
                self._confirm_btn.configure(state="normal"),
            ])
