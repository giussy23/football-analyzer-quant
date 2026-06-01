"""
ui/views/quiniela.py — Vista de Quinielas IA.

Genera picks 1/X/2 (con dobles y triples opcionales) usando las
probabilidades del modelo, calcula el coste y la probabilidad de pleno.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import customtkinter as ctk
import numpy as np
import pandas as pd

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ..widgets import make_card, make_textbox, textbox_set

# Coste base por combinación en la quiniela española (€)
COSTE_BASE = 0.55

# Multiplicadores por tipo de pick
MULT = {"1": 1, "X": 1, "2": 1, "1X": 2, "X2": 2, "12": 2, "1X2": 3}

# Picks simples para calcular probabilidad de acertar
DESCOMPOSICION = {
    "1": ["H"], "X": ["D"], "2": ["A"],
    "1X": ["H", "D"], "X2": ["D", "A"], "12": ["H", "A"],
    "1X2": ["H", "D", "A"],
}


def _ai_pick(p_h: float, p_d: float, p_a: float) -> str:
    """Elige el pick IA óptimo según las probabilidades del modelo."""
    best  = max(p_h, p_d, p_a)
    best2 = sorted([p_h, p_d, p_a], reverse=True)[1]

    # Triple si todo muy incierto
    if best < 0.42:
        return "1X2"

    # Doble si el segundo más probable está cerca
    gap = best - best2
    if gap < 0.12:
        ranking = sorted(
            [("H", p_h), ("D", p_d), ("A", p_a)], key=lambda x: x[1], reverse=True
        )
        top2 = {ranking[0][0], ranking[1][0]}
        if top2 == {"H", "D"}:  return "1X"
        if top2 == {"D", "A"}:  return "X2"
        if top2 == {"H", "A"}:  return "12"

    # Simple con el más probable
    if p_h == best: return "1"
    if p_d == best: return "X"
    return "2"


def _prob_acertar(pick: str, p_h: float, p_d: float, p_a: float) -> float:
    """Probabilidad de que el pick sea correcto."""
    prob_map = {"H": p_h, "D": p_d, "A": p_a}
    return sum(prob_map.get(r, 0) for r in DESCOMPOSICION.get(pick, []))


class QuilineaRow:
    """Estado de una fila de la quiniela (un partido)."""
    def __init__(self, match_data: pd.Series):
        self.data    = match_data
        self.pick_var = tk.StringVar(value="1")
        self.p_h     = float(match_data.get("p_home", 1/3) or 1/3)
        self.p_d     = float(match_data.get("p_draw", 1/3) or 1/3)
        self.p_a     = float(match_data.get("p_away", 1/3) or 1/3)


class QuinielaView(ctk.CTkFrame):
    """Vista de generador de quinielas con IA."""

    PICK_OPTIONS = ["1", "X", "2", "1X", "X2", "12", "1X2"]
    MAX_MATCHES  = 15

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app   = app
        self._rows: list[QuilineaRow] = []
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_controls()
        self._build_table()
        self._build_summary()

    def _build_controls(self) -> None:
        ctrl = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctrl.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            ctrl, text="⚽  Quiniela IA",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")

        ctk.CTkButton(
            ctrl, text="⚡  Generar con IA",
            command=self.generate_ai,
            fg_color=ACCENT, hover_color=ACCENT_2, height=36,
        ).grid(row=0, column=3, padx=6, pady=14)

        ctk.CTkButton(
            ctrl, text="Limpiar",
            command=self.clear_picks,
            fg_color="#1f3357", height=36,
        ).grid(row=0, column=4, padx=(0, 16), pady=14)

        self.status_lbl = ctk.CTkLabel(
            ctrl,
            text="Ejecuta el análisis y pulsa ⚡ Generar con IA",
            text_color=MUTED,
        )
        self.status_lbl.grid(row=0, column=2, padx=8, sticky="w")

    def _build_table(self) -> None:
        # Estilo Treeview oscuro
        style = ttk.Style()
        style.configure("Quiniela.Treeview",
            background="#0a1422", fieldbackground="#0a1422",
            foreground="#dbe7f8", rowheight=30,
            font=("Segoe UI", 10),
        )
        style.configure("Quiniela.Treeview.Heading",
            background="#12233d", foreground="#eaf2ff",
            font=("Segoe UI Semibold", 10),
        )

        shell = ctk.CTkFrame(self, fg_color="#08101a", corner_radius=14)
        shell.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("#", "local", "visitante", "p1", "px", "p2", "pick_ia", "tu_pick")
        self.tree = ttk.Treeview(
            shell, columns=cols, show="headings",
            style="Quiniela.Treeview", selectmode="browse",
        )

        heads = {
            "#": ("#", 40), "local": ("Local", 180), "visitante": ("Visitante", 180),
            "p1": ("P(1)", 65), "px": ("P(X)", 65), "p2": ("P(2)", 65),
            "pick_ia": ("IA", 65), "tu_pick": ("Tu pick", 80),
        }
        for col, (label, width) in heads.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")

        self.tree.tag_configure("single", foreground="#d6ffe6")
        self.tree.tag_configure("double", foreground="#fff0c2")
        self.tree.tag_configure("triple", foreground="#ffd3d3")

        self.tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview).grid(
            row=0, column=1, sticky="ns", pady=6,
        )

        # Panel de edición del pick seleccionado
        edit_bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                                border_color=BORDER, border_width=1)
        edit_bar.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        edit_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(edit_bar, text="Cambiar pick seleccionado:",
                     text_color=MUTED).grid(row=0, column=0, padx=12, pady=8)

        self._edit_var = tk.StringVar(value="1")
        pick_menu = ctk.CTkOptionMenu(
            edit_bar, variable=self._edit_var,
            values=self.PICK_OPTIONS,
            fg_color=CARD_2, button_color=ACCENT,
            command=self._apply_pick_edit,
            width=100,
        )
        pick_menu.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        self.edit_lbl = ctk.CTkLabel(
            edit_bar,
            text="Selecciona un partido en la tabla para cambiar su pick",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self.edit_lbl.grid(row=0, column=2, padx=12, sticky="w")

    def _build_summary(self) -> None:
        self.summary_frame = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=14,
            border_color=BORDER, border_width=1,
        )
        self.summary_frame.grid(row=3, column=0, sticky="ew")
        self.summary_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self._kpi_labels: dict[str, ctk.CTkLabel] = {}
        kpis = [
            ("partidos",      "Partidos",         "0"),
            ("combinaciones", "Combinaciones",     "0"),
            ("coste",         "Coste",             "0.00 €"),
            ("prob",          "P(pleno)",          "—"),
        ]
        for col, (key, title, default) in enumerate(kpis):
            box = ctk.CTkFrame(self.summary_frame, fg_color="#0f1b31", corner_radius=12)
            box.grid(row=0, column=col, padx=6, pady=10, sticky="ew")
            ctk.CTkLabel(box, text=title, text_color=MUTED,
                         font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(10, 2))
            lbl = ctk.CTkLabel(box, text=default, text_color=TEXT,
                               font=ctk.CTkFont(size=20, weight="bold"))
            lbl.pack(anchor="w", padx=12, pady=(0, 10))
            self._kpi_labels[key] = lbl

    # ── Generación IA ─────────────────────────────────────────────────────────

    def generate_ai(self, df: pd.DataFrame | None = None) -> None:
        """Carga los próximos partidos y genera picks con IA."""
        if df is None:
            df = self.app.results

        if df is None or df.empty:
            self.status_lbl.configure(text="⚠  Ejecuta el análisis primero.")
            return

        # Tomar hasta MAX_MATCHES partidos futuros con probabilidades disponibles
        fut = df[df["p_home"].notna() & df["p_draw"].notna() & df["p_away"].notna()].copy()
        if fut.empty:
            self.status_lbl.configure(text="⚠  Sin partidos con predicciones del modelo.")
            return

        fut = fut.head(self.MAX_MATCHES)
        self._rows = [QuilineaRow(row) for _, row in fut.iterrows()]

        # Asignar picks IA
        for r in self._rows:
            r.pick_var.set(_ai_pick(r.p_h, r.p_d, r.p_a))

        self._refresh_tree()
        self.status_lbl.configure(
            text=f"✓  {len(self._rows)} partidos · picks generados por IA"
        )

    def clear_picks(self) -> None:
        for r in self._rows:
            r.pick_var.set("1")
        self._refresh_tree()

    # ── Edición de picks ──────────────────────────────────────────────────────

    def _apply_pick_edit(self, _value: str = "") -> None:
        """Aplica el pick del menú a la fila seleccionada en el Treeview."""
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._rows):
            new_pick = self._edit_var.get()
            self._rows[idx].pick_var.set(new_pick)
            self._refresh_tree()
            self.tree.selection_set(str(idx))
            self.edit_lbl.configure(
                text=f"Partido {idx + 1} → {new_pick}"
            )

    # ── Refresco de tabla y KPIs ──────────────────────────────────────────────

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        total_prob  = 1.0
        total_mult  = 1
        has_probs   = True

        for i, r in enumerate(self._rows):
            pick = r.pick_var.get()
            mult = MULT.get(pick, 1)
            total_mult *= mult

            p_h = r.p_h
            p_d = r.p_d
            p_a = r.p_a

            prob = _prob_acertar(pick, p_h, p_d, p_a)
            if prob <= 0:
                has_probs = False
            total_prob *= prob

            ai_pick = _ai_pick(p_h, p_d, p_a)
            tag     = "triple" if mult == 3 else "double" if mult == 2 else "single"

            home = r.data.get("home_team", "?")
            away = r.data.get("away_team", "?")

            self.tree.insert("", "end", iid=str(i), tags=(tag,), values=(
                i + 1,
                home[:22],
                away[:22],
                f"{p_h:.0%}",
                f"{p_d:.0%}",
                f"{p_a:.0%}",
                ai_pick,
                pick,
            ))

        # Actualizar KPIs
        n       = len(self._rows)
        coste   = round(total_mult * COSTE_BASE, 2)
        prob_str = f"{total_prob:.3%}" if has_probs and n > 0 else "—"

        self._kpi_labels["partidos"].configure(text=str(n))
        self._kpi_labels["combinaciones"].configure(text=str(total_mult))
        self._kpi_labels["coste"].configure(text=f"{coste:.2f} €")
        self._kpi_labels["prob"].configure(
            text=prob_str,
            text_color="#00c853" if has_probs and total_prob > 0.01
            else "#ffd600" if has_probs else MUTED,
        )
