"""
ui/views/portfolio.py — Vista Portfolio: historial de combinadas y ROI acumulado.
ui/views/execution.py — Vista Execution: simulador manual y bet builder.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk

import customtkinter as ctk
import pandas as pd
from tkinter import messagebox

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD_2, MUTED, TEXT
from ..widgets import make_card, make_textbox, textbox_set


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio view
# ══════════════════════════════════════════════════════════════════════════════

class PortfolioView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()

    def _build(self):
        card = make_card(self, "Portfolio Command")
        card.pack(fill="both", expand=True)

        self.roi_box = make_textbox(card, height=100)
        self.roi_box.pack(fill="x", padx=12, pady=(0, 8))

        self.history_box = make_textbox(card, height=260)
        self.history_box.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        acts = ctk.CTkFrame(card, fg_color="transparent")
        acts.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkButton(
            acts, text="WIN",
            command=lambda: self.app.settle_last("WIN"),
            fg_color="#166534", width=74, corner_radius=12,
        ).pack(side="left")

        ctk.CTkButton(
            acts, text="LOSS",
            command=lambda: self.app.settle_last("LOSS"),
            fg_color="#991b1b", width=74, corner_radius=12,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            acts, text="SEND",
            command=self.app.send_combo,
            fg_color=ACCENT, width=86, corner_radius=12,
        ).pack(side="right")

    def refresh_roi(self, agg: dict) -> None:
        textbox_set(
            self.roi_box,
            f"Combinadas resueltas: {agg['count']}\n"
            f"WIN / LOSS: {agg['wins']} / {agg['losses']}\n"
            f"Stake total: {agg['stake']:.2f}\n"
            f"Profit total: {agg['profit']:.2f}\n"
            f"ROI acumulado: {agg['roi']:.2f}%",
        )

    def refresh_history(self, history: list[dict]) -> None:
        if not history:
            textbox_set(self.history_box, "Todavía no hay combinadas registradas.")
            return
        lines = []
        for item in history[:25]:
            lines.append(
                f"[{item['timestamp']}] {item['size']} legs | "
                f"cuota {item['total_odds']:.2f} | "
                f"estado: {item.get('status','PENDING')} | "
                f"profit: {float(item.get('profit',0)):.2f} | "
                f"ROI: {float(item.get('roi',0)):.2f}%"
            )
            for leg in item["legs"]:
                lines.append(f"  - {leg['match']} | {leg['pick']} @ {leg['odds']:.2f}")
            lines.append("")
        textbox_set(self.history_box, "\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# Execution / Simulator view
# ══════════════════════════════════════════════════════════════════════════════

class ExecutionView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()

    def _build(self):
        self._build_slip()
        self._build_stats()
        self._build_combo_card()
        self._build_history()

    # ── Slip ───────────────────────────────────────────────────────────────────

    def _build_slip(self):
        sim = make_card(self, "Manual Slip",
                        "Partido · Mercado · Cuota auto-rellenada · Stake")
        sim.pack(fill="x", pady=(0, 10))

        sb = ctk.CTkFrame(sim, fg_color="transparent")
        sb.pack(fill="x", padx=12, pady=(0, 12))

        # Partido
        ctk.CTkLabel(sb, text="Partido", text_color=MUTED).pack(anchor="w")
        self.app.sim_match_var = tk.StringVar(value="Sin resultados todavía")
        self.match_menu = ctk.CTkComboBox(
            sb, variable=self.app.sim_match_var,
            values=["Sin resultados todavía"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
            command=lambda _: self.app.auto_fill_sim_odds(),
        )
        self.match_menu.pack(fill="x", pady=(4, 10))

        # Mercado (ampliado a 5 opciones)
        ctk.CTkLabel(sb, text="Mercado", text_color=MUTED).pack(anchor="w")
        self.app.manual_pick_var = tk.StringVar(value="1")
        ctk.CTkComboBox(
            sb, variable=self.app.manual_pick_var,
            values=["1", "X", "2", "OVER2.5", "UNDER2.5"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
            command=lambda _: self.app.auto_fill_sim_odds(),
        ).pack(fill="x", pady=(4, 10))

        # Cuota (auto-rellenada)
        cuota_row = ctk.CTkFrame(sb, fg_color="transparent")
        cuota_row.pack(fill="x", pady=(0, 2))
        cuota_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(cuota_row, text="Cuota", text_color=MUTED).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(cuota_row, text="(auto)", text_color="#3b82f6",
                     font=ctk.CTkFont(size=10)).grid(row=0, column=1, sticky="e")
        ctk.CTkEntry(
            sb, textvariable=self.app.manual_odds_var,
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
        ).pack(fill="x", pady=(0, 10))

        # Stake
        ctk.CTkLabel(sb, text="Stake (€)", text_color=MUTED).pack(anchor="w")
        ctk.CTkEntry(
            sb, textvariable=self.app.manual_stake_var,
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
        ).pack(fill="x", pady=(4, 10))

        # Estado inicial
        ctk.CTkLabel(sb, text="Estado al guardar", text_color=MUTED).pack(anchor="w")
        self.app.sim_result_var = tk.StringVar(value="PENDING")
        ctk.CTkComboBox(
            sb, variable=self.app.sim_result_var,
            values=["PENDING", "WIN", "LOSS"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
        ).pack(fill="x", pady=(4, 10))

        btn_row = ctk.CTkFrame(sb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(
            btn_row, text="Calcular retorno",
            command=self.app.update_manual_quote_preview,
            fg_color="#25406b",
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar apuesta",
            command=self.app.save_bet_simulation,
            fg_color=ACCENT,
        ).pack(side="left", padx=8)

        self.sim_detail = make_textbox(sim, height=80)
        self.sim_detail.pack(fill="x", padx=12, pady=(8, 12))

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
        hist = make_card(self, "Historial de apuestas",
                         "Persistente · Selecciona una fila y marca WIN / LOSS")
        hist.pack(fill="x", pady=(0, 10))

        # Treeview
        shell = ctk.CTkFrame(hist, fg_color="#08101a")
        shell.pack(fill="x", padx=12, pady=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("timestamp", "match", "pick", "odds", "stake", "retorno", "status", "pnl")
        self.sim_tree = ttk.Treeview(shell, columns=cols, show="headings", height=8)

        widths = {
            "timestamp": 130, "match": 200, "pick": 80, "odds": 60,
            "stake": 70, "retorno": 80, "status": 80, "pnl": 80,
        }
        labels = {
            "timestamp": "Fecha", "match": "Partido", "pick": "Mercado",
            "odds": "Cuota", "stake": "Stake €", "retorno": "Retorno €",
            "status": "Estado", "pnl": "PnL €",
        }
        for col in cols:
            self.sim_tree.heading(col, text=labels[col])
            self.sim_tree.column(col, width=widths[col], anchor="center")

        self.sim_tree.tag_configure("win",     background="#0e2d1d", foreground="#d6ffe6")
        self.sim_tree.tag_configure("loss",    background="#341313", foreground="#ffd3d3")
        self.sim_tree.tag_configure("pending", background="#1a1f2e", foreground="#dbe7f8")

        self.sim_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(shell, orient="vertical", command=self.sim_tree.yview)
        self.sim_tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

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

        self.settle_lbl = ctk.CTkLabel(
            act_row, text="Selecciona una fila para liquidar",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self.settle_lbl.pack(side="left", padx=8)

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_match_list(self, labels: list[str]) -> None:
        values = labels if labels else ["Sin resultados todavía"]
        self.match_menu.configure(values=values)
        if values:
            self.app.sim_match_var.set(values[0])

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
        """Rellena el Treeview con el historial de simulaciones."""
        for row in self.sim_tree.get_children():
            self.sim_tree.delete(row)

        for item in history:
            status = item.get("status", "PENDING")
            odds   = float(item.get("odds",  0) or 0)
            stake  = float(item.get("stake", 0) or 0)
            pnl    = float(item.get("pnl",   0) or 0)
            ret    = round(stake * odds, 2) if odds > 1 else 0.0
            tag    = "win" if status == "WIN" else "loss" if status == "LOSS" else "pending"
            pnl_str = f"{pnl:+.2f}" if status != "PENDING" else "—"

            self.sim_tree.insert("", "end", tags=(tag,), values=(
                item.get("timestamp", "")[:16],
                item.get("match", ""),
                item.get("pick", ""),
                f"{odds:.2f}",
                f"{stake:.2f}",
                f"{ret:.2f}",
                status,
                pnl_str,
            ), iid=str(item.get("_db_id", id(item))))
