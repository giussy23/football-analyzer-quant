"""
ui/views/portfolio.py — Vista Portfolio: historial de combinadas y ROI acumulado.
ui/views/execution.py — Vista Execution: simulador manual y bet builder.
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime

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

    def _build_slip(self):
        sim = make_card(self, "Manual 1X2 Slip",
                        "Elige un partido, selecciona 1/X/2 y calcula retorno")
        sim.pack(fill="x", pady=(0, 10))

        sb = ctk.CTkFrame(sim, fg_color="transparent")
        sb.pack(fill="x", padx=12, pady=(0, 12))

        def _entry_row(label: str, var: tk.StringVar) -> None:
            ctk.CTkLabel(sb, text=label, text_color=MUTED).pack(anchor="w")
            ctk.CTkEntry(
                sb, textvariable=var,
                fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            ).pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(sb, text="Partido", text_color=MUTED).pack(anchor="w")
        self.app.sim_match_var = tk.StringVar(value="Sin resultados todavía")
        self.match_menu = ctk.CTkComboBox(
            sb, variable=self.app.sim_match_var,
            values=["Sin resultados todavía"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
        )
        self.match_menu.pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(sb, text="Selección 1X2", text_color=MUTED).pack(anchor="w")
        self.app.manual_pick_var = tk.StringVar(value="1")
        ctk.CTkComboBox(
            sb, variable=self.app.manual_pick_var,
            values=["1", "X", "2"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
        ).pack(fill="x", pady=(4, 10))

        _entry_row("Cuota", self.app.manual_odds_var)
        _entry_row("Stake (€)", self.app.manual_stake_var)

        ctk.CTkLabel(sb, text="Estado", text_color=MUTED).pack(anchor="w")
        self.app.sim_result_var = tk.StringVar(value="PENDING")
        ctk.CTkComboBox(
            sb, variable=self.app.sim_result_var,
            values=["PENDING", "WIN", "LOSS"],
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            button_color=ACCENT, button_hover_color=ACCENT_2,
        ).pack(fill="x", pady=(4, 10))

        btn_row = ctk.CTkFrame(sb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(btn_row, text="Ver detalle",
                      command=self.app.load_selected_match_into_simulator,
                      fg_color="#1f3357").pack(side="left")
        ctk.CTkButton(btn_row, text="Calcular retorno",
                      command=self.app.update_manual_quote_preview,
                      fg_color="#25406b").pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Guardar simulación",
                      command=self.app.save_bet_simulation,
                      fg_color=ACCENT).pack(side="left", padx=8)

        self.sim_detail = make_textbox(sim, height=145)
        self.sim_detail.pack(fill="x", padx=12, pady=(0, 12))

    def _build_stats(self):
        stats = make_card(self, "Simulator Stats")
        stats.pack(fill="x", pady=(0, 10))
        self.sim_stats = make_textbox(stats, height=120)
        self.sim_stats.pack(fill="x", padx=12, pady=(0, 12))

    def _build_combo_card(self):
        builder = make_card(self, "Combo Builder")
        builder.pack(fill="x", pady=(0, 10))
        self.combo_text = make_textbox(builder, height=150)
        self.combo_text.pack(fill="x", padx=12, pady=(0, 12))

    def _build_history(self):
        hist = make_card(self, "Simulation History")
        hist.pack(fill="x", pady=(0, 10))
        self.sim_history = make_textbox(hist, height=220)
        self.sim_history.pack(fill="x", padx=12, pady=(0, 12))

    # ── Refresh ────────────────────────────────────────────────────────────────

    def refresh_match_list(self, labels: list[str]) -> None:
        values = labels if labels else ["Sin resultados todavía"]
        self.match_menu.configure(values=values)
        if values:
            self.app.sim_match_var.set(values[0])

    def refresh_stats(self, history: list[dict]) -> None:
        settled = [x for x in history if x["status"] in ("WIN", "LOSS")]
        if not settled:
            textbox_set(self.sim_stats, "Sin simulaciones todavía.")
            return
        total_stake = sum(x["stake"] for x in settled)
        total_pnl   = sum(x["pnl"]   for x in settled)
        wins   = sum(1 for x in settled if x["status"] == "WIN")
        losses = sum(1 for x in settled if x["status"] == "LOSS")
        roi    = (total_pnl / total_stake * 100) if total_stake else 0.0
        hit    = (wins / len(settled) * 100)     if settled     else 0.0
        textbox_set(
            self.sim_stats,
            f"Apuestas resueltas: {len(settled)}\n"
            f"WIN / LOSS: {wins} / {losses}\n"
            f"Stake total: {total_stake:.2f} €\n"
            f"PnL total: {total_pnl:.2f} €\n"
            f"ROI: {roi:.2f}%\n"
            f"Hit rate: {hit:.2f}%",
        )

    def refresh_history_panel(self, history: list[dict]) -> None:
        if not history:
            textbox_set(self.sim_history, "Todavía no hay simulaciones guardadas.")
            return
        total_stake = sum(x["stake"] for x in history)
        total_pnl   = sum(x["pnl"]   for x in history)
        lines = [
            f"Simulaciones: {len(history)}",
            f"Stake acumulado: {total_stake:.2f} €",
            f"PnL acumulado: {total_pnl:.2f} €",
            "",
        ]
        for item in history[:20]:
            lines.append(
                f"[{item['timestamp']}] {item['league']} | {item['match']}\n"
                f"{item['pick']} @ {item['odds']:.2f} | "
                f"Stake {item['stake']:.2f} € | {item['status']} | PnL {item['pnl']:.2f} €"
            )
            lines.append("")
        textbox_set(self.sim_history, "\n".join(lines))
