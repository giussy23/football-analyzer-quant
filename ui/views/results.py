# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/results.py — Tracker de picks reales con ROI verificado.

Fixes v14:
  ① Sin duplicados — comprueba (partido + pick) antes de guardar
  ② Guarda VERDE y AMARILLO — distinguidos por color en la tabla
  ③ P&L en euros — usa la banca configurada en ⚙️ Strategy
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

import customtkinter as ctk
import pandas as pd

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT

if TYPE_CHECKING:
    from ...app import PremiumApp


import logging

logger = logging.getLogger(__name__)


class ResultsView(ctk.CTkFrame):
    """Seguimiento de picks reales: estado, stake €, P&L € y ROI verificado."""

    def __init__(self, parent, app: "PremiumApp", **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._picks: list[dict] = []
        self._setup_style()
        self._build()
        self.refresh()

    # ── Treeview style ─────────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        style = ttk.Style()
        style.configure(
            "Results.Treeview",
            background="#050e1c", fieldbackground="#050e1c",
            foreground="#f0fff4", rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Results.Treeview.Heading",
            background="#091408", foreground="#f0fff4",
            font=("Segoe UI Semibold", 10),
        )
        style.map("Results.Treeview", background=[("selected", "#1a4d2a")])

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_top_bar()
        self._build_kpis()
        self._build_table()
        self._build_action_bar()

    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar, text="Tracker de Picks Reales",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            bar,
            text="VERDE + AMARILLO · Sin duplicados · P&L en euros reales",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="w")

        btn_frame = ctk.CTkFrame(bar, fg_color="transparent")
        btn_frame.grid(row=0, column=1, rowspan=2, sticky="e")

        ctk.CTkButton(
            btn_frame,
            text="📥 Guardar picks del análisis",
            command=self._import_from_app,
            fg_color=ACCENT, hover_color=ACCENT_2,
            height=36, corner_radius=10,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame, text="🔄 Actualizar",
            command=self.refresh,
            fg_color=CARD, hover_color=CARD_2,
            border_color=BORDER, border_width=1, text_color=TEXT,
            height=36, corner_radius=10,
        ).pack(side="left")

    def _build_kpis(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for i in range(7):
            row.grid_columnconfigure(i, weight=1)

        kpi_defs = [
            ("picks_lbl",    "Picks guardados",  "0"),
            ("verde_lbl",    "VERDE / AMAR.",    "0 / 0"),
            ("accierto_lbl", "Tasa de acierto",  "0.0%"),
            ("roi_lbl",      "ROI real",         "0.00%"),
            ("pnl_lbl",      "P&L",              "0.00"),
            ("clv_avg_lbl",  "CLV medio",        "—"),
            ("clv_pos_lbl",  "Picks CLV+",       "—"),
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
            val_lbl = ctk.CTkLabel(
                card, text=default, text_color=ACCENT,
                font=ctk.CTkFont(size=20, weight="bold"),
            )
            val_lbl.pack(anchor="w", padx=12, pady=(0, 10))
            self._kpi_labels[key] = val_lbl

    def _build_table(self) -> None:
        shell = ctk.CTkFrame(
            self, fg_color="#060f07", corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        shell.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("#", "señal", "fecha", "partido", "liga",
                "pick", "cuota", "edge", "prob", "stake", "estado", "p&l", "clv")
        self.tree = ttk.Treeview(
            shell, columns=cols, show="headings",
            style="Results.Treeview", selectmode="browse",
        )

        col_cfg = {
            "#":       (36,  "center"),
            "señal":   (70,  "center"),
            "fecha":   (86,  "center"),
            "partido": (200, "w"),
            "liga":    (75,  "center"),
            "pick":    (70,  "center"),
            "cuota":   (60,  "center"),
            "edge":    (60,  "center"),
            "prob":    (60,  "center"),
            "stake":   (80,  "center"),
            "estado":  (78,  "center"),
            "p&l":     (90,  "center"),
            "clv":     (70,  "center"),
        }
        for col in cols:
            w, anchor = col_cfg[col]
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=w, anchor=anchor, minwidth=w)

        # Tooltip en cabecera CLV
        self._clv_tooltip: tk.Toplevel | None = None
        self.tree.heading(
            "clv",
            text="CLV",
            command=lambda: None,
        )
        self.tree.bind("<Motion>", self._on_header_motion)
        self.tree.bind("<Leave>", self._hide_clv_tooltip)

        # Tags por señal + resultado
        self.tree.tag_configure("verde_win",     background="#0c2918", foreground="#b0f0c8")
        self.tree.tag_configure("verde_loss",    background="#2d0d0d", foreground="#ffc0c0")
        self.tree.tag_configure("verde_pending", background="#050e1c", foreground="#c8e0ff")
        self.tree.tag_configure("amar_win",      background="#252000", foreground="#f0e080")
        self.tree.tag_configure("amar_loss",     background="#2a1008", foreground="#f0c090")
        self.tree.tag_configure("amar_pending",  background="#161400", foreground="#d8d080")
        self.tree.tag_configure("void",          background="#141414", foreground="#909090")

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew")

        for text, fg, hover, cmd in [
            ("✅ Ganado",  "#166534", "#14532d", lambda: self._settle("WIN")),
            ("❌ Perdido", "#991b1b", "#7f1d1d", lambda: self._settle("LOSS")),
            ("⬜ Nulo",    "#374151", "#1f2937", lambda: self._settle("VOID")),
            ("🗑 Eliminar","#4b1111", "#3b0d0d", self._delete_pick),
        ]:
            ctk.CTkButton(
                bar, text=text, command=cmd,
                fg_color=fg, hover_color=hover,
                height=36, corner_radius=10,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            bar, text="🔬 Autopsia IA",
            command=self._autopsy_selected,
            fg_color="#1e1b4b", hover_color="#312e81",
            border_color="#818cf8", border_width=1,
            text_color="#c4b5fd",
            height=36, corner_radius=10,
        ).pack(side="left", padx=(0, 6))

        self._auto_settle_btn = ctk.CTkButton(
            bar, text="⚡ Auto-liquidar",
            command=self._auto_settle_all,
            fg_color="#0c2a4e", hover_color="#1e3a5f",
            border_color="#3b82f6", border_width=1,
            text_color="#93c5fd",
            height=36, corner_radius=10,
        )
        self._auto_settle_btn.pack(side="left", padx=(0, 6))

        self._status_lbl = ctk.CTkLabel(
            bar, text="Selecciona un pick para liquidar",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._status_lbl.pack(side="left", padx=8)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._picks = self.app.storage.load_model_picks()
        self._fill_tree()
        self._update_kpis()

    def import_verde_picks(self, results_df: pd.DataFrame) -> tuple[int, int]:
        """
        Importa picks VERDE y AMARILLO del DataFrame de análisis.

        Retorna (guardados, omitidos_por_duplicado).
        """
        if results_df is None or results_df.empty:
            return 0, 0

        if "risk_light" not in results_df.columns:
            return 0, 0

        # Bug fix: DataFrame.get() con Series vacío causa ValueError por shape mismatch
        if "pick" in results_df.columns:
            pick_mask = results_df["pick"] != "NO BET"
        else:
            pick_mask = pd.Series(True, index=results_df.index)

        candidates = results_df[
            results_df["risk_light"].isin(["VERDE", "AMARILLO"]) & pick_mask
        ].copy()

        if candidates.empty:
            return 0, 0

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        saved = dupes = 0

        for _, row in candidates.iterrows():
            home  = str(row.get("home_team", ""))
            away  = str(row.get("away_team", ""))
            date  = str(row.get("date", ""))
            pick  = str(row.get("pick", ""))

            # ── Fix ①: deduplicación ──────────────────────────────────────────
            if self.app.storage.pick_exists(home, away, date, pick):
                dupes += 1
                continue

            signal = str(row.get("risk_light", "VERDE"))

            data = {
                "saved_at":    now,
                "date":        date,
                "home_team":   home,
                "away_team":   away,
                "league":      str(row.get("league", row.get("div", ""))),
                "pick":        pick,
                "odds":        float(row["odds"])        if pd.notna(row.get("odds"))        else None,
                "edge":        float(row["edge"])        if pd.notna(row.get("edge"))        else None,
                "model_prob":  float(row["model_prob"])  if pd.notna(row.get("model_prob"))  else None,
                "bankroll_pct": float(row["bankroll_pct"]) if pd.notna(row.get("bankroll_pct")) else None,
                "status":      "PENDING",
                "pnl":         0.0,
                "signal":      signal,   # ── Fix ②: VERDE o AMARILLO ─────────
                # Magnitud del ajuste Claude — para auditar la capa IA con picks liquidados
                "claude_adj":  float(row["claude_adj"]) if pd.notna(row.get("claude_adj")) else None,
            }
            self.app.storage.save_model_pick(data)
            saved += 1

        self.refresh()
        return saved, dupes

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _bankroll(self) -> float:
        """Banca configurada en euros (0 si no está configurada)."""
        try:
            return max(0.0, float(self.app.bankroll_eur.get()))
        except (ValueError, AttributeError):
            return 0.0

    def _fmt_money(self, value: float, pct: bool = False) -> str:
        """Formatea un valor como euros o unidades según si hay banca configurada."""
        bankroll = self._bankroll()
        if bankroll > 0:
            eur = value * bankroll
            sign = "+" if eur > 0 else ""
            return f"{sign}{eur:.2f}€"
        # Sin banca: mostrar en unidades
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.4f}u"

    def _fmt_stake(self, bankroll_pct: float | None) -> str:
        """Formatea el stake como euros o porcentaje."""
        if bankroll_pct is None:
            return "—"
        bankroll = self._bankroll()
        if bankroll > 0:
            return f"{bankroll * bankroll_pct / 100:.2f}€"
        return f"{bankroll_pct:.2f}%"

    def _fill_tree(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for idx, pick in enumerate(self._picks, start=1):
            status = pick.get("status", "PENDING")
            signal = pick.get("signal", "VERDE")

            if status == "VOID":
                tag = "void"
            else:
                prefix = "verde" if signal == "VERDE" else "amar"
                suffix = {"WIN": "win", "LOSS": "loss"}.get(status, "pending")
                tag = f"{prefix}_{suffix}"

            # ── Columna señal ──────────────────────────────────────────────────
            signal_txt = "● VERDE" if signal == "VERDE" else "● AMAR."

            # ── Stake y P&L ───────────────────────────────────────────────────
            stake_str = self._fmt_stake(pick.get("bankroll_pct"))
            pnl       = pick.get("pnl") or 0.0
            pnl_str   = self._fmt_money(pnl) if status != "PENDING" else "—"

            odds       = pick.get("odds")
            edge       = pick.get("edge")
            model_prob = pick.get("model_prob")
            clv_val    = pick.get("clv")

            if clv_val is not None:
                sign = "+" if clv_val >= 0 else ""
                clv_str = f"{sign}{clv_val * 100:.1f}%"
            else:
                clv_str = "—"

            self.tree.insert(
                "", "end",
                iid=str(pick["id"]),
                tags=(tag,),
                values=(
                    idx,
                    signal_txt,
                    str(pick.get("date", ""))[:10],
                    f"{pick.get('home_team','')} vs {pick.get('away_team','')}",
                    pick.get("league", ""),
                    pick.get("pick", ""),
                    f"{odds:.2f}"       if odds       is not None else "—",
                    f"{edge*100:.1f}%"  if edge       is not None else "—",
                    f"{model_prob:.0%}" if model_prob is not None else "—",
                    stake_str,
                    status,
                    pnl_str,
                    clv_str,
                ),
            )

    def _update_kpis(self) -> None:
        picks    = self._picks
        total    = len(picks)
        n_verde  = sum(1 for p in picks if p.get("signal", "VERDE") == "VERDE")
        n_amar   = total - n_verde
        settled  = [p for p in picks if p.get("status") in ("WIN", "LOSS")]
        wins     = [p for p in picks if p.get("status") == "WIN"]

        hit_rate  = len(wins) / len(settled) * 100 if settled else 0.0
        total_pnl = sum(float(p.get("pnl") or 0.0) for p in settled)
        total_risk = sum(
            float(p.get("bankroll_pct") or 0.0) / 100.0
            for p in settled if p.get("bankroll_pct") is not None
        )
        roi = (total_pnl / total_risk * 100) if total_risk > 0 else 0.0

        # ── Fix ③: P&L en euros si hay banca configurada ─────────────────────
        bankroll = self._bankroll()
        if bankroll > 0:
            pnl_display = f"{total_pnl * bankroll:+.2f}€"
        else:
            pnl_display = f"{total_pnl:+.4f}u"

        roi_color = ACCENT if roi >= 0 else "#ef4444"
        pnl_color = ACCENT if total_pnl >= 0 else "#ef4444"

        # ── CLV KPIs ──────────────────────────────────────────────────────────
        clv_values = [float(p["clv"]) for p in picks if p.get("clv") is not None]
        if clv_values:
            clv_avg     = sum(clv_values) / len(clv_values)
            clv_pos_pct = sum(1 for v in clv_values if v > 0) / len(clv_values) * 100
            sign        = "+" if clv_avg >= 0 else ""
            clv_avg_txt = f"{sign}{clv_avg * 100:.2f}%"
            clv_pos_txt = f"{clv_pos_pct:.0f}%"
            clv_avg_color = ACCENT if clv_avg >= 0 else "#ef4444"
            clv_pos_color = ACCENT if clv_pos_pct >= 50 else "#ef4444"
        else:
            clv_avg_txt   = "—"
            clv_pos_txt   = "—"
            clv_avg_color = MUTED
            clv_pos_color = MUTED

        self._kpi_labels["picks_lbl"].configure(text=str(total), text_color=ACCENT)
        self._kpi_labels["verde_lbl"].configure(
            text=f"{n_verde} / {n_amar}", text_color=ACCENT,
        )
        self._kpi_labels["accierto_lbl"].configure(
            text=f"{hit_rate:.1f}%", text_color=ACCENT,
        )
        self._kpi_labels["roi_lbl"].configure(
            text=f"{roi:+.2f}%", text_color=roi_color,
        )
        self._kpi_labels["pnl_lbl"].configure(
            text=pnl_display, text_color=pnl_color,
        )
        self._kpi_labels["clv_avg_lbl"].configure(
            text=clv_avg_txt, text_color=clv_avg_color,
        )
        self._kpi_labels["clv_pos_lbl"].configure(
            text=clv_pos_txt, text_color=clv_pos_color,
        )

    def _selected_pick_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Resultados", "Selecciona un pick primero.")
            return None
        try:
            return int(sel[0])
        except ValueError:
            return None

    def _settle(self, result: str) -> None:
        pick_id = self._selected_pick_id()
        if pick_id is None:
            return

        pick = next((p for p in self._picks if p["id"] == pick_id), None)
        if pick is None:
            return

        if pick.get("status") != "PENDING":
            messagebox.showinfo(
                "Resultados",
                f"Este pick ya está liquidado como {pick['status']}.",
            )
            return

        bankroll_pct = float(pick.get("bankroll_pct") or 0.0)
        odds_raw     = pick.get("odds")

        # Bug fix: odds puede ser None/NULL en DB → aviso en lugar de registrar 0€
        if result == "WIN":
            if odds_raw is None or float(odds_raw) <= 1.0:
                messagebox.showwarning(
                    "Cuota inválida",
                    "Las cuotas de este pick son 0 o no están disponibles.\n"
                    "Edita el pick manualmente y liquídalo de nuevo.",
                )
                return
            pnl = (float(odds_raw) - 1.0) * bankroll_pct / 100.0
        elif result == "LOSS":
            pnl = -(bankroll_pct / 100.0)
        else:
            pnl = 0.0

        # ── Diálogo de closing odds (CLV) ─────────────────────────────────────
        closing_odds_value: float | None = None
        clv_value: float | None         = None
        closing_odds_value, clv_value   = self._ask_closing_odds(pick, odds_raw)

        self.app.storage.update_pick_result(pick_id, result, pnl)

        if closing_odds_value is not None and clv_value is not None:
            self.app.storage.update_pick_clv(pick_id, closing_odds_value, clv_value)

        # Mensaje con euros si hay banca configurada
        bankroll = self._bankroll()
        if bankroll > 0:
            pnl_str = f"{pnl * bankroll:+.2f}€"
        else:
            pnl_str = f"{pnl:+.4f}u"

        clv_suffix = ""
        if clv_value is not None:
            sign = "+" if clv_value >= 0 else ""
            clv_suffix = f"  CLV {sign}{clv_value * 100:.1f}%"

        self._status_lbl.configure(
            text=f"✓  Pick #{pick_id} → {result}  ({pnl_str}){clv_suffix}",
            text_color=ACCENT if pnl >= 0 else "#ef4444",
        )
        self.refresh()

    def _ask_closing_odds(
        self, pick: dict, odds_raw
    ) -> tuple[float | None, float | None]:
        """
        Muestra un diálogo modal pidiendo la closing odds.
        Devuelve (closing_odds, clv) o (None, None) si el usuario omite el campo.
        """
        dialog = tk.Toplevel(self)
        dialog.title("Closing Odds (CLV)")
        dialog.configure(bg="#050e1c")
        dialog.resizable(False, False)
        dialog.grab_set()

        # Centrar sobre la ventana padre
        dialog.update_idletasks()
        px = self.winfo_rootx() + self.winfo_width() // 2
        py = self.winfo_rooty() + self.winfo_height() // 2
        dialog.geometry(f"340x210+{px - 170}+{py - 105}")

        tk.Label(
            dialog,
            text="Closing Odds (opcional)",
            bg="#050e1c", fg="#f0fff4",
            font=("Segoe UI Semibold", 11),
        ).pack(padx=20, pady=(18, 4), anchor="w")

        opening_txt = f"{float(odds_raw):.2f}" if odds_raw is not None else "N/A"
        tk.Label(
            dialog,
            text=f"Cuota de entrada: {opening_txt}  ·  "
                 "Deja en blanco para omitir CLV",
            bg="#050e1c", fg="#7dd3fa",
            font=("Segoe UI", 9),
        ).pack(padx=20, anchor="w")

        entry_var = tk.StringVar()
        entry = tk.Entry(
            dialog,
            textvariable=entry_var,
            bg="#091408", fg="#f0fff4",
            insertbackground="#f0fff4",
            relief="flat", bd=1,
            font=("Segoe UI", 12),
            width=14,
            highlightthickness=1,
            highlightcolor="#2dd45b",
            highlightbackground="#2dd45b",
        )
        entry.pack(padx=20, pady=(8, 4), anchor="w", ipady=4)
        entry.focus_set()

        feedback_lbl = tk.Label(
            dialog, text="", bg="#050e1c", fg="#ef4444",
            font=("Segoe UI", 9),
        )
        feedback_lbl.pack(padx=20, anchor="w")

        result_container: list = [None, None]

        def _confirm(event=None) -> None:
            raw = entry_var.get().strip().replace(",", ".")
            if raw == "":
                dialog.destroy()
                return
            try:
                c_odds = float(raw)
                if c_odds <= 1.0:
                    raise ValueError
            except ValueError:
                feedback_lbl.configure(text="Introduce una cuota válida (> 1.00)")
                return

            if odds_raw is not None and float(odds_raw) > 1.0:
                clv = (float(odds_raw) / c_odds) - 1.0
            else:
                clv = None

            result_container[0] = c_odds
            result_container[1] = clv
            dialog.destroy()

        def _skip() -> None:
            dialog.destroy()

        btn_frame = tk.Frame(dialog, bg="#050e1c")
        btn_frame.pack(padx=20, pady=(12, 0), anchor="w")

        ok_btn = tk.Button(
            btn_frame, text="Guardar CLV",
            command=_confirm,
            bg="#166534", fg="#f0fff4", activebackground="#14532d",
            relief="flat", padx=14, pady=6,
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        ok_btn.pack(side="left", padx=(0, 8))

        skip_btn = tk.Button(
            btn_frame, text="Omitir",
            command=_skip,
            bg="#1f2937", fg="#7dd3fa", activebackground="#374151",
            relief="flat", padx=14, pady=6,
            font=("Segoe UI", 10),
            cursor="hand2",
        )
        skip_btn.pack(side="left")

        entry.bind("<Return>", _confirm)
        entry.bind("<Escape>", lambda e: _skip())

        dialog.wait_window()
        return result_container[0], result_container[1]

    def _delete_pick(self) -> None:
        pick_id = self._selected_pick_id()
        if pick_id is None:
            return
        if not messagebox.askyesno("Eliminar", f"¿Eliminar el pick #{pick_id}?"):
            return
        self.app.storage.delete_model_pick(pick_id)
        self._status_lbl.configure(
            text=f"🗑  Pick #{pick_id} eliminado", text_color=MUTED,
        )
        self.refresh()

    # ── CLV header tooltip ─────────────────────────────────────────────────────

    def _on_header_motion(self, event: tk.Event) -> None:
        """Muestra tooltip cuando el cursor pasa por la cabecera CLV."""
        region = self.tree.identify_region(event.x, event.y)
        if region == "heading":
            col_id = self.tree.identify_column(event.x)
            # Obtener índice de la columna CLV
            cols = self.tree["columns"]
            try:
                clv_idx = list(cols).index("clv")
                clv_col_id = f"#{clv_idx + 1}"
            except ValueError:
                clv_col_id = None

            if col_id == clv_col_id:
                self._show_clv_tooltip(event)
                return
        self._hide_clv_tooltip()

    def _show_clv_tooltip(self, event: tk.Event) -> None:
        """Crea (o reutiliza) la ventana de tooltip para la cabecera CLV."""
        if self._clv_tooltip is not None:
            return  # ya visible

        tip = tk.Toplevel(self)
        tip.wm_overrideredirect(True)
        tip.configure(bg="#1a5228")
        tip.attributes("-topmost", True)

        tk.Label(
            tip,
            text="Closing Line Value:\ncuánto mejor que el mercado fue tu cuota de entrada",
            bg="#1a5228", fg="#f0fff4",
            font=("Segoe UI", 9),
            padx=10, pady=6,
            justify="left",
            relief="flat",
        ).pack()

        x = self.winfo_rootx() + event.x + 12
        y = self.winfo_rooty() + event.y + 20
        tip.geometry(f"+{x}+{y}")
        self._clv_tooltip = tip

    def _hide_clv_tooltip(self, _event=None) -> None:
        """Destruye el tooltip si existe."""
        if self._clv_tooltip is not None:
            self._clv_tooltip.destroy()
            self._clv_tooltip = None

    def _import_from_app(self) -> None:
        df = getattr(self.app, "results", None)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            messagebox.showinfo(
                "Sin datos",
                "No hay resultados disponibles.\nEjecuta el análisis primero.",
            )
            return

        saved, dupes = self.import_verde_picks(df)

        if saved == 0 and dupes == 0:
            messagebox.showinfo(
                "Importar",
                "No se encontraron picks VERDE ni AMARILLO en el análisis actual.",
            )
        elif saved == 0 and dupes > 0:
            messagebox.showinfo(
                "Sin cambios",
                f"Todos los picks ({dupes}) ya estaban guardados.\nNo se añadieron duplicados.",
            )
        else:
            msg = f"✅  {saved} pick{'s' if saved != 1 else ''} guardado{'s' if saved != 1 else ''}."
            if dupes > 0:
                msg += f"\n({dupes} ya existían — no duplicados)"
            messagebox.showinfo("Importar", msg)

    def _get_selected_pick(self) -> dict | None:
        """Retorna el pick seleccionado actualmente o None."""
        sel = self.tree.selection()
        if not sel:
            return None
        pick_id = sel[0]
        for p in self._picks:
            if str(p.get("id")) == str(pick_id):
                return p
        return None

    # ── Auto-liquidación ──────────────────────────────────────────────────────

    def _auto_settle_all(self) -> None:
        """
        Lanza la liquidación automática de todos los picks PENDING cuya
        fecha de partido ya haya pasado, usando la ESPN Scores API.
        """
        pending = [p for p in self._picks if p.get("status") == "PENDING"]
        if not pending:
            self._status_lbl.configure(
                text="No hay picks PENDING para liquidar", text_color=MUTED,
            )
            return

        bankroll = self._bankroll()
        if bankroll <= 0:
            # Advertencia pero no bloqueante — se calculará P&L en unidades
            bankroll = 1.0

        self._auto_settle_btn.configure(state="disabled", text="⏳ Buscando…")
        self._status_lbl.configure(
            text=f"⚡  Buscando resultados para {len(pending)} picks…",
            text_color="#93c5fd",
        )

        threading.Thread(
            target=self._auto_settle_worker,
            args=(list(pending), bankroll),
            daemon=True,
        ).start()

    def _auto_settle_worker(self, pending: list, bankroll: float) -> None:
        """Hilo de fondo: llama a auto_settle() y actualiza la UI al terminar."""
        from ...core.auto_settler import auto_settle
        try:
            report = auto_settle(pending, bankroll, self.app.storage)
        except Exception as exc:
            report = {"settled": 0, "not_found": 0, "skipped": 0, "results": [], "error": str(exc)}

        self.app.after(0, lambda r=report: self._on_auto_settle_done(r))

    def _on_auto_settle_done(self, report: dict) -> None:
        """Llamado en el hilo principal cuando la auto-liquidación termina."""
        self._auto_settle_btn.configure(state="normal", text="⚡ Auto-liquidar")
        self.refresh()

        settled    = report.get("settled",   0)
        not_found  = report.get("not_found", 0)
        skipped    = report.get("skipped",   0)
        error      = report.get("error")

        if error:
            self._status_lbl.configure(
                text=f"⚠  Error en auto-liquidación: {error}",
                text_color="#ef4444",
            )
            return

        if settled == 0 and not_found == 0 and skipped > 0:
            self._status_lbl.configure(
                text="⚡  Sin picks pasados que liquidar (todos son futuros o ya liquidados)",
                text_color=MUTED,
            )
            return

        parts = []
        if settled:
            wins   = sum(1 for r in report.get("results", []) if r["status"] == "WIN")
            losses = settled - wins
            parts.append(f"✓ {settled} liquidados  ({wins}W / {losses}L)")
        if not_found:
            parts.append(f"{not_found} sin resultado ESPN")
        if skipped:
            parts.append(f"{skipped} omitidos")

        color = ACCENT if settled > 0 else MUTED
        self._status_lbl.configure(text="  ·  ".join(parts), text_color=color)

        # Mostrar detalle en un messagebox si se liquidaron picks
        if settled > 0:
            lines = [f"⚡ Auto-liquidación: {settled} picks", ""]
            for r in report.get("results", []):
                icon = "✅" if r["status"] == "WIN" else "❌"
                pnl  = r["pnl"]
                bankroll = self._bankroll()
                if bankroll > 1:
                    pnl_str = f"{pnl * bankroll:+.2f}€"
                else:
                    pnl_str = f"{pnl:+.4f}u"
                lines.append(
                    f"{icon} {r['match'][:35]}  {r['pick']}  {r['score']}  ({pnl_str})"
                )
            if not_found:
                lines += ["", f"⚠ {not_found} partidos no encontrados en ESPN"]
            messagebox.showinfo("Auto-liquidación", "\n".join(lines))

    def _autopsy_selected(self) -> None:
        """Lanza la autopsia IA del pick seleccionado."""
        import threading as _threading
        pick = self._get_selected_pick()
        if not pick:
            from tkinter import messagebox
            messagebox.showinfo("Autopsia IA", "Selecciona un pick de la tabla para analizar.")
            return

        status = pick.get("status", "PENDING")
        if status == "PENDING":
            from tkinter import messagebox
            messagebox.showinfo(
                "Autopsia IA",
                "La autopsia solo está disponible para picks ya liquidados (WIN o LOSS)."
            )
            return

        api_key = self.app.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            from tkinter import messagebox
            messagebox.showwarning(
                "Autopsia IA",
                "Configura la API key de Anthropic en ⚙️ Strategy para usar esta función."
            )
            return

        # Mostrar ventana de carga
        self._autopsy_loading = self._show_autopsy_loading(pick)
        history = list(self._picks)   # todos los picks para contexto

        _threading.Thread(
            target=self._autopsy_worker,
            args=(pick, history, api_key),
            daemon=True,
        ).start()

    def _autopsy_worker(self, pick: dict, history: list, api_key: str) -> None:
        from ...core.ai_analysis import autopsy_pick
        result = autopsy_pick(pick, history, api_key)
        self.app.after(0, lambda r=result, p=pick: self._show_autopsy_result(r, p))

    def _show_autopsy_loading(self, pick: dict) -> "ctk.CTkToplevel":
        import customtkinter as ctk
        win = ctk.CTkToplevel(self.app)
        win.title("Autopsia IA")
        win.geometry("480x160")
        win.configure(fg_color="#050e1c")
        win.grab_set()

        home = pick.get("home_team", "?")
        away = pick.get("away_team", "?")
        ctk.CTkLabel(
            win,
            text=f"🔬 Analizando: {home} vs {away}",
            text_color=ACCENT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(pady=(30, 8))
        ctk.CTkLabel(
            win, text="Claude está generando la autopsia...",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack()
        return win

    def _show_autopsy_result(self, result: str, pick: dict) -> None:
        import tkinter as tk
        import customtkinter as ctk

        # Cerrar ventana de carga
        if hasattr(self, "_autopsy_loading") and self._autopsy_loading:
            try:
                self._autopsy_loading.destroy()
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)

        self.app._update_claude_counter()

        home   = pick.get("home_team", "?")
        away   = pick.get("away_team", "?")
        mpick  = pick.get("pick", "?")
        status = pick.get("status", "?")
        odds   = pick.get("odds")
        prob   = pick.get("model_prob")
        clv    = pick.get("clv")

        win = ctk.CTkToplevel(self.app)
        win.title(f"Autopsia IA — {home} vs {away}")
        win.geometry("640x480")
        win.configure(fg_color="#050e1c")
        win.grab_set()

        # Header
        result_color = "#22c55e" if status == "WIN" else "#ef4444"
        result_icon  = "✅" if status == "WIN" else "❌"
        ctk.CTkLabel(
            win,
            text=f"🔬 Autopsia: {home} vs {away}",
            text_color=ACCENT, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=20, pady=(16, 2))

        # Stats row
        stats_frame = ctk.CTkFrame(win, fg_color="#0a1a0e", corner_radius=8)
        stats_frame.pack(fill="x", padx=20, pady=(0, 12))
        stats_inner = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_inner.pack(padx=12, pady=8)

        stats = [
            (f"{result_icon} {status}", result_color),
            (f"Pick: {mpick}", TEXT),
        ]
        if odds:
            stats.append((f"Cuota: {float(odds):.2f}", MUTED))
        if prob:
            stats.append((f"P(modelo): {float(prob):.0%}", MUTED))
        if clv is not None:
            clv_f = float(clv)
            clv_color = "#22c55e" if clv_f >= 0 else "#ef4444"
            stats.append((f"CLV: {clv_f*100:+.1f}%", clv_color))

        for i, (txt, color) in enumerate(stats):
            ctk.CTkLabel(
                stats_inner, text=txt,
                text_color=color, font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=0, column=i, padx=(0 if i == 0 else 16, 0))

        # Texto autopsia
        ctk.CTkLabel(
            win, text="Análisis de Claude:",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=20, pady=(0, 4))

        text_box = ctk.CTkTextbox(
            win, fg_color="#0a1a0e",
            text_color="#e8d5ff",
            font=ctk.CTkFont(size=12),
            corner_radius=8, height=220,
        )
        text_box.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        text_box.insert("end", result)
        text_box.configure(state="disabled")

        ctk.CTkButton(
            win, text="Cerrar",
            command=win.destroy,
            fg_color=ACCENT_2, hover_color=ACCENT,
            height=36, corner_radius=10,
        ).pack(pady=(0, 16))
