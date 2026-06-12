# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/portfolio.py — Vista Portfolio: historial de combinadas y ROI acumulado.
ui/views/execution.py — Vista Execution: simulador manual y bet builder.
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import customtkinter as ctk
import pandas as pd
from tkinter import messagebox

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ..widgets import make_card, make_textbox, textbox_set

# Monte Carlo — importación diferida para no romper si matplotlib no está
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    _MPL_OK = True
except ImportError:
    _MPL_OK = False

try:
    from ...core.montecarlo import simulate_bankroll
    _MC_OK = True
except ImportError:
    _MC_OK = False

# Colores propios del gráfico Monte Carlo
_MC_BG      = "#040c18"
_MC_FILL_25 = "#22c55e"   # banda p25-p75
_MC_FILL_10 = "#166534"   # banda p10-p90
_MC_LINE    = "#22c55e"   # mediana
_MC_BASE    = "#98d4aa"   # baseline

# Colores del tablero de apuestas
_BOARD_CARD    = "#060f07"
_BOARD_HDR     = "#091408"
_BTN_NORMAL    = "#0f2e14"
_BTN_HOVER     = "#1a4d22"
_BTN_SELECTED  = "#22c55e"
_BTN_SEL_TEXT  = "#061006"
_RISK_COLORS   = {
    "VERDE":    "#22c55e",
    "AMARILLO": "#fbbf24",
    "ROJO":     "#6b7280",
    "CLAUDE":   "#818cf8",
}


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio view
# ══════════════════════════════════════════════════════════════════════════════

