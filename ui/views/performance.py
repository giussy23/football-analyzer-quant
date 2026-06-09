# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/performance.py — Vista Performance: CLV tracker, equity curve, ROI por liga.

Muestra el historial real de picks del modelo con:
  - Estadísticas globales (win rate, ROI, CLV medio)
  - Curva de equity con tkinter Canvas (sin matplotlib)
  - Desglose por liga
  - Diagnósticos del backtest walk-forward
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import customtkinter as ctk
import pandas as pd

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT


_CARD_BG  = "#040c18"
_CANVAS_BG = "#020810"
_GREEN    = "#22d3ee"
_RED      = "#f87171"
_YELLOW   = "#fbbf24"
_TEAL     = "#0d9488"
_GRID_CLR = "#0d2035"
_ZERO_CLR = "#1e4060"


def _pct(v: float) -> str:
    return f"{v*100:+.1f}%"


def _color_roi(roi: float) -> str:
    if roi > 0.05:  return _GREEN
    if roi > 0:     return "#86efac"
    if roi > -0.05: return _YELLOW
    return _RED


class PerformanceView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app   = app
        self._picks: list[dict] = []
        self._settled: list[dict] = []
        self._setup_style()
        self._build()

    # ── Estilo treeview ───────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        s = ttk.Style()
        s.configure("Perf.Treeview",
                    background=_CARD_BG, fieldbackground=_CARD_BG,
                    foreground=TEXT, rowheight=26,
                    font=("Segoe UI", 10))
        s.configure("Perf.Treeview.Heading",
                    background="#060f1e", foreground=ACCENT,
                    font=("Segoe UI", 10, "bold"))
        s.map("Perf.Treeview", background=[("selected", "#0a2535")])

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build(self) -> None:
        # ── Cabecera ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 0))
        ctk.CTkLabel(hdr, text="📈  Performance & CLV Tracker",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=ACCENT).pack(side="left")
        self._refresh_btn = ctk.CTkButton(
            hdr, text="↺  Actualizar",
            command=self.refresh,
            fg_color="#0a2535", hover_color=_TEAL,
            width=110, height=30,
            font=ctk.CTkFont(size=11),
        )
        self._refresh_btn.pack(side="right")

        # ── Tarjetas KPI ──────────────────────────────────────────────────────
        kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        kpi_row.pack(fill="x", padx=16, pady=12)
        for i in range(5):
            kpi_row.columnconfigure(i, weight=1)

        self._kpi_cards: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        kpi_defs = [
            ("picks",    "Picks rastreados"),
            ("win_rate", "Win Rate"),
            ("roi",      "ROI acum."),
            ("avg_clv",  "CLV medio"),
            ("avg_edge", "Edge medio"),
        ]
        for col, (key, label) in enumerate(kpi_defs):
            card = ctk.CTkFrame(kpi_row, fg_color=_CARD_BG, corner_radius=10,
                                border_color=BORDER, border_width=1)
            card.grid(row=0, column=col, padx=5, sticky="ew")
            ctk.CTkLabel(card, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(pady=(8, 0))
            val_var  = tk.StringVar(value="—")
            sub_var  = tk.StringVar(value="")
            ctk.CTkLabel(card, textvariable=val_var, text_color=ACCENT,
                         font=ctk.CTkFont(size=18, weight="bold")).pack(pady=2)
            ctk.CTkLabel(card, textvariable=sub_var, text_color=MUTED,
                         font=ctk.CTkFont(size=10)).pack(pady=(0, 8))
            self._kpi_cards[key] = (val_var, sub_var)

        # ── Equity curve ──────────────────────────────────────────────────────
        eq_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                border_color=BORDER, border_width=1)
        eq_frame.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(eq_frame, text="Curva de Equity",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 4))
        self._eq_canvas = tk.Canvas(eq_frame, height=200, bg=_CANVAS_BG,
                                    highlightthickness=0, bd=0)
        self._eq_canvas.pack(fill="x", padx=10, pady=(0, 10))
        self._eq_canvas.bind("<Configure>", lambda e: self._draw_equity_curve())

        # ── Desglose por liga ─────────────────────────────────────────────────
        league_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                    border_color=BORDER, border_width=1)
        league_frame.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(league_frame, text="ROI por Liga",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 4))

        self._league_tree = ttk.Treeview(
            league_frame,
            columns=("picks", "wins", "win_rate", "roi", "avg_clv", "avg_edge"),
            show="headings tree",
            style="Perf.Treeview",
            height=6,
        )
        for col, label, w in [
            ("#0",       "Liga",      120),
            ("picks",    "Picks",     55),
            ("wins",     "W / L",     70),
            ("win_rate", "Win%",      65),
            ("roi",      "ROI",       75),
            ("avg_clv",  "CLV med.",  75),
            ("avg_edge", "Edge med.", 75),
        ]:
            if col == "#0":
                self._league_tree.heading(col, text=label)
                self._league_tree.column(col, width=w, anchor="w")
            else:
                self._league_tree.heading(col, text=label, anchor="center")
                self._league_tree.column(col, width=w, anchor="center")
        self._league_tree.pack(fill="x", padx=10, pady=(0, 12))

        # ── Historial de picks (últimos 50) ───────────────────────────────────
        hist_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                  border_color=BORDER, border_width=1)
        hist_frame.pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkLabel(hist_frame, text="Historial de Picks (últimos 50)",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 4))

        self._hist_tree = ttk.Treeview(
            hist_frame,
            columns=("date", "match", "pick", "odds", "edge", "status", "pnl", "clv"),
            show="headings",
            style="Perf.Treeview",
            height=12,
        )
        for col, label, w in [
            ("date",   "Fecha",    88),
            ("match",  "Partido", 190),
            ("pick",   "Pick",     55),
            ("odds",   "Cuota",    60),
            ("edge",   "Edge",     60),
            ("status", "Res.",     55),
            ("pnl",    "P&L",      65),
            ("clv",    "CLV",      60),
        ]:
            self._hist_tree.heading(col, text=label, anchor="center")
            self._hist_tree.column(col, width=w, anchor="center")
        self._hist_tree.pack(fill="x", padx=10, pady=(0, 12))

        # Colorear filas por resultado
        self._hist_tree.tag_configure("WIN",     foreground="#4ade80")
        self._hist_tree.tag_configure("LOSS",    foreground="#f87171")
        self._hist_tree.tag_configure("PENDING", foreground=MUTED)

        # ── Diagnósticos del backtest ─────────────────────────────────────────
        diag_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                  border_color=BORDER, border_width=1)
        diag_frame.pack(fill="x", padx=16, pady=(0, 20))
        ctk.CTkLabel(diag_frame, text="Diagnóstico del Modelo",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 4))
        self._diag_text = ctk.CTkTextbox(diag_frame, height=120,
                                          fg_color=_CANVAS_BG, text_color=MUTED,
                                          font=ctk.CTkFont(size=11),
                                          state="disabled")
        self._diag_text.pack(fill="x", padx=10, pady=(0, 10))

        # Carga inicial
        self.refresh()

    # ── Actualización de datos ────────────────────────────────────────────────

    def refresh(self) -> None:
        """Recarga picks desde storage y actualiza todos los widgets."""
        try:
            self._picks   = self.app.storage.load_model_picks(limit=500)
            self._settled = [p for p in self._picks if p.get("status") in ("WIN", "LOSS")]
        except Exception:
            self._picks   = []
            self._settled = []

        self._update_kpis()
        self._draw_equity_curve()
        self._update_league_table()
        self._update_hist_table()
        self._update_diagnostics()

    def _update_kpis(self) -> None:
        total   = len(self._picks)
        settled = len(self._settled)
        wins    = sum(1 for p in self._settled if p["status"] == "WIN")
        losses  = settled - wins

        win_rate = wins / settled if settled > 0 else None

        # ROI: suma de P&L / suma de stakes (asumiendo stake ≈ bankroll_pct * 1000)
        pnl_total   = sum(p.get("pnl", 0) or 0 for p in self._settled)
        stakes_total = sum(
            (p.get("bankroll_pct", 0) or 0) * 10  # 10€ por % de bankroll como referencia
            for p in self._settled
        )
        roi = pnl_total / stakes_total if stakes_total > 0 else None

        clv_vals  = [p["clv"]  for p in self._settled if p.get("clv")  is not None]
        edge_vals = [p["edge"] for p in self._picks   if p.get("edge") is not None]

        avg_clv  = sum(clv_vals)  / len(clv_vals)  if clv_vals  else None
        avg_edge = sum(edge_vals) / len(edge_vals) if edge_vals else None

        def _set(key, val_str, sub_str="", color=ACCENT):
            v, s = self._kpi_cards[key]
            v.set(val_str)
            s.set(sub_str)

        _set("picks",    str(total),
             f"{wins}W / {losses}L / {total - settled}P")
        _set("win_rate", f"{win_rate*100:.1f}%" if win_rate is not None else "—",
             f"de {settled} liquidados")
        _set("roi",      _pct(roi) if roi is not None else "—",
             "calculado sobre stakes")
        _set("avg_clv",  _pct(avg_clv) if avg_clv is not None else "—",
             f"n={len(clv_vals)}" if clv_vals else "sin datos")
        _set("avg_edge", _pct(avg_edge) if avg_edge is not None else "—",
             f"n={len(edge_vals)}" if edge_vals else "")

        # Actualizar color ROI
        if roi is not None:
            self._kpi_cards["roi"][0].set(_pct(roi))

    # ── Curva de equity ───────────────────────────────────────────────────────

    def _draw_equity_curve(self) -> None:
        c = self._eq_canvas
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height() or 200
        if W < 50:
            return

        PAD_L, PAD_R, PAD_T, PAD_B = 50, 20, 15, 30

        settled = sorted(
            self._settled,
            key=lambda p: p.get("saved_at", "") or "",
        )

        if len(settled) < 2:
            c.create_text(W // 2, H // 2, text="Sin suficientes picks liquidados",
                          fill=MUTED, font=("Segoe UI", 11))
            return

        # Calcular curva de P&L acumulado
        cum_pnl = []
        acc = 0.0
        for p in settled:
            acc += p.get("pnl", 0) or 0
            cum_pnl.append(acc)

        pnl_min = min(cum_pnl)
        pnl_max = max(cum_pnl)
        pnl_range = max(pnl_max - pnl_min, 1.0)

        # Dibujar grid horizontal
        chart_w = W - PAD_L - PAD_R
        chart_h = H - PAD_T - PAD_B
        n_lines = 5
        for i in range(n_lines + 1):
            y = PAD_T + chart_h * i // n_lines
            pnl_val = pnl_max - pnl_range * i / n_lines
            c.create_line(PAD_L, y, W - PAD_R, y, fill=_GRID_CLR, dash=(2, 4))
            c.create_text(PAD_L - 4, y, text=f"{pnl_val:+.0f}",
                          fill=MUTED, font=("Segoe UI", 8), anchor="e")

        # Línea de zero
        if pnl_min < 0 < pnl_max:
            y0 = PAD_T + int(chart_h * (pnl_max / pnl_range))
            c.create_line(PAD_L, y0, W - PAD_R, y0, fill=_ZERO_CLR, width=1)

        # Construir puntos de la curva
        n = len(cum_pnl)
        coords = []
        for i, v in enumerate(cum_pnl):
            x = PAD_L + int(chart_w * i / (n - 1))
            y = PAD_T + int(chart_h * (pnl_max - v) / pnl_range)
            coords.extend([x, y])

        # Área bajo la curva (relleno sutil)
        y_zero = PAD_T + int(chart_h * max(0, pnl_max) / pnl_range)
        fill_coords = [PAD_L, y_zero] + coords + [W - PAD_R, y_zero]
        c.create_polygon(fill_coords, fill="#042030", outline="")

        # Línea principal de equity
        if len(coords) >= 4:
            final_pnl = cum_pnl[-1]
            line_col  = _GREEN if final_pnl >= 0 else _RED
            c.create_line(*coords, fill=line_col, width=2, smooth=True)

        # Punto final
        if coords:
            xf, yf = coords[-2], coords[-1]
            final_pnl = cum_pnl[-1]
            dot_col = _GREEN if final_pnl >= 0 else _RED
            c.create_oval(xf - 4, yf - 4, xf + 4, yf + 4,
                          fill=dot_col, outline="")
            c.create_text(xf + 6, yf, text=f"{final_pnl:+.1f}€",
                          fill=dot_col, font=("Segoe UI", 9, "bold"), anchor="w")

        # Etiqueta eje X
        c.create_text(PAD_L + chart_w // 2, H - 5,
                      text=f"Picks liquidados: {n}",
                      fill=MUTED, font=("Segoe UI", 9))

    # ── Tabla por liga ────────────────────────────────────────────────────────

    def _update_league_table(self) -> None:
        for row in self._league_tree.get_children():
            self._league_tree.delete(row)

        if not self._picks:
            return

        # Agrupar por liga
        from collections import defaultdict
        groups: dict[str, list[dict]] = defaultdict(list)
        for p in self._picks:
            league = p.get("league", "?")
            groups[league].append(p)

        for league, picks in sorted(groups.items()):
            sett = [p for p in picks if p.get("status") in ("WIN", "LOSS")]
            wins = sum(1 for p in sett if p["status"] == "WIN")
            losses = len(sett) - wins
            wr   = wins / len(sett) if sett else None
            pnl_sum = sum(p.get("pnl", 0) or 0 for p in sett)
            st_sum  = sum((p.get("bankroll_pct", 0) or 0) * 10 for p in sett)
            roi  = pnl_sum / st_sum if st_sum > 0 else None
            clvs = [p["clv"] for p in sett if p.get("clv") is not None]
            avg_clv = sum(clvs) / len(clvs) if clvs else None
            edges = [p["edge"] for p in picks if p.get("edge") is not None]
            avg_e = sum(edges) / len(edges) if edges else None

            self._league_tree.insert(
                "", "end",
                text=league,
                values=(
                    len(picks),
                    f"{wins}W/{losses}L",
                    f"{wr*100:.0f}%" if wr is not None else "—",
                    _pct(roi) if roi is not None else "—",
                    _pct(avg_clv) if avg_clv is not None else "—",
                    _pct(avg_e) if avg_e is not None else "—",
                ),
            )

    # ── Historial de picks ────────────────────────────────────────────────────

    def _update_hist_table(self) -> None:
        for row in self._hist_tree.get_children():
            self._hist_tree.delete(row)

        for p in self._picks[:50]:
            date_str = str(p.get("date", "") or "")[:10]
            match    = f"{p.get('home_team','?')} v {p.get('away_team','?')}"
            pick     = str(p.get("pick", "?"))
            odds_v   = p.get("odds")
            edge_v   = p.get("edge")
            status   = str(p.get("status", "PENDING"))
            pnl_v    = p.get("pnl")
            clv_v    = p.get("clv")

            tag = "WIN" if status == "WIN" else ("LOSS" if status == "LOSS" else "PENDING")

            self._hist_tree.insert(
                "", "end", tags=(tag,),
                values=(
                    date_str,
                    match,
                    pick,
                    f"{odds_v:.2f}" if odds_v else "—",
                    _pct(edge_v) if edge_v else "—",
                    status,
                    f"{pnl_v:+.2f}" if pnl_v is not None else "—",
                    _pct(clv_v) if clv_v is not None else "—",
                ),
            )

    # ── Diagnósticos del backtest ─────────────────────────────────────────────

    def _update_diagnostics(self) -> None:
        lines: list[str] = []

        # Diagnósticos del último análisis
        if hasattr(self.app, "diagnostics") and self.app.diagnostics:
            lines += ["── Diagnóstico del modelo ──"]
            lines += self.app.diagnostics

        # Backtest por liga
        if hasattr(self.app, "backtest_summary") and self.app.backtest_summary:
            lines += ["", "── Backtest walk-forward por liga ──"]
            for div, bt in self.app.backtest_summary.items():
                roi   = bt.get("roi", None)
                n     = bt.get("n_bets", 0)
                ll    = bt.get("match_logloss", None)
                pure  = "✓ pure WF" if bt.get("pure_wf") else "≈ pseudo-OOS"
                roi_s = f"ROI={_pct(roi)}" if roi is not None else "ROI=?"
                ll_s  = f"  logloss={ll:.4f}" if ll else ""
                lines.append(f"{div:>4}  n={n:>4}  {roi_s}{ll_s}  [{pure}]")

        if not lines:
            lines = ["Ejecuta un análisis primero para ver los diagnósticos."]

        self._diag_text.configure(state="normal")
        self._diag_text.delete("1.0", "end")
        self._diag_text.insert("1.0", "\n".join(lines))
        self._diag_text.configure(state="disabled")
