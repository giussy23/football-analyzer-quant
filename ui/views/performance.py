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

        self._kpi_cards: dict = {}

        def _kpi_card(parent, key, label):
            """Tarjeta KPI estilo hero: acento lateral de color + valor grande,
            alineada a la izquierda y con aire (lenguaje del mockup Aurora Glass)."""
            card = ctk.CTkFrame(parent, fg_color=CARD_2, corner_radius=16,
                                border_color=BORDER, border_width=1)
            strip = ctk.CTkFrame(card, fg_color=ACCENT, width=4, corner_radius=2)
            strip.pack(side="left", fill="y", padx=(8, 0), pady=14)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=(14, 12), pady=14)
            ctk.CTkLabel(body, text=label, text_color=MUTED,
                         font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
            val_var = tk.StringVar(value="—")
            sub_var = tk.StringVar(value="")
            val_lbl = ctk.CTkLabel(body, textvariable=val_var, text_color=ACCENT,
                                   font=ctk.CTkFont(size=30, weight="bold"), anchor="w")
            val_lbl.pack(anchor="w", pady=(6, 2))
            ctk.CTkLabel(body, textvariable=sub_var, text_color=MUTED,
                         font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w")
            self._kpi_cards[key] = (val_var, sub_var, val_lbl, card, strip)
            return card

        # ── Tarjetas KPI — fila 1 (4 grandes) ────────────────────────────────
        kpi_row = ctk.CTkFrame(self, fg_color="transparent")
        kpi_row.pack(fill="x", padx=20, pady=(16, 10))
        for i in range(4):
            kpi_row.columnconfigure(i, weight=1)
        for col, (key, label) in enumerate([
            ("picks",    "Picks rastreados"),
            ("win_rate", "Win rate"),
            ("roi",      "ROI acumulado"),
            ("avg_clv",  "CLV medio"),
        ]):
            _kpi_card(kpi_row, key, label).grid(row=0, column=col, padx=8, sticky="ew")

        # ── Tarjetas KPI — fila 2 (Edge, Sharpe, Max DD, Racha) ──────────────
        kpi_row2 = ctk.CTkFrame(self, fg_color="transparent")
        kpi_row2.pack(fill="x", padx=20, pady=(0, 14))
        for i in range(4):
            kpi_row2.columnconfigure(i, weight=1)
        for col, (key, label) in enumerate([
            ("avg_edge", "Edge medio"),
            ("sharpe",   "Sharpe ratio"),
            ("max_dd",   "Max drawdown"),
            ("racha",    "Racha actual"),
        ]):
            _kpi_card(kpi_row2, key, label).grid(row=0, column=col, padx=8, sticky="ew")

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

        # ── Calibración del modelo (reliability diagram) ──────────────────────
        cal_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                 border_color=BORDER, border_width=1)
        cal_frame.pack(fill="x", padx=16, pady=(0, 12))
        cal_header = ctk.CTkFrame(cal_frame, fg_color="transparent")
        cal_header.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(cal_header, text="Calibración del modelo",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(side="left")
        self._cal_info = tk.StringVar(value="")
        ctk.CTkLabel(cal_header, textvariable=self._cal_info, text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="right")
        self._cal_canvas = tk.Canvas(cal_frame, height=240, bg=_CANVAS_BG,
                                     highlightthickness=0, bd=0)
        self._cal_canvas.pack(fill="x", padx=10, pady=(0, 10))
        self._cal_canvas.bind("<Configure>", lambda e: self._draw_calibration())

        # ── ARB / Valor extremo scanner ───────────────────────────────────────
        arb_frame = ctk.CTkFrame(self, fg_color=_CARD_BG, corner_radius=12,
                                 border_color=BORDER, border_width=1)
        arb_frame.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(arb_frame, text="🎯  Scanner ARB / Valor Extremo",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 4))
        self._arb_tree = ttk.Treeview(
            arb_frame,
            columns=("match", "pick", "our_odds", "mkt_odds", "edge", "type"),
            show="headings",
            style="Perf.Treeview",
            height=4,
        )
        for col, label, w in [
            ("match",    "Partido",      210),
            ("pick",     "Pick",          55),
            ("our_odds", "Cuota justa",   90),
            ("mkt_odds", "Cuota mkt.",    90),
            ("edge",     "Edge",          70),
            ("type",     "Señal",        115),
        ]:
            self._arb_tree.heading(col, text=label, anchor="center")
            self._arb_tree.column(col, width=w, anchor="center")
        self._arb_tree.tag_configure("HARD_ARB", foreground="#22c55e")
        self._arb_tree.tag_configure("SOFT_ARB", foreground="#fbbf24")
        self._arb_tree.pack(fill="x", padx=10, pady=(0, 4))
        self._arb_lbl = ctk.CTkLabel(
            arb_frame, text="Ejecuta Run Analysis para ver señales.",
            text_color=MUTED, font=ctk.CTkFont(size=10))
        self._arb_lbl.pack(anchor="w", padx=14, pady=(0, 8))

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
        self._draw_calibration()
        self._update_arb_scanner()
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
            entry = self._kpi_cards.get(key)
            if not entry:
                return
            entry[0].set(val_str)
            entry[1].set(sub_str)
            if len(entry) > 2:
                entry[2].configure(text_color=color)
            # Acento lateral + borde de color según el estado semántico → "vida"
            # de un vistazo; el acento lateral siempre toma el color del valor.
            if len(entry) > 4:
                entry[4].configure(fg_color=color if color != MUTED else BORDER)
            if len(entry) > 3:
                if color in (_GREEN, _YELLOW, _RED):
                    entry[3].configure(border_color=color, border_width=2)
                else:
                    entry[3].configure(border_color=BORDER, border_width=1)

        _set("picks",    str(total),
             f"{wins}W / {losses}L / {total - settled}P")
        wr_col = (_GREEN if win_rate >= 0.5 else _RED) if win_rate is not None else ACCENT
        _set("win_rate", f"{win_rate*100:.1f}%" if win_rate is not None else "—",
             f"de {settled} liquidados", wr_col)
        roi_col = _color_roi(roi) if roi is not None else MUTED
        _set("roi",      _pct(roi) if roi is not None else "—",
             "calculado sobre stakes", roi_col)
        clv_col = (_GREEN if avg_clv > 0 else _RED) if avg_clv is not None else MUTED
        _set("avg_clv",  _pct(avg_clv) if avg_clv is not None else "—",
             f"n={len(clv_vals)}" if clv_vals else "sin datos", clv_col)
        edge_col = (_GREEN if avg_edge > 0 else _RED) if avg_edge is not None else MUTED
        _set("avg_edge", _pct(avg_edge) if avg_edge is not None else "—",
             f"n={len(edge_vals)}" if edge_vals else "", edge_col)

        # ── KPIs avanzados: Sharpe, Max Drawdown, Racha ───────────────────────
        stats = self._compute_advanced_stats()
        self._last_adv_stats = stats   # caché para equity curve

        sharpe = stats.get("sharpe")
        max_dd = stats.get("max_drawdown", 0.0)
        racha  = stats.get("racha", 0)
        rdir   = stats.get("racha_dir", "+")

        if sharpe is not None:
            sc = _GREEN if sharpe >= 2.0 else (_YELLOW if sharpe >= 1.0 else _RED)
            _set("sharpe", f"{sharpe:.2f}", "≥1 bueno  |  ≥2 excelente", sc)
        else:
            _set("sharpe", "—", "sin suficientes datos", MUTED)

        if max_dd > 0:
            _set("max_dd", f"-{max_dd:.1f}€", "pico → valle máximo en equity", _RED)
        else:
            _set("max_dd", "—", "sin datos aún", MUTED)

        if racha > 0:
            racha_col = _GREEN if rdir == "+" else _RED
            racha_sub = "wins seguidas" if rdir == "+" else "pérdidas seguidas"
            _set("racha", f"{rdir}{racha}", racha_sub, racha_col)
        else:
            _set("racha", "—", "", MUTED)

    # ── Curva de equity ───────────────────────────────────────────────────────

    def _draw_empty_state(self, canvas, icon: str, title: str, subtitle: str = "") -> None:
        """Estado vacío elegante: icono grande + título + subtítulo centrados,
        en vez de una caja vacía con una sola línea de texto."""
        canvas.delete("all")
        W = canvas.winfo_width()
        H = canvas.winfo_height() or 200
        cx, cy = W // 2, H // 2
        canvas.create_text(cx, cy - 24, text=icon,
                           font=("Segoe UI Emoji", 30), fill=MUTED)
        canvas.create_text(cx, cy + 14, text=title,
                           font=("Segoe UI Semibold", 13), fill=ACCENT)
        if subtitle:
            canvas.create_text(cx, cy + 36, text=subtitle,
                               font=("Segoe UI", 10), fill=MUTED)

    def _draw_calibration(self) -> None:
        """Reliability diagram: probabilidad predicha (x) vs frecuencia real (y).
        La diagonal es la calibración perfecta; cada punto es un intervalo de
        probabilidad, con radio proporcional al nº de picks."""
        c = self._cal_canvas
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height() or 240
        if W < 50:
            return

        from ...core.calibration import compute_calibration, calibration_grade
        cal   = compute_calibration(self._settled, n_bins=10)
        bins  = cal["bins"]
        brier = cal["brier"]

        if brier is None or not bins:
            self._cal_info.set("")
            self._draw_empty_state(
                c, "🎯", "Aún no hay datos de calibración",
                "Liquida algunos picks para ver el diagrama de fiabilidad")
            return

        from ...core.prob_calibrator import MIN_SAMPLES
        if cal["n"] >= MIN_SAMPLES:
            corr = "· corrección ON"
        else:
            corr = f"· corrección en {MIN_SAMPLES - cal['n']} picks"
        self._cal_info.set(
            f"Brier {brier:.3f} · {calibration_grade(brier)} · n={cal['n']} {corr}")

        PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 12, 26
        size = min(W - PAD_L - PAD_R, H - PAD_T - PAD_B)
        if size < 20:
            return
        x0, y0 = PAD_L, PAD_T
        x1, y1 = x0 + size, y0 + size

        def px(v: float) -> float:
            return x0 + v * size

        def py(v: float) -> float:
            return y1 - v * size      # eje y invertido (0 abajo, 1 arriba)

        # Grid + etiquetas de eje
        for g in (0.0, 0.25, 0.5, 0.75, 1.0):
            c.create_line(px(g), y0, px(g), y1, fill=_GRID_CLR)
            c.create_line(x0, py(g), x1, py(g), fill=_GRID_CLR)
            c.create_text(px(g), y1 + 11, text=f"{g:.2f}",
                          fill=MUTED, font=("Segoe UI", 7))
            c.create_text(x0 - 16, py(g), text=f"{g:.2f}",
                          fill=MUTED, font=("Segoe UI", 7))

        # Diagonal de calibración perfecta
        c.create_line(px(0), py(0), px(1), py(1), fill=_ZERO_CLR, dash=(4, 3))

        # Curva de fiabilidad (une los bins) + puntos
        max_count = max(b["count"] for b in bins)
        pts: list[float] = []
        for b in bins:
            pts += [px(b["pred"]), py(b["obs"])]
        if len(pts) >= 4:
            c.create_line(*pts, fill=ACCENT, width=2, smooth=True)
        for b in bins:
            x, y = px(b["pred"]), py(b["obs"])
            r = 3 + 5 * (b["count"] / max_count)
            err = abs(b["pred"] - b["obs"])
            col = _GREEN if err < 0.08 else (_YELLOW if err < 0.18 else _RED)
            c.create_oval(x - r, y - r, x + r, y + r, fill=col, outline="")

        # Etiquetas de ejes
        c.create_text((x0 + x1) // 2, y1 + 21, text="Probabilidad predicha",
                      fill=MUTED, font=("Segoe UI", 8))
        c.create_text(x0 - 32, (y0 + y1) // 2, text="Frecuencia real",
                      fill=MUTED, font=("Segoe UI", 8), angle=90)

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
            self._draw_empty_state(
                c, "📈", "Tu curva de equity aparecerá aquí",
                "Ejecuta Run Analysis y liquida picks para construirla")
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

        # Sombreado de max drawdown (pico → valle)
        _ast = getattr(self, "_last_adv_stats", {})
        _dpi = _ast.get("dd_peak_i")
        _dti = _ast.get("dd_trough_i")
        _mdd = _ast.get("max_drawdown", 0.0)
        if _dpi is not None and _dti is not None and _dti > _dpi and _mdd > 0:
            xp = PAD_L + int(chart_w * _dpi / (n - 1))
            xt = PAD_L + int(chart_w * _dti / (n - 1))
            c.create_rectangle(xp, PAD_T, xt, H - PAD_B, fill="#1c0505", outline="")
            yp = PAD_T + int(chart_h * (pnl_max - cum_pnl[_dpi]) / pnl_range)
            yt = PAD_T + int(chart_h * (pnl_max - cum_pnl[_dti]) / pnl_range)
            c.create_line(xp, yp, xp, H - PAD_B, fill="#7f1d1d", dash=(3, 3), width=1)
            c.create_line(xt, yt, xt, H - PAD_B, fill="#dc2626", dash=(3, 3), width=1)
            c.create_text(xt + 5, yt + 10,
                          text=f"MaxDD -{_mdd:.1f}€",
                          fill="#f87171", font=("Segoe UI", 8, "bold"), anchor="w")

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

    # ── Estadísticas avanzadas ────────────────────────────────────────────────

    def _compute_advanced_stats(self) -> dict:
        """Calcula Sharpe ratio, max drawdown y racha actual."""
        import math
        import statistics as _st

        s = sorted(self._settled, key=lambda p: p.get("saved_at", "") or "")
        if not s:
            return {}

        pnl_list = [float(p.get("pnl", 0.0) or 0.0) for p in s]

        # Curva acumulada de P&L
        cum, acc = [], 0.0
        for v in pnl_list:
            acc += v
            cum.append(acc)

        # Sharpe por pick: (media / std) × √n  — sin anualizar
        sharpe = None
        if len(pnl_list) >= 4:
            mean_p = _st.mean(pnl_list)
            std_p  = _st.stdev(pnl_list)
            if std_p > 1e-9:
                sharpe = (mean_p / std_p) * math.sqrt(len(pnl_list))

        # Max drawdown: mayor caída pico → valle en la curva de equity
        peak, max_dd = cum[0], 0.0
        tmp_peak_i = dd_peak_i = dd_trough_i = 0
        for i, v in enumerate(cum):
            if v > peak:
                peak = v
                tmp_peak_i = i
            dd = peak - v
            if dd > max_dd:
                max_dd = dd
                dd_peak_i   = tmp_peak_i
                dd_trough_i = i

        # Racha actual (wins o losses consecutivas al final de la serie)
        statuses = [p.get("status") for p in s]
        last_st  = statuses[-1] if statuses else None
        racha    = 0
        for st in reversed(statuses):
            if st == last_st:
                racha += 1
            else:
                break

        return {
            "sharpe":       sharpe,
            "max_drawdown": max_dd,
            "dd_peak_i":    dd_peak_i,
            "dd_trough_i":  dd_trough_i,
            "racha":        racha,
            "racha_dir":    "+" if last_st == "WIN" else "-",
            "cum_pnl":      cum,
            "n":            len(pnl_list),
        }

    # ── Scanner ARB / valor extremo ───────────────────────────────────────────

    def _update_arb_scanner(self) -> None:
        """Rellena el scanner con picks de edge extremo del análisis activo."""
        for row in self._arb_tree.get_children():
            self._arb_tree.delete(row)

        # Leer el DataFrame del análisis más reciente
        df = getattr(self.app, "filtered", None)
        if df is None or (hasattr(df, "empty") and df.empty):
            df = getattr(self.app, "results", None)
        if df is None or (hasattr(df, "empty") and df.empty):
            self._arb_lbl.configure(
                text="Ejecuta Run Analysis para ver señales.")
            return

        signals = []
        for _, row in df.iterrows():
            edge      = float(row.get("edge") or 0.0)
            mkt_odds  = float(row.get("odds") or 0.0)
            mod_prob  = float(row.get("model_prob") or 0.0)
            overr     = float(row.get("open_overround") or 1.08)
            pick      = str(row.get("pick", ""))
            match     = f"{row.get('home_team','?')} v {row.get('away_team','?')}"

            if edge <= 0:
                continue

            our_fair = round(1.0 / mod_prob, 2) if mod_prob > 0 else None

            if overr < 1.0:
                sig_type, tag = "HARD ARB  🟢", "HARD_ARB"
            elif edge >= 0.12:
                sig_type, tag = "VALOR EXTREMO ⚡", "SOFT_ARB"
            elif edge >= 0.08:
                sig_type, tag = "VALOR ALTO", "SOFT_ARB"
            else:
                continue

            signals.append({
                "match": match, "pick": pick,
                "our_odds": our_fair, "mkt_odds": round(mkt_odds, 2) if mkt_odds else None,
                "edge": edge, "type": sig_type, "tag": tag,
            })

        if not signals:
            n_total = len(df) if hasattr(df, "__len__") else "?"
            self._arb_lbl.configure(
                text=f"Sin señales de valor extremo (edge < 8%) en {n_total} picks analizados.")
            return

        signals.sort(key=lambda x: -x["edge"])
        for sig in signals:
            self._arb_tree.insert(
                "", "end", tags=(sig["tag"],),
                values=(
                    sig["match"], sig["pick"],
                    f"{sig['our_odds']:.2f}" if sig["our_odds"] else "—",
                    f"{sig['mkt_odds']:.2f}" if sig["mkt_odds"] else "—",
                    f"+{sig['edge']*100:.1f}%",
                    sig["type"],
                ),
            )

        n_hard = sum(1 for s in signals if s["tag"] == "HARD_ARB")
        n_soft = len(signals) - n_hard
        parts  = []
        if n_hard: parts.append(f"{n_hard} hard ARB")
        if n_soft: parts.append(f"{n_soft} valor extremo/alto")
        self._arb_lbl.configure(
            text=f"⚡  {len(signals)} señal(es): {' | '.join(parts)}")

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