class PortfolioView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._setup_style()
        self._build()

    def _setup_style(self) -> None:
        style = ttk.Style()
        style.configure(
            "Portfolio.Treeview",
            background="#050e1c", fieldbackground="#050e1c",
            foreground="#f0fff4", rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Portfolio.Treeview.Heading",
            background="#091408", foreground="#f0fff4",
            font=("Segoe UI Semibold", 10),
        )
        style.map("Portfolio.Treeview", background=[("selected", "#1a4d2a")])

    def _build(self) -> None:
        self._build_kpis()
        self._build_table()
        self._build_detail_box()
        self._build_action_bar()
        self._build_montecarlo()

    def _build_kpis(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1)

        kpi_defs = [
            ("total_lbl",  "Combinadas",    "0"),
            ("hit_lbl",    "Hit rate",       "—"),
            ("profit_lbl", "Profit total",   "0.00 €"),
            ("roi_lbl",    "ROI acumulado",  "—"),
        ]
        self._kpi_labels: dict[str, ctk.CTkLabel] = {}
        for col, (key, title, default) in enumerate(kpi_defs):
            card = ctk.CTkFrame(
                row, fg_color=CARD, corner_radius=12,
                border_color=BORDER, border_width=1,
            )
            card.grid(row=0, column=col, sticky="ew",
                      padx=(0 if col == 0 else 6, 0))
            ctk.CTkLabel(
                card, text=title, text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=12, pady=(10, 2))
            lbl = ctk.CTkLabel(
                card, text=default, text_color=ACCENT,
                font=ctk.CTkFont(size=22, weight="bold"),
            )
            lbl.pack(anchor="w", padx=12, pady=(0, 10))
            self._kpi_labels[key] = lbl

    def _build_table(self) -> None:
        shell = ctk.CTkFrame(
            self, fg_color="#060f07", corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        shell.pack(fill="x", pady=(0, 6))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("#", "fecha", "legs", "cuota", "stake", "profit", "roi", "estado", "selecciones")
        self.tree = ttk.Treeview(
            shell, columns=cols, show="headings",
            style="Portfolio.Treeview", selectmode="browse",
            height=10,
        )
        col_cfg = {
            "#":           (35,  "center"),
            "fecha":       (120, "center"),
            "legs":        (45,  "center"),
            "cuota":       (65,  "center"),
            "stake":       (70,  "center"),
            "profit":      (80,  "center"),
            "roi":         (72,  "center"),
            "estado":      (85,  "center"),
            "selecciones": (260, "w"),
        }
        headers = {
            "#": "#", "fecha": "Fecha", "legs": "Legs",
            "cuota": "Cuota", "stake": "Stake €",
            "profit": "Profit €", "roi": "ROI %",
            "estado": "Estado", "selecciones": "Selecciones",
        }
        for col in cols:
            w, anchor = col_cfg[col]
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=w, anchor=anchor, minwidth=w)

        self.tree.tag_configure("win",     background="#0e2d1d", foreground="#d6ffe6")
        self.tree.tag_configure("loss",    background="#341313", foreground="#ffd3d3")
        self.tree.tag_configure("pending", background="#050e1c", foreground="#dbe7f8")

        vsb = ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        vsb.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _build_detail_box(self) -> None:
        self._detail_box = make_textbox(self, height=68)
        self._detail_box.pack(fill="x", pady=(0, 6))
        textbox_set(self._detail_box, "Selecciona una combinada para ver sus selecciones.")

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))

        ctk.CTkButton(
            bar, text="✅ Ganada",
            command=lambda: self.app.settle_combo_selected("WIN"),
            fg_color="#166534", hover_color="#14532d",
            height=36, corner_radius=10,
        ).pack(side="left")
        ctk.CTkButton(
            bar, text="❌ Perdida",
            command=lambda: self.app.settle_combo_selected("LOSS"),
            fg_color="#991b1b", hover_color="#7f1d1d",
            height=36, corner_radius=10,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            bar, text="🗑 Eliminar",
            command=self.app.delete_combo,
            fg_color="#4b1111", hover_color="#3b0d0d",
            height=36, corner_radius=10,
        ).pack(side="left")

        self._status_lbl = ctk.CTkLabel(
            bar, text="Selecciona una combinada para liquidar",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._status_lbl.pack(side="left", padx=10)

        ctk.CTkButton(
            bar, text="📤 Enviar a Telegram",
            command=self.app.send_combo,
            fg_color=ACCENT, hover_color=ACCENT_2,
            height=36, corner_radius=10,
        ).pack(side="right")

    # ── Selección ──────────────────────────────────────────────────────────────

    def selected_db_id(self) -> "int | None":
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Portfolio", "Selecciona una combinada primero.")
            return None
        try:
            return int(sel[0])
        except ValueError:
            messagebox.showwarning("Portfolio", "No se pudo identificar la combinada.")
            return None

    def _on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        try:
            db_id = int(sel[0])
        except ValueError:
            return
        combo = next(
            (h for h in self.app.history if h.get("_db_id") == db_id), None
        )
        if not combo:
            return

        legs   = combo.get("legs", [])
        header = (
            f"{'⭐ ' if combo.get('risk') == 'VERDE' else ''}"
            f"{len(legs)} legs · cuota {float(combo.get('total_odds', 0)):.2f} · "
            f"stake {float(combo.get('stake_amount', 0)):.2f} €"
        )
        lines = [header, ""]
        for i, leg in enumerate(legs, 1):
            lines.append(
                f"  {i}. {leg.get('match', '?')}  ·  "
                f"{leg.get('pick', '?')} @ {float(leg.get('odds', 0)):.2f}"
                f"  (Edge {float(leg.get('edge', 0)):.2%} · Rel {int(leg.get('reliability', 0))})"
            )
        textbox_set(self._detail_box, "\n".join(lines))

        status = combo.get("status", "PENDING")
        if status == "PENDING":
            self._status_lbl.configure(
                text="PENDIENTE — liquida con ✅ o ❌",
                text_color=MUTED,
            )
        else:
            pnl   = float(combo.get("profit", 0))
            color = "#22c55e" if pnl >= 0 else "#ef4444"
            self._status_lbl.configure(
                text=f"{status} · Profit {pnl:+.2f} €",
                text_color=color,
            )

    # ── Refresh (llamado desde app.py) ────────────────────────────────────────

    def refresh_roi(self, agg: dict) -> None:
        total   = len(self.app.history)
        settled = agg["count"]
        hit     = (agg["wins"] / settled * 100) if settled > 0 else 0.0
        profit  = agg["profit"]
        roi     = agg["roi"]

        self._kpi_labels["total_lbl"].configure(text=str(total), text_color=ACCENT)
        self._kpi_labels["hit_lbl"].configure(
            text=f"{hit:.1f}%" if settled > 0 else "—",
            text_color=ACCENT if hit >= 50 else ("#ef4444" if settled > 0 else MUTED),
        )
        self._kpi_labels["profit_lbl"].configure(
            text=f"{profit:+.2f} €",
            text_color=ACCENT if profit >= 0 else "#ef4444",
        )
        self._kpi_labels["roi_lbl"].configure(
            text=f"{roi:+.2f}%" if settled > 0 else "—",
            text_color=ACCENT if roi >= 0 else ("#ef4444" if settled > 0 else MUTED),
        )

    def refresh_history(self, history: list[dict]) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, item in enumerate(history, start=1):
            status = item.get("status", "PENDING")
            tag    = "win" if status == "WIN" else "loss" if status == "LOSS" else "pending"
            legs   = item.get("legs", [])
            profit = float(item.get("profit", 0) or 0)
            roi    = float(item.get("roi",    0) or 0)

            picks_str = "  +  ".join(
                f"{l.get('pick', '?')}@{float(l.get('odds', 0)):.2f}"
                for l in legs[:3]
            )
            if len(legs) > 3:
                picks_str += f" +{len(legs) - 3}…"

            self.tree.insert(
                "", "end",
                iid=str(item.get("_db_id", idx)),
                tags=(tag,),
                values=(
                    idx,
                    item.get("timestamp", "")[:16],
                    len(legs),
                    f"{float(item.get('total_odds', 0)):.2f}",
                    f"{float(item.get('stake_amount', 0)):.2f}",
                    f"{profit:+.2f}" if status != "PENDING" else "—",
                    f"{roi:+.1f}%"   if status != "PENDING" else "—",
                    status,
                    picks_str,
                ),
            )

    # ── Monte Carlo ────────────────────────────────────────────────────────────

    def _build_montecarlo(self) -> None:
        """Construye el panel Monte Carlo al final de PortfolioView."""
        self._mc_picks: list[dict] = []

        # ── Contenedor principal ───────────────────────────────────────────────
        mc_frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        mc_frame.pack(fill="x", pady=(12, 8))

        # Cabecera
        hdr = ctk.CTkFrame(mc_frame, fg_color=CARD, corner_radius=0)
        hdr.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            hdr, text="Simulador Monte Carlo — Bankroll",
            text_color=ACCENT, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            hdr, text="Proyección probabilística del bankroll futuro",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=12)

        # ── Fila de controles ──────────────────────────────────────────────────
        ctrl_row = ctk.CTkFrame(mc_frame, fg_color="transparent")
        ctrl_row.pack(fill="x", padx=14, pady=(0, 10))

        # Bankroll inicial (Entry)
        ctk.CTkLabel(
            ctrl_row, text="Bankroll (€)",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self._mc_bankroll_var = tk.StringVar(value="1000")
        ctk.CTkEntry(
            ctrl_row, textvariable=self._mc_bankroll_var,
            width=80, fg_color=CARD, border_color=BORDER,
            text_color="#f0fff4", font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 16))

        # Nº simulaciones (Slider 1000–10000)
        ctk.CTkLabel(
            ctrl_row, text="Simulaciones",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self._mc_nsims_var = tk.IntVar(value=3000)
        self._mc_nsims_lbl = ctk.CTkLabel(
            ctrl_row, text="3000",
            text_color="#f0fff4", font=ctk.CTkFont(size=11),
            width=44,
        )
        ctk.CTkSlider(
            ctrl_row, from_=1000, to=10000,
            number_of_steps=9, variable=self._mc_nsims_var,
            button_color=ACCENT, button_hover_color=ACCENT,
            progress_color=ACCENT, fg_color=CARD,
            width=120,
            command=lambda v: self._mc_nsims_lbl.configure(text=f"{int(v)}"),
        ).pack(side="left", padx=(4, 2))
        self._mc_nsims_lbl.pack(side="left", padx=(0, 16))

        # Semanas (Slider 4–52)
        ctk.CTkLabel(
            ctrl_row, text="Semanas",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self._mc_weeks_var = tk.IntVar(value=26)
        self._mc_weeks_lbl = ctk.CTkLabel(
            ctrl_row, text="26",
            text_color="#f0fff4", font=ctk.CTkFont(size=11),
            width=30,
        )
        ctk.CTkSlider(
            ctrl_row, from_=4, to=52,
            number_of_steps=24, variable=self._mc_weeks_var,
            button_color=ACCENT, button_hover_color=ACCENT,
            progress_color=ACCENT, fg_color=CARD,
            width=120,
            command=lambda v: self._mc_weeks_lbl.configure(text=f"{int(v)}"),
        ).pack(side="left", padx=(4, 2))
        self._mc_weeks_lbl.pack(side="left", padx=(0, 16))

        # Picks/semana (Slider 2–10)
        ctk.CTkLabel(
            ctrl_row, text="Picks/sem.",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")
        self._mc_ppw_var = tk.IntVar(value=5)
        self._mc_ppw_lbl = ctk.CTkLabel(
            ctrl_row, text="5",
            text_color="#f0fff4", font=ctk.CTkFont(size=11),
            width=24,
        )
        ctk.CTkSlider(
            ctrl_row, from_=2, to=10,
            number_of_steps=8, variable=self._mc_ppw_var,
            button_color=ACCENT, button_hover_color=ACCENT,
            progress_color=ACCENT, fg_color=CARD,
            width=100,
            command=lambda v: self._mc_ppw_lbl.configure(text=f"{int(v)}"),
        ).pack(side="left", padx=(4, 2))
        self._mc_ppw_lbl.pack(side="left", padx=(0, 16))

        # Botón Simular
        self._mc_run_btn = ctk.CTkButton(
            ctrl_row, text="▶  Simular",
            command=self._run_montecarlo,
            fg_color=ACCENT, hover_color=ACCENT_2,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32, corner_radius=8, width=110,
        )
        self._mc_run_btn.pack(side="left", padx=(0, 0))

        # Indicador de estado (visible mientras corre)
        self._mc_status_lbl = ctk.CTkLabel(
            ctrl_row, text="",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._mc_status_lbl.pack(side="left", padx=10)

        # ── Área del gráfico ───────────────────────────────────────────────────
        if _MPL_OK:
            self._mc_fig, self._mc_ax = plt.subplots(figsize=(10, 4))
            self._mc_fig.patch.set_facecolor(_MC_BG)
            self._mc_ax.set_facecolor(_MC_BG)
            self._mc_canvas = FigureCanvasTkAgg(self._mc_fig, master=mc_frame)
            self._mc_canvas.get_tk_widget().pack(
                fill="x", padx=14, pady=(0, 6),
            )
            self._mc_draw_placeholder()
        else:
            ctk.CTkLabel(
                mc_frame,
                text="matplotlib no disponible — instala con: pip install matplotlib",
                text_color="#ef4444", font=ctk.CTkFont(size=11),
            ).pack(pady=12)

        # ── Grid de estadísticas ───────────────────────────────────────────────
        stats_frame = ctk.CTkFrame(mc_frame, fg_color="transparent")
        stats_frame.pack(fill="x", padx=14, pady=(0, 14))
        for col in range(3):
            stats_frame.grid_columnconfigure(col, weight=1)

        stat_defs = [
            ("mc_expected",    "E[Bankroll final]",     "—"),
            ("mc_roi",         "ROI mediano",            "—"),
            ("mc_ruin",        "P(Ruina)",               "—"),
            ("mc_dd20",        "P(Drawdown >20%)",       "—"),
            ("mc_dd50",        "P(Drawdown >50%)",       "—"),
            ("mc_max_dd",      "Drawdown máx. mediano",  "—"),
        ]
        self._mc_stat_lbls: dict[str, ctk.CTkLabel] = {}
        for i, (key, title, default) in enumerate(stat_defs):
            row_idx = i // 3
            col_idx = i %  3
            cell = ctk.CTkFrame(
                stats_frame, fg_color=CARD, corner_radius=8,
                border_color=BORDER, border_width=1,
            )
            cell.grid(
                row=row_idx, column=col_idx,
                sticky="ew", padx=(0 if col_idx == 0 else 4, 0),
                pady=(0 if row_idx == 0 else 4, 0),
            )
            ctk.CTkLabel(
                cell, text=title,
                text_color=MUTED, font=ctk.CTkFont(size=10),
            ).pack(anchor="w", padx=10, pady=(8, 2))
            val_lbl = ctk.CTkLabel(
                cell, text=default,
                text_color=ACCENT, font=ctk.CTkFont(size=16, weight="bold"),
            )
            val_lbl.pack(anchor="w", padx=10, pady=(0, 8))
            self._mc_stat_lbls[key] = val_lbl

    def _mc_draw_placeholder(self) -> None:
        """Dibuja el gráfico vacío con instrucciones."""
        if not _MPL_OK:
            return
        ax = self._mc_ax
        ax.clear()
        ax.set_facecolor(_MC_BG)
        ax.text(
            0.5, 0.5,
            "Pulsa ▶ Simular para proyectar el bankroll",
            transform=ax.transAxes,
            ha="center", va="center",
            color=MUTED, fontsize=12,
        )
        ax.set_xlabel("Semana", color=MUTED, fontsize=9)
        ax.set_ylabel("Bankroll (€)", color=MUTED, fontsize=9)
        ax.tick_params(colors=MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER)
        self._mc_fig.tight_layout()
        self._mc_canvas.draw_idle()

    def _run_montecarlo(self) -> None:
        """Lanza la simulación en un hilo para no bloquear la UI."""
        if not _MC_OK:
            messagebox.showerror(
                "Monte Carlo",
                "No se pudo importar core.montecarlo. Revisa la instalación.",
            )
            return

        # Parsear parámetros
        try:
            initial = float(self._mc_bankroll_var.get())
            if initial <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Monte Carlo", "Bankroll inicial inválido.")
            return

        n_sims  = int(self._mc_nsims_var.get())
        n_weeks = int(self._mc_weeks_var.get())
        ppw     = int(self._mc_ppw_var.get())

        picks = list(self._mc_picks) if self._mc_picks else []

        self._mc_run_btn.configure(state="disabled")
        self._mc_status_lbl.configure(text="Simulando…")

        def worker():
            try:
                result = simulate_bankroll(
                    picks=picks,
                    n_sims=n_sims,
                    n_weeks=n_weeks,
                    picks_per_week=ppw,
                    initial=initial,
                )
            except Exception as exc:
                self.after(0, lambda: self._mc_on_error(str(exc)))
                return
            self.after(0, lambda: self._mc_on_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _mc_on_error(self, msg: str) -> None:
        self._mc_run_btn.configure(state="normal")
        self._mc_status_lbl.configure(text="")
        messagebox.showerror("Monte Carlo", f"Error en simulación:\n{msg}")

    def _mc_on_result(self, result: dict) -> None:
        """Recibe el resultado del hilo y actualiza UI (se llama en el hilo principal)."""
        self._mc_run_btn.configure(state="normal")
        self._mc_status_lbl.configure(
            text=f"{result['n_sims']:,} sims · {result['n_weeks']} sem."
        )
        if _MPL_OK:
            self._mc_plot(result)
        self._mc_update_stats(result)

    def _mc_plot(self, r: dict) -> None:
        """Redibuja el gráfico de fanplot con los percentiles."""
        ax = self._mc_ax
        ax.clear()
        ax.set_facecolor(_MC_BG)

        weeks = r["weeks"]
        p10   = r["p10"]
        p25   = r["p25"]
        p50   = r["p50"]
        p75   = r["p75"]
        p90   = r["p90"]
        init  = r["initial"]

        # Banda p10-p90 (tenue)
        ax.fill_between(weeks, p10, p90, color=_MC_FILL_10, alpha=0.25,
                        label="P10–P90")
        # Banda p25-p75 (más opaca)
        ax.fill_between(weeks, p25, p75, color=_MC_FILL_25, alpha=0.40,
                        label="P25–P75")
        # Mediana
        ax.plot(weeks, p50, color=_MC_LINE, linewidth=2.2,
                label="Mediana (P50)")
        # Baseline
        ax.axhline(init, color=_MC_BASE, linewidth=1.0, linestyle="--",
                   alpha=0.7, label=f"Inicial {init:,.0f} €")

        # Estilo
        ax.set_title(
            f"Proyección bankroll — {r['n_sims']:,} simulaciones",
            color="#f0fff4", fontsize=11, pad=8,
        )
        ax.set_xlabel("Semana", color=MUTED, fontsize=9)
        ax.set_ylabel("Bankroll (€)", color=MUTED, fontsize=9)
        ax.tick_params(colors=MUTED, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(BORDER)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x:,.0f}")
        )

        ax.legend(
            fontsize=8, framealpha=0.25,
            facecolor=CARD, edgecolor=BORDER,
            labelcolor="#f0fff4",
        )

        self._mc_fig.tight_layout()
        self._mc_canvas.draw_idle()

    def _mc_update_stats(self, r: dict) -> None:
        """Actualiza las celdas de estadísticas con los resultados."""
        init = r["initial"]

        def _color(val: float, *, invert: bool = False) -> str:
            good = val >= 0 if not invert else val <= 0
            return ACCENT if good else "#ef4444"

        final   = r["expected_final"]
        roi     = r["roi_median"]
        p_ruin  = r["p_ruin"]
        dd20    = r["p_drawdown_20"]
        dd50    = r["p_drawdown_50"]
        max_dd  = r["max_drawdown_median"]

        self._mc_stat_lbls["mc_expected"].configure(
            text=f"{final:,.2f} €",
            text_color=_color(final - init),
        )
        self._mc_stat_lbls["mc_roi"].configure(
            text=f"{roi:+.1%}",
            text_color=_color(roi),
        )
        self._mc_stat_lbls["mc_ruin"].configure(
            text=f"{p_ruin:.1%}",
            text_color=("#ef4444" if p_ruin > 0.05 else ACCENT),
        )
        self._mc_stat_lbls["mc_dd20"].configure(
            text=f"{dd20:.1%}",
            text_color=("#ef4444" if dd20 > 0.40 else MUTED),
        )
        self._mc_stat_lbls["mc_dd50"].configure(
            text=f"{dd50:.1%}",
            text_color=("#ef4444" if dd50 > 0.15 else MUTED),
        )
        self._mc_stat_lbls["mc_max_dd"].configure(
            text=f"{max_dd:.1%}",
            text_color=("#ef4444" if max_dd > 0.40 else MUTED),
        )

    def refresh_montecarlo(self, picks: list[dict]) -> None:
        """
        Punto de entrada público para que app.py suministre picks reales.

        Parameters
        ----------
        picks : list[dict]
            Cada dict debe tener: 'ev', 'model_prob', 'odds', 'kelly_pct'.
        """
        self._mc_picks = list(picks) if picks else []


# ══════════════════════════════════════════════════════════════════════════════
# Execution / Simulator view
# ══════════════════════════════════════════════════════════════════════════════

class ExecutionView(ctk.CTkScrollableFrame):

    # Etiquetas legibles para cada mercado
    _PICK_LABELS: dict[str, str] = {
        "1":        "Victoria Local (1)",
        "X":        "Empate (X)",
        "2":        "Victoria Visitante (2)",
        "OVER2.5":  "Más de 2.5 goles",
        "UNDER2.5": "Menos de 2.5 goles",
    }

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        # (match_key, pick_key) → CTkButton
        self._odd_btns: dict[tuple[str, str], ctk.CTkButton] = {}
        # Legs actualmente en el boleto  {match_key, match_name, pick, odds}
        self._slip_legs: list[dict] = []
        self._build()

    def _build(self):
        self._build_slip()
        self._build_stats()
        self._build_combo_card()
        self._build_history()

    # ── Slip ───────────────────────────────────────────────────────────────────

    def _build_slip(self):
        sim = make_card(self, "Manual Slip",
                        "Selecciona un partido y mercado · Introduce stake · Guarda apuesta")
        sim.pack(fill="x", pady=(0, 10))

        container = ctk.CTkFrame(sim, fg_color="transparent")
        container.pack(fill="x", padx=12, pady=(0, 12))
        container.grid_columnconfigure(0, weight=3)
        container.grid_columnconfigure(1, weight=2)

        # ── Left: tablero de partidos ──────────────────────────────────────
        board_wrap = ctk.CTkFrame(container, fg_color="transparent")
        board_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        hdr_row = ctk.CTkFrame(board_wrap, fg_color="transparent")
        hdr_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            hdr_row, text="PARTIDOS DISPONIBLES",
            text_color=MUTED, font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(side="left")

        self._match_board = ctk.CTkScrollableFrame(
            board_wrap, fg_color="transparent", height=480,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT,
        )
        self._match_board.pack(fill="x")
        self._match_board.grid_columnconfigure(0, weight=1)

        # ── Right: bet slip ────────────────────────────────────────────────
        slip_panel = ctk.CTkFrame(
            container, fg_color=_BOARD_CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        slip_panel.grid(row=0, column=1, sticky="nsew")
        self._build_bet_slip_panel(slip_panel)

    def _build_bet_slip_panel(self, parent: ctk.CTkFrame) -> None:
        # ── Cabecera ────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(parent, fg_color=_BOARD_HDR, corner_radius=0)
        hdr.pack(fill="x")
        hdr_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_inner.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(
            hdr_inner, text="BET SLIP",
            text_color=ACCENT, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        self._legs_count_lbl = ctk.CTkLabel(
            hdr_inner, text="",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._legs_count_lbl.pack(side="right")

        # ── Lista dinámica de legs ──────────────────────────────────────────
        self._legs_area = ctk.CTkFrame(parent, fg_color="transparent")
        self._legs_area.pack(fill="x", padx=10, pady=(8, 4))

        # Placeholder inicial (se reemplaza por _refresh_slip_panel)
        ctk.CTkLabel(
            self._legs_area,
            text="Haz clic en una cuota\npara añadir al slip",
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="center",
        ).pack(pady=22)

        # ── Botón limpiar ───────────────────────────────────────────────────
        ctk.CTkButton(
            parent, text="🗑  Limpiar todo",
            command=self._clear_slip,
            fg_color="#2d0a0a", hover_color="#450f0f",
            font=ctk.CTkFont(size=11), height=28,
        ).pack(fill="x", padx=10, pady=(0, 6))

        # ── Separador ───────────────────────────────────────────────────────
        ctk.CTkFrame(parent, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 8))

        # ── Cuota total ─────────────────────────────────────────────────────
        self._total_odds_lbl = ctk.CTkLabel(
            parent, text="CUOTA TOTAL  —",
            text_color=ACCENT, font=ctk.CTkFont(size=15, weight="bold"),
        )
        self._total_odds_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Stake ───────────────────────────────────────────────────────────
        ctk.CTkLabel(parent, text="Stake (€)", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12)
        ctk.CTkEntry(
            parent, textvariable=self.app.manual_stake_var,
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            font=ctk.CTkFont(size=14),
        ).pack(fill="x", padx=10, pady=(4, 6))

        # ── Retorno potencial ───────────────────────────────────────────────
        self._slip_return_lbl = ctk.CTkLabel(
            parent, text="Retorno bruto:  —",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._slip_return_lbl.pack(anchor="w", padx=12, pady=(0, 2))
        self._slip_profit_lbl = ctk.CTkLabel(
            parent, text="Beneficio neto:  —",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._slip_profit_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # ── Separador ───────────────────────────────────────────────────────
        ctk.CTkFrame(parent, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 8))

        # ── Estado al guardar ───────────────────────────────────────────────
        ctk.CTkLabel(parent, text="Estado al guardar", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12)
        ctk.CTkComboBox(
            parent, variable=self.app.sim_result_var,
            values=["PENDING", "WIN", "LOSS"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
        ).pack(fill="x", padx=10, pady=(4, 8))

        # ── Guardar ─────────────────────────────────────────────────────────
        ctk.CTkButton(
            parent, text="Guardar boleto",
            command=self.app.save_bet_simulation,
            fg_color=ACCENT, hover_color=ACCENT_2,
            font=ctk.CTkFont(size=13, weight="bold"), height=38,
        ).pack(fill="x", padx=10, pady=(0, 6))

        # ── Detalle/análisis ─────────────────────────────────────────────────
        self.sim_detail = make_textbox(parent, height=72)
        self.sim_detail.pack(fill="x", padx=10, pady=(0, 8))

        # Live update del retorno
        self.app.manual_stake_var.trace_add(
            "write", lambda *_: self.app.after(50, self._update_slip_return)
        )
        self.app.manual_odds_var.trace_add(
            "write", lambda *_: self.app.after(50, self._update_slip_return)
        )

    # ── Slip: toggle add / remove ─────────────────────────────────────────────

    def _select_odds(self, match_key: str, pick: str, odds: float) -> None:
        """Click en cuota: añade/quita del boleto multi-leg (toggle)."""
        key = (match_key, pick)

        # ¿Ya existe este leg exacto? → quitar (toggle off)
        same_idx = next(
            (i for i, l in enumerate(self._slip_legs)
             if l["match_key"] == match_key and l["pick"] == pick),
            None,
        )
        if same_idx is not None:
            self._remove_leg(same_idx)
            return

        # ¿Hay una cuota diferente del mismo partido? → reemplazar
        match_idx = next(
            (i for i, l in enumerate(self._slip_legs) if l["match_key"] == match_key),
            None,
        )
        if match_idx is not None:
            old = self._slip_legs[match_idx]
            old_btn = self._odd_btns.get((old["match_key"], old["pick"]))
            if old_btn:
                try:
                    old_btn.configure(
                        fg_color=_BTN_NORMAL, border_color="#2a5a32", text_color=TEXT,
                    )
                except Exception:
                    pass
            self._slip_legs[match_idx] = self._leg_dict(match_key, pick, odds)
        else:
            # Añadir nuevo leg
            self._slip_legs.append(self._leg_dict(match_key, pick, odds))

        # Resaltar botón nuevo
        btn = self._odd_btns.get(key)
        if btn:
            try:
                btn.configure(
                    fg_color=_BTN_SELECTED, border_color=_BTN_SELECTED,
                    text_color=_BTN_SEL_TEXT,
                )
            except Exception:
                pass

        # Sincronizar vars de app (compat con auto_fill_sim_odds)
        self.app.sim_match_var.set(match_key)
        self.app.manual_pick_var.set(pick)
        self._refresh_slip_panel()

    def _leg_dict(self, match_key: str, pick: str, odds: float) -> dict:
        parts = match_key.split(" | ")
        return {
            "match_key":  match_key,
            "match_name": parts[2] if len(parts) >= 3 else match_key,
            "pick":       pick,
            "odds":       odds,
        }

    def _remove_leg(self, idx: int) -> None:
        if not (0 <= idx < len(self._slip_legs)):
            return
        leg = self._slip_legs.pop(idx)
        btn = self._odd_btns.get((leg["match_key"], leg["pick"]))
        if btn:
            try:
                btn.configure(
                    fg_color=_BTN_NORMAL, border_color="#2a5a32", text_color=TEXT,
                )
            except Exception:
                pass
        self._refresh_slip_panel()

    def _clear_slip(self) -> None:
        for leg in self._slip_legs:
            btn = self._odd_btns.get((leg["match_key"], leg["pick"]))
            if btn:
                try:
                    btn.configure(
                        fg_color=_BTN_NORMAL, border_color="#2a5a32", text_color=TEXT,
                    )
                except Exception:
                    pass
        self._slip_legs.clear()
        self._refresh_slip_panel()

    def _refresh_slip_panel(self) -> None:
        """Reconstruye la lista de legs y actualiza cuota total + retorno."""
        for w in self._legs_area.winfo_children():
            w.destroy()

        if not self._slip_legs:
            ctk.CTkLabel(
                self._legs_area,
                text="Haz clic en una cuota\npara añadir al slip",
                text_color=MUTED, font=ctk.CTkFont(size=11), justify="center",
            ).pack(pady=22)
            self._legs_count_lbl.configure(text="")
            self._total_odds_lbl.configure(text="CUOTA TOTAL  —")
            self._slip_return_lbl.configure(text="Retorno bruto:  —", text_color=MUTED)
            self._slip_profit_lbl.configure(text="Beneficio neto:  —", text_color=MUTED)
            self.app.manual_odds_var.set("0.00")
            return

        for i, leg in enumerate(self._slip_legs):
            leg_card = ctk.CTkFrame(self._legs_area, fg_color=_BOARD_HDR, corner_radius=6)
            leg_card.pack(fill="x", pady=(0, 4))

            # Nombre del partido
            ctk.CTkLabel(
                leg_card, text=leg["match_name"],
                text_color=TEXT, font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w", wraplength=160,
            ).pack(anchor="w", padx=8, pady=(5, 1))

            # Pick + cuota + botón ✕
            row = ctk.CTkFrame(leg_card, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=(1, 5))

            pl = self._PICK_LABELS.get(leg["pick"], leg["pick"])
            ctk.CTkLabel(
                row, text=pl,
                text_color=MUTED, font=ctk.CTkFont(size=10),
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=f"  @{leg['odds']:.2f}",
                text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left")
            ctk.CTkButton(
                row, text="✕", width=24, height=24, corner_radius=4,
                fg_color="#3a0a0a", hover_color="#5a1010",
                text_color="#ffaaaa", font=ctk.CTkFont(size=11),
                command=lambda idx=i: self._remove_leg(idx),
            ).pack(side="right")

        # Totales
        n = len(self._slip_legs)
        total_odds = 1.0
        for leg in self._slip_legs:
            total_odds *= leg["odds"]

        suffix = "es" if n != 1 else ""
        self._legs_count_lbl.configure(text=f"{n} selección{suffix}")
        self._total_odds_lbl.configure(text=f"CUOTA TOTAL  {total_odds:.2f}")
        self.app.manual_odds_var.set(f"{total_odds:.4f}")
        self._update_slip_return()

        # Actualizar cuadro de detalle con resumen del boleto
        lines = [
            f"{'Acumulador' if n > 1 else 'Apuesta simple'}  ·  {n} leg{'s' if n > 1 else ''}",
            f"Cuota total: {total_odds:.2f}",
            "─" * 32,
        ]
        for i, leg in enumerate(self._slip_legs, 1):
            pl = self._PICK_LABELS.get(leg["pick"], leg["pick"])
            lines.append(f"{i}. {leg['match_name']}")
            lines.append(f"   {pl} @ {leg['odds']:.2f}")
        try:
            textbox_set(self.sim_detail, "\n".join(lines))
        except Exception:
            pass

    def _update_slip_return(self) -> None:
        try:
            odds  = float(self.app.manual_odds_var.get())
            stake = float(self.app.manual_stake_var.get())
        except (ValueError, tk.TclError):
            return
        if odds > 1 and stake > 0:
            ret    = round(stake * odds, 2)
            profit = round((odds - 1) * stake, 2)
            self._slip_return_lbl.configure(
                text=f"Retorno bruto:   {ret:.2f} €", text_color=TEXT,
            )
            self._slip_profit_lbl.configure(
                text=f"Beneficio neto:  +{profit:.2f} €", text_color=ACCENT,
            )

    # ── Diálogo de liquidación con auto-detección por marcador ────────────────

    @staticmethod
    def _check_pick_result(pick: str, h: int, a: int) -> str:
        """Devuelve WIN o LOSS en función del resultado y el mercado."""
        total = h + a
        if pick == "1":        return "WIN" if h > a  else "LOSS"
        if pick == "X":        return "WIN" if h == a else "LOSS"
        if pick == "2":        return "WIN" if h < a  else "LOSS"
        if pick == "OVER2.5":  return "WIN" if total > 2  else "LOSS"
        if pick == "UNDER2.5": return "WIN" if total <= 2 else "LOSS"
        return "PENDING"

    def _show_settlement_dialog(self, slip: dict, db_id: int) -> None:
        """Diálogo para liquidar un acumulador introduciendo el marcador de cada partido."""
        legs = slip.get("legs", [])
        if not legs:
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title("Liquidar boleto acumulador")
        dlg.geometry(f"480x{min(720, 160 + len(legs) * 110)}")
        dlg.configure(fg_color="#050e1c")
        dlg.grab_set()
        dlg.resizable(False, False)

        ctk.CTkLabel(
            dlg, text="Liquidar boleto",
            text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(padx=20, pady=(16, 2))
        ctk.CTkLabel(
            dlg, text="Introduce el marcador final de cada partido",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(pady=(0, 10))

        score_vars:   list[tuple[tk.StringVar, tk.StringVar]] = []
        result_lbls:  list[ctk.CTkLabel]                      = []

        # ── Fila por leg ────────────────────────────────────────────────────
        for i, leg in enumerate(legs):
            frame = ctk.CTkFrame(dlg, fg_color=_BOARD_HDR, corner_radius=8)
            frame.pack(fill="x", padx=20, pady=4)

            top_row = ctk.CTkFrame(frame, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(8, 2))
            ctk.CTkLabel(
                top_row, text=leg.get("match", ""),
                text_color=TEXT, font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="left")
            ctk.CTkLabel(
                top_row,
                text=f"{self._PICK_LABELS.get(leg['pick'], leg['pick'])}  @{leg['odds']:.2f}",
                text_color=MUTED, font=ctk.CTkFont(size=10),
            ).pack(side="right")

            score_row = ctk.CTkFrame(frame, fg_color="transparent")
            score_row.pack(fill="x", padx=10, pady=(4, 10))

            hv = tk.StringVar()
            av = tk.StringVar()
            score_vars.append((hv, av))

            ctk.CTkEntry(
                score_row, textvariable=hv, width=58,
                placeholder_text="Local",
                fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
                font=ctk.CTkFont(size=14),
            ).pack(side="left")
            ctk.CTkLabel(
                score_row, text="  —  ",
                text_color=MUTED, font=ctk.CTkFont(size=14),
            ).pack(side="left")
            ctk.CTkEntry(
                score_row, textvariable=av, width=58,
                placeholder_text="Visit.",
                fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
                font=ctk.CTkFont(size=14),
            ).pack(side="left")

            res_lbl = ctk.CTkLabel(
                score_row, text="—",
                text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"),
            )
            res_lbl.pack(side="right", padx=8)
            result_lbls.append(res_lbl)

        # ── Resultado global ────────────────────────────────────────────────
        bottom = ctk.CTkFrame(dlg, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=12)

        overall_lbl = ctk.CTkLabel(
            bottom, text="— Introduce todos los marcadores —",
            text_color=MUTED, font=ctk.CTkFont(size=13, weight="bold"),
        )
        overall_lbl.pack(pady=(0, 8))

        confirm_btn = ctk.CTkButton(
            bottom, text="Confirmar liquidación",
            state="disabled",
            fg_color=ACCENT, hover_color=ACCENT_2,
            font=ctk.CTkFont(size=13, weight="bold"), height=38,
        )
        confirm_btn.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            bottom, text="Cancelar", command=dlg.destroy,
            fg_color="#2d0a0a", hover_color="#450f0f",
        ).pack(fill="x")

        # ── Lógica de actualización ─────────────────────────────────────────
        def _recalc(_event=None) -> None:
            results: list[str | None] = []
            for idx, (hv, av) in enumerate(score_vars):
                try:
                    h = int(hv.get())
                    a = int(av.get())
                    r = self._check_pick_result(legs[idx]["pick"], h, a)
                    results.append(r)
                    lbl = result_lbls[idx]
                    if r == "WIN":
                        lbl.configure(text="✅ Ganado", text_color="#22c55e")
                    else:
                        lbl.configure(text="❌ Perdido", text_color="#ef4444")
                except (ValueError, IndexError):
                    result_lbls[idx].configure(text="—", text_color=MUTED)
                    results.append(None)

            if None in results:
                overall_lbl.configure(
                    text="— Introduce todos los marcadores —", text_color=MUTED,
                )
                confirm_btn.configure(state="disabled")
            elif all(r == "WIN" for r in results):
                overall_lbl.configure(text="✅  BOLETO GANADOR", text_color="#22c55e")
                confirm_btn.configure(state="normal")
            else:
                overall_lbl.configure(text="❌  BOLETO PERDEDOR", text_color="#ef4444")
                confirm_btn.configure(state="normal")

        # Trace para actualización en tiempo real
        for hv, av in score_vars:
            hv.trace_add("write", lambda *_: dlg.after(50, _recalc))
            av.trace_add("write", lambda *_: dlg.after(50, _recalc))

        def _confirm() -> None:
            results = []
            for idx, (hv, av) in enumerate(score_vars):
                h = int(hv.get())
                a = int(av.get())
                results.append(self._check_pick_result(legs[idx]["pick"], h, a))

            overall = "WIN" if all(r == "WIN" for r in results) else "LOSS"
            stake      = float(slip.get("stake", 0))
            total_odds = float(slip.get("total_odds", 0))
            pnl = (
                round((total_odds - 1) * stake, 2)
                if overall == "WIN"
                else round(-stake, 2)
            )

            # Actualizar legs individuales
            for idx, leg in enumerate(legs):
                leg["status"] = results[idx]

            slip["status"]     = overall
            slip["pnl"]        = pnl
            slip["settled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            self.app.storage.update_sim_full(db_id, slip)

            # Actualizar memoria
            for sim in self.app.bet_sim_history:
                if sim.get("_db_id") == db_id:
                    sim.update(slip)
                    break

            self.refresh_history_panel(self.app.bet_sim_history)
            self.refresh_stats(self.app.bet_sim_history)

            emoji = "✅" if overall == "WIN" else "❌"
            self.settle_lbl.configure(
                text=f"{emoji}  Acumulador {overall}  (PnL {pnl:+.2f} €)"
            )
            dlg.destroy()
            messagebox.showinfo(
                "Liquidación",
                f"Boleto {emoji} {'GANADOR' if overall == 'WIN' else 'PERDEDOR'}\n"
                f"PnL: {pnl:+.2f} €",
            )

        confirm_btn.configure(command=_confirm)

    # ── Match board ───────────────────────────────────────────────────────────

    def _make_match_card(self, parent, match: dict) -> None:
        """Crea una tarjeta de partido estilo casa de apuestas."""
        risk        = match.get("risk_light", "ROJO")
        risk_color  = _RISK_COLORS.get(risk, "#6b7280")
        model_pick  = match.get("pick", "NO BET")

        outer = ctk.CTkFrame(
            parent, fg_color=_BOARD_CARD, corner_radius=8,
            border_color="#1a3d22", border_width=1,
        )
        outer.pack(fill="x", pady=(0, 6), padx=2)

        # ── Cabecera: liga + fecha + pick IA ──────────────────────────────
        hdr = ctk.CTkFrame(outer, fg_color=_BOARD_HDR, corner_radius=0)
        hdr.pack(fill="x")

        ctk.CTkLabel(
            hdr, text="●", text_color=risk_color,
            font=ctk.CTkFont(size=9),
        ).pack(side="left", padx=(8, 4), pady=4)
        ctk.CTkLabel(
            hdr, text=match.get("league", ""),
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(side="left", pady=4)

        date_str = str(match.get("date", ""))[:10]
        ctk.CTkLabel(
            hdr, text=date_str,
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).pack(side="right", padx=8, pady=4)

        if model_pick and model_pick != "NO BET":
            ctk.CTkLabel(
                hdr, text=f"IA {model_pick}",
                text_color=risk_color,
                font=ctk.CTkFont(size=10, weight="bold"),
            ).pack(side="right", padx=(0, 6), pady=4)

        # ── Equipos ────────────────────────────────────────────────────────
        teams = ctk.CTkFrame(outer, fg_color="transparent")
        teams.pack(fill="x", padx=10, pady=(7, 4))
        teams.grid_columnconfigure(0, weight=1)
        teams.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            teams, text=match.get("home_team", ""),
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
            anchor="e",
        ).grid(row=0, column=0, sticky="e")
        ctk.CTkLabel(
            teams, text="vs",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        ).grid(row=0, column=1, padx=10)
        ctk.CTkLabel(
            teams, text=match.get("away_team", ""),
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).grid(row=0, column=2, sticky="w")

        # ── Botones de cuotas ──────────────────────────────────────────────
        match_key = (
            f"{match.get('date','')} | {match.get('league','')} | "
            f"{match.get('home_team','')} vs {match.get('away_team','')}"
        )

        markets_1x2 = [
            ("1",     "1",        match.get("B365H")),
            ("X",     "X",        match.get("B365D")),
            ("2",     "2",        match.get("B365A")),
        ]
        markets_ou = [
            ("O 2.5", "OVER2.5",  match.get("B365O25")),
            ("U 2.5", "UNDER2.5", match.get("B365U25")),
        ]

        for row_markets in (markets_1x2, markets_ou):
            row = ctk.CTkFrame(outer, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=(2, 0))
            for label, pick_key, odds_val in row_markets:
                col = ctk.CTkFrame(row, fg_color="transparent")
                col.pack(side="left", expand=True, fill="x", padx=3)

                ctk.CTkLabel(
                    col, text=label,
                    text_color=MUTED, font=ctk.CTkFont(size=9),
                ).pack()

                valid = False
                if odds_val is not None:
                    try:
                        odds_f = float(odds_val)
                        if not pd.isna(odds_f) and odds_f > 1.0:
                            valid = True
                    except (TypeError, ValueError):
                        pass

                if valid:
                    btn = ctk.CTkButton(
                        col,
                        text=f"{odds_f:.2f}",
                        fg_color=_BTN_NORMAL,
                        hover_color=_BTN_HOVER,
                        border_color="#2a5a32",
                        border_width=1,
                        text_color=TEXT,
                        font=ctk.CTkFont(size=12, weight="bold"),
                        height=34, corner_radius=6,
                        command=lambda mk=match_key, pk=pick_key, ov=odds_f:
                            self._select_odds(mk, pk, ov),
                    )
                    btn.pack(fill="x")
                    self._odd_btns[(match_key, pick_key)] = btn
                else:
                    ctk.CTkLabel(
                        col, text="—",
                        text_color="#3a5a44", font=ctk.CTkFont(size=12),
                    ).pack(pady=4)

        # Espacio inferior
        ctk.CTkFrame(outer, fg_color="transparent", height=4).pack()

    # ── Stats ──────────────────────────────────────────────────────────────────

    def _build_stats(self):
        stats = make_card(self, "Estadísticas de simulación")
        stats.pack(fill="x", pady=(0, 10))
        self.sim_stats = make_textbox(stats, height=110)
        self.sim_stats.pack(fill="x", padx=12, pady=(0, 12))

    # ── Combo builder ──────────────────────────────────────────────────────────

    def _build_combo_card(self):
        builder = make_card(self, "Combo Builder")
        builder.pack(fill="x", pady=(0, 10))
        self.combo_text = make_textbox(builder, height=150)
        self.combo_text.pack(fill="x", padx=12, pady=(0, 12))

    # ── Historial persistente con Treeview ────────────────────────────────────

    def _build_history(self):
        hist = make_card(
            self, "Historial de apuestas",
            "Singles y acumuladores · WIN/LOSS para singles · Liquidar para acumuladores",
        )
        hist.pack(fill="x", pady=(0, 10))

        # Treeview
        shell = ctk.CTkFrame(hist, fg_color="#060f07")
        shell.pack(fill="x", padx=12, pady=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("timestamp", "tipo", "match", "odds", "stake", "retorno", "status", "pnl")
        self.sim_tree = ttk.Treeview(shell, columns=cols, show="headings", height=8)

        widths = {
            "timestamp": 130, "tipo": 70, "match": 220, "odds": 64,
            "stake": 70, "retorno": 80, "status": 80, "pnl": 80,
        }
        labels = {
            "timestamp": "Fecha", "tipo": "Tipo", "match": "Partido / Mercado",
            "odds": "Cuota", "stake": "Stake €", "retorno": "Retorno €",
            "status": "Estado", "pnl": "PnL €",
        }
        for col in cols:
            self.sim_tree.heading(col, text=labels[col])
            self.sim_tree.column(col, width=widths[col], anchor="center")

        self.sim_tree.tag_configure("win",     background="#0e2d1d", foreground="#d6ffe6")
        self.sim_tree.tag_configure("loss",    background="#341313", foreground="#ffd3d3")
        self.sim_tree.tag_configure("pending", background="#050e1c", foreground="#dbe7f8")
        self.sim_tree.tag_configure("acum",    background="#0a1a2e", foreground="#c8d8ff")

        self.sim_tree.grid(row=0, column=0, sticky="nsew")
        sb_tree = ttk.Scrollbar(shell, orient="vertical", command=self.sim_tree.yview)
        self.sim_tree.configure(yscrollcommand=sb_tree.set)
        sb_tree.grid(row=0, column=1, sticky="ns")

        # ── Panel de detalle de legs (visible al seleccionar acumulador) ────
        self._legs_detail_box = make_textbox(hist, height=72)
        self._legs_detail_box.pack(fill="x", padx=12, pady=(0, 6))
        textbox_set(self._legs_detail_box, "Selecciona un acumulador para ver sus legs.")

        # Binding de selección
        self.sim_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Botones de liquidación
        act_row = ctk.CTkFrame(hist, fg_color="transparent")
        act_row.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkButton(
            act_row, text="✓  WIN",
            command=lambda: self.app.settle_sim_selected("WIN"),
            fg_color="#166534", hover_color="#14532d", width=90, corner_radius=10,
        ).pack(side="left")
        ctk.CTkButton(
            act_row, text="✗  LOSS",
            command=lambda: self.app.settle_sim_selected("LOSS"),
            fg_color="#991b1b", hover_color="#7f1d1d", width=90, corner_radius=10,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            act_row, text="⚡ Liquidar acumulador",
            command=self._settle_acum_selected,
            fg_color="#1e3a5f", hover_color="#2a4f7f", corner_radius=10,
        ).pack(side="left", padx=8)

        self.settle_lbl = ctk.CTkLabel(
            act_row, text="Selecciona una fila para liquidar",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self.settle_lbl.pack(side="left", padx=8)

    def _on_tree_select(self, _event=None) -> None:
        """Muestra el detalle de legs cuando se selecciona un acumulador."""
        sel = self.sim_tree.selection()
        if not sel:
            return
        try:
            db_id = int(sel[0])
        except ValueError:
            return
        sim = next((s for s in self.app.bet_sim_history if s.get("_db_id") == db_id), None)
        if sim is None:
            return

        if sim.get("type") == "accumulator":
            legs = sim.get("legs", [])
            lines = [f"Acumulador · {len(legs)} legs · cuota {sim.get('total_odds', 0):.2f}"]
            for i, leg in enumerate(legs, 1):
                st = leg.get("status", "PENDING")
                icon = "✅" if st == "WIN" else "❌" if st == "LOSS" else "⏳"
                lines.append(
                    f"  {i}. {icon} {leg.get('match','')}  |  "
                    f"{self._PICK_LABELS.get(leg.get('pick',''), leg.get('pick',''))} "
                    f"@ {leg.get('odds', 0):.2f}"
                )
            textbox_set(self._legs_detail_box, "\n".join(lines))
            self.settle_lbl.configure(
                text="Acumulador — usa ⚡ Liquidar para introducir marcadores",
                text_color="#818cf8",
            )
        else:
            textbox_set(
                self._legs_detail_box,
                f"Single  |  {sim.get('match','')}  |  "
                f"{self._PICK_LABELS.get(sim.get('pick',''), sim.get('pick',''))} "
                f"@ {sim.get('odds', 0):.2f}",
            )
            self.settle_lbl.configure(
                text="Single — marca WIN o LOSS directamente", text_color=MUTED,
            )

    def _settle_acum_selected(self) -> None:
        """Abre el diálogo de liquidación para el acumulador seleccionado."""
        sel = self.sim_tree.selection()
        if not sel:
            messagebox.showwarning("Historial", "Selecciona un acumulador.")
            return
        try:
            db_id = int(sel[0])
        except ValueError:
            return
        sim = next((s for s in self.app.bet_sim_history if s.get("_db_id") == db_id), None)
        if sim is None:
            return
        if sim.get("type") != "accumulator":
            messagebox.showinfo("Historial", "Esta fila es una apuesta simple. Usa WIN / LOSS.")
            return
        if sim.get("status") != "PENDING":
            messagebox.showinfo("Historial", f"Ya liquidada como {sim['status']}.")
            return
        self._show_settlement_dialog(sim, db_id)

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_match_list(self, matches: list[dict]) -> None:
        """Reconstruye el tablero de partidos estilo casa de apuestas."""
        for widget in self._match_board.winfo_children():
            widget.destroy()
        self._odd_btns.clear()
        # Limpiar el slip al actualizar partidos
        self._slip_legs.clear()
        self._refresh_slip_panel()

        if not matches:
            ctk.CTkLabel(
                self._match_board,
                text="Sin partidos disponibles.\nEjecuta el análisis primero.",
                text_color=MUTED, font=ctk.CTkFont(size=12), justify="center",
            ).pack(pady=40)
            return

        for match in matches:
            self._make_match_card(self._match_board, match)

    def refresh_stats(self, history: list[dict]) -> None:
        settled = [x for x in history if x.get("status") in ("WIN", "LOSS")]
        if not settled:
            textbox_set(self.sim_stats, "Sin apuestas liquidadas todavía.")
            return
        total_stake = sum(float(x.get("stake", 0)) for x in settled)
        total_pnl   = sum(float(x.get("pnl",   0)) for x in settled)
        wins   = sum(1 for x in settled if x.get("status") == "WIN")
        losses = sum(1 for x in settled if x.get("status") == "LOSS")
        roi    = (total_pnl / total_stake * 100) if total_stake else 0.0
        hit    = (wins / len(settled) * 100)     if settled     else 0.0
        textbox_set(
            self.sim_stats,
            f"Apuestas liquidadas : {len(settled)}\n"
            f"WIN / LOSS          : {wins} / {losses}\n"
            f"Stake total         : {total_stake:.2f} €\n"
            f"PnL total           : {total_pnl:+.2f} €\n"
            f"ROI                 : {roi:+.2f}%\n"
            f"Hit rate            : {hit:.1f}%",
        )

    def refresh_history_panel(self, history: list[dict]) -> None:
        """Rellena el Treeview con el historial (singles y acumuladores)."""
        for row in self.sim_tree.get_children():
            self.sim_tree.delete(row)

        for item in history:
            status    = item.get("status", "PENDING")
            stake     = float(item.get("stake", 0) or 0)
            pnl       = float(item.get("pnl",   0) or 0)
            pnl_str   = f"{pnl:+.2f}" if status != "PENDING" else "—"
            slip_type = item.get("type", "single")

            if slip_type == "accumulator":
                legs       = item.get("legs", [])
                total_odds = float(item.get("total_odds", 0) or 0)
                ret        = round(stake * total_odds, 2) if total_odds > 1 else 0.0
                n          = len(legs)
                # Resumen compacto de las primeras 2-3 legs
                leg_summary = "  +  ".join(
                    f"{l.get('pick','')}@{float(l.get('odds',0)):.2f}"
                    for l in legs[:3]
                )
                if n > 3:
                    leg_summary += f" +{n-3}…"
                match_str  = f"[ACUM {n}L]  {leg_summary}"
                tag = (
                    "win"     if status == "WIN"
                    else "loss"    if status == "LOSS"
                    else "acum"
                )
                self.sim_tree.insert("", "end", tags=(tag,), values=(
                    item.get("timestamp", "")[:16],
                    "ACUM",
                    match_str,
                    f"{total_odds:.2f}",
                    f"{stake:.2f}",
                    f"{ret:.2f}",
                    status,
                    pnl_str,
                ), iid=str(item.get("_db_id", id(item))))
            else:
                # Single bet
                odds = float(item.get("odds", 0) or 0)
                ret  = round(stake * odds, 2) if odds > 1 else 0.0
                tag  = "win" if status == "WIN" else "loss" if status == "LOSS" else "pending"
                pick = item.get("pick", "")
                pick_lbl = self._PICK_LABELS.get(pick, pick)
                match_str = f"{item.get('match', '')}  [{pick_lbl}]"
                self.sim_tree.insert("", "end", tags=(tag,), values=(
                    item.get("timestamp", "")[:16],
                    "SINGLE",
                    match_str,
                    f"{odds:.2f}",
                    f"{stake:.2f}",
                    f"{ret:.2f}",
                    status,
                    pnl_str,
                ), iid=str(item.get("_db_id", id(item))))
