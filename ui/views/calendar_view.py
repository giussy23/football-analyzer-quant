# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/calendar_view.py — Calendario mensual de picks.

Muestra un grid de días del mes con los picks coloreados por estado
(PENDING azul, WIN verde, LOSS rojo, VOID gris).
Al hacer click en un día se despliega el detalle de los picks de esa fecha.
"""

from __future__ import annotations

import calendar
import tkinter as tk
from collections import defaultdict
from datetime import date, datetime
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT

if TYPE_CHECKING:
    from ...app import PremiumApp

# Paleta de estados
_STATUS_COLOR = {
    "WIN":     "#22c55e",
    "LOSS":    "#ef4444",
    "VOID":    "#6b7280",
    "PENDING": "#60a5fa",
    "FIXTURE": "#a78bfa",   # morado — partido del análisis (aún sin apostar)
}
_STATUS_BG = {
    "WIN":     "#0c2918",
    "LOSS":    "#2d0d0d",
    "VOID":    "#141414",
    "PENDING": "#0c1f38",
    "FIXTURE": "#1a0a38",
}

_DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


class CalendarView(ctk.CTkFrame):
    """Calendario mensual interactivo de picks."""

    def __init__(self, parent, app: "PremiumApp", **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._today  = date.today()
        self._year   = self._today.year
        self._month  = self._today.month
        self._picks_by_date: dict[str, list[dict]] = {}
        self._selected_date: str | None = None
        self._day_frames: dict[str, ctk.CTkFrame] = {}

        self._build()
        self.refresh()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_nav_bar()
        self._build_body()

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar, text="Calendario de Picks",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            bar,
            text="Vista mensual  ·  Click en un día para ver detalle",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="w")

        # Leyenda
        legend = ctk.CTkFrame(bar, fg_color="transparent")
        legend.grid(row=0, column=1, rowspan=2, sticky="e")
        legend_items = [
            ("WIN",     "WIN"),
            ("LOSS",    "LOSS"),
            ("VOID",    "VOID"),
            ("PENDING", "PENDING"),
            ("FIXTURE", "⚽ Análisis"),
        ]
        for status, label in legend_items:
            color = _STATUS_COLOR[status]
            ctk.CTkLabel(
                legend, text=f"● {label}",
                text_color=color, font=ctk.CTkFont(size=10),
            ).pack(side="left", padx=6)

    def _build_nav_bar(self) -> None:
        nav = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                           border_color=BORDER, border_width=1)
        nav.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        nav.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            nav, text="◀", width=36,
            command=self._prev_month,
            fg_color=CARD_2, hover_color="#1f2937",
            border_color=BORDER, border_width=1, text_color=TEXT,
            corner_radius=8,
        ).grid(row=0, column=0, padx=12, pady=8)

        self._month_lbl = ctk.CTkLabel(
            nav, text="",
            text_color=TEXT, font=ctk.CTkFont(size=16, weight="bold"),
        )
        self._month_lbl.grid(row=0, column=1, pady=8)

        ctk.CTkButton(
            nav, text="▶", width=36,
            command=self._next_month,
            fg_color=CARD_2, hover_color="#1f2937",
            border_color=BORDER, border_width=1, text_color=TEXT,
            corner_radius=8,
        ).grid(row=0, column=2, padx=(0, 6), pady=8)

        ctk.CTkButton(
            nav, text="Hoy",
            command=self._go_today,
            fg_color=ACCENT, hover_color=ACCENT_2,
            height=32, corner_radius=8,
        ).grid(row=0, column=3, padx=(0, 12), pady=8)

    def _build_body(self) -> None:
        """Construye el área principal: grid calendario + panel de detalle."""
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=1)

        # ── Grid del calendario ───────────────────────────────────────────────
        self._cal_frame = ctk.CTkFrame(
            body, fg_color=CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        self._cal_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # ── Panel de detalle ──────────────────────────────────────────────────
        detail_outer = ctk.CTkFrame(
            body, fg_color=CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        detail_outer.grid(row=0, column=1, sticky="nsew")
        detail_outer.grid_rowconfigure(1, weight=1)
        detail_outer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            detail_outer, text="Detalle del día",
            text_color=MUTED, font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        self._detail_box = ctk.CTkScrollableFrame(
            detail_outer, fg_color="transparent",
            scrollbar_button_color="#1f4a26",
            scrollbar_button_hover_color=ACCENT,
            scrollbar_fg_color="#0a1e0c",
        )
        self._detail_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self._detail_lbl = ctk.CTkLabel(
            self._detail_box,
            text="Selecciona un día del calendario",
            text_color=MUTED, font=ctk.CTkFont(size=11),
            wraplength=200,
        )
        self._detail_lbl.pack(anchor="w", padx=4, pady=4)

    # ── Datos ─────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        picks = self.app.storage.load_model_picks()
        by_date: dict[str, list[dict]] = defaultdict(list)
        for p in picks:
            d = str(p.get("date", ""))[:10]
            if d:
                by_date[d].append(p)

        # ── Fixtures futuros del último análisis ──────────────────────────────
        results = getattr(self.app, "results", None)
        today_str = str(date.today())
        if results is not None and not results.empty:
            for _, row in results.iterrows():
                d = str(row.get("date", ""))[:10]
                if not d or d < today_str:
                    continue
                # Evitar duplicar si ya existe un pick registrado para el mismo partido/día
                existing = {
                    (p.get("home_team", ""), p.get("away_team", ""))
                    for p in by_date.get(d, [])
                    if p.get("status") != "FIXTURE"
                }
                ht = str(row.get("home_team", ""))
                at = str(row.get("away_team", ""))
                if (ht, at) in existing:
                    continue
                try:
                    edge = float(row.get("edge_1x2") or row.get("edge") or 0)
                except Exception:
                    edge = 0.0
                # Normalizar la hora (puede venir como "12:30:00", "12:30", NaN, etc.)
                raw_time = row.get("time", "") or ""
                try:
                    time_str = str(raw_time).strip()
                    # Quitar segundos si vienen en formato HH:MM:SS
                    if time_str.count(":") == 2:
                        time_str = time_str[:5]
                    # Descartar valores que no parezcan hora
                    if len(time_str) not in (4, 5) or ":" not in time_str:
                        time_str = ""
                except Exception:
                    time_str = ""

                by_date[d].append({
                    "_type":    "fixture",
                    "status":   "FIXTURE",
                    "home_team": ht,
                    "away_team": at,
                    "pick":      str(row.get("pick", "")),
                    "league":    str(row.get("league", row.get("div", ""))),
                    "date":      d,
                    "time":      time_str,
                    "p_home":    float(row.get("p_home") or 0),
                    "p_draw":    float(row.get("p_draw") or 0),
                    "p_away":    float(row.get("p_away") or 0),
                    "edge":      edge,
                    "reliability_score": float(row.get("reliability_score") or 0),
                })

        self._picks_by_date = dict(by_date)
        self._render_calendar()

    # ── Renderizado ───────────────────────────────────────────────────────────

    def _render_calendar(self) -> None:
        """Redibuja el grid del mes actual."""
        for w in self._cal_frame.winfo_children():
            w.destroy()
        self._day_frames = {}

        month_name = [
            "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ][self._month]
        self._month_lbl.configure(text=f"{month_name} {self._year}")

        # Cabeceras de días de la semana
        for col, name in enumerate(_DAY_NAMES):
            color = "#ef4444" if col >= 5 else MUTED
            ctk.CTkLabel(
                self._cal_frame, text=name,
                text_color=color, font=ctk.CTkFont(size=10, weight="bold"),
            ).grid(row=0, column=col, padx=4, pady=(8, 4), sticky="ew")

        # Calcular primer día y total de días
        first_wd, n_days = calendar.monthrange(self._year, self._month)
        # Python: lunes=0, domingo=6 — ajustamos para mostrar Lun-Dom
        start_col = first_wd  # ya en formato lunes=0

        day = 1
        for cell in range(start_col, start_col + n_days):
            row = cell // 7 + 1
            col = cell % 7
            d_str = f"{self._year}-{self._month:02d}-{day:02d}"
            self._render_day_cell(d_str, day, row, col)
            day += 1

        # Ajuste de peso de columnas
        for i in range(7):
            self._cal_frame.grid_columnconfigure(i, weight=1)

    def _render_day_cell(self, d_str: str, day_num: int, row: int, col: int) -> None:
        picks = self._picks_by_date.get(d_str, [])
        is_today = (d_str == str(self._today))
        is_sel   = (d_str == self._selected_date)
        is_past  = (d_str < str(self._today))

        # Color de fondo de la celda
        if is_today:
            cell_bg = "#0f3320"
            border  = ACCENT
        elif is_sel:
            cell_bg = "#0c1f38"
            border  = "#60a5fa"
        else:
            cell_bg = "#08160a" if is_past else "#0a1e0c"
            border  = "#1a3320" if picks else "#0d2010"

        cell = ctk.CTkFrame(
            self._cal_frame,
            fg_color=cell_bg,
            corner_radius=8,
            border_color=border,
            border_width=1 if (is_today or is_sel or picks) else 0,
            cursor="hand2" if picks else "",
        )
        cell.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
        self._cal_frame.grid_rowconfigure(row, weight=1)
        self._day_frames[d_str] = cell

        # Número del día
        day_color = ACCENT if is_today else (TEXT if picks else "#3a5a3a")
        day_font  = ctk.CTkFont(size=13, weight="bold") if is_today else ctk.CTkFont(size=12)
        ctk.CTkLabel(
            cell, text=str(day_num),
            text_color=day_color, font=day_font,
        ).pack(anchor="w", padx=6, pady=(4, 0))

        # Badges de picks (máx 3 puntos de color)
        if picks:
            dot_row = ctk.CTkFrame(cell, fg_color="transparent")
            dot_row.pack(anchor="w", padx=6, pady=(0, 2))

            # Agrupar fixtures y picks normales
            fixtures   = [p for p in picks if p.get("status") == "FIXTURE"]
            non_fix    = [p for p in picks if p.get("status") != "FIXTURE"]

            status_counts: dict[str, int] = {}
            for p in non_fix:
                s = p.get("status", "PENDING")
                status_counts[s] = status_counts.get(s, 0) + 1

            # Badges de picks normales
            for status, cnt in list(status_counts.items())[:2]:
                color = _STATUS_COLOR.get(status, MUTED)
                ctk.CTkLabel(
                    dot_row,
                    text=f"● {cnt}" if cnt > 1 else "●",
                    text_color=color,
                    font=ctk.CTkFont(size=9),
                ).pack(side="left", padx=1)

            # Badge de fixtures con hora si solo hay uno
            if fixtures:
                color = _STATUS_COLOR["FIXTURE"]
                if len(fixtures) == 1:
                    t = fixtures[0].get("time", "")
                    dot_text = f"⚽ {t}" if t else "⚽"
                else:
                    dot_text = f"⚽ {len(fixtures)}"
                ctk.CTkLabel(
                    dot_row,
                    text=dot_text,
                    text_color=color,
                    font=ctk.CTkFont(size=9),
                ).pack(side="left", padx=1)

        # Click handler
        if picks:
            cell.bind("<Button-1>", lambda _e, d=d_str: self._on_day_click(d))
            for child in cell.winfo_children():
                child.bind("<Button-1>", lambda _e, d=d_str: self._on_day_click(d))

    # ── Interacción ───────────────────────────────────────────────────────────

    def _on_day_click(self, d_str: str) -> None:
        self._selected_date = d_str
        self._render_calendar()
        self._show_day_detail(d_str)

    def _show_day_detail(self, d_str: str) -> None:
        """Muestra los picks del día seleccionado en el panel derecho."""
        for w in self._detail_box.winfo_children():
            w.destroy()

        picks = self._picks_by_date.get(d_str, [])
        if not picks:
            ctk.CTkLabel(
                self._detail_box,
                text="Sin picks este día",
                text_color=MUTED, font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=4, pady=4)
            return

        # Cabecera del día
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            day_name = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][dt.weekday()]
            header = f"{day_name} {dt.day} de {['','Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][dt.month]}"
        except Exception:
            header = d_str

        ctk.CTkLabel(
            self._detail_box, text=header,
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=4, pady=(4, 8))

        # Totales del día (los FIXTURE no tienen P&L real)
        non_fixture = [p for p in picks if p.get("status") != "FIXTURE"]
        fixtures    = [p for p in picks if p.get("status") == "FIXTURE"]
        total_pnl = sum(float(p.get("pnl") or 0) for p in non_fixture if p.get("status") in ("WIN","LOSS"))
        bankroll = max(0.0, float(self.app.bankroll_eur.get() or 0))

        wins   = sum(1 for p in non_fixture if p.get("status") == "WIN")
        losses = sum(1 for p in non_fixture if p.get("status") == "LOSS")
        pend   = sum(1 for p in non_fixture if p.get("status") == "PENDING")
        fix_n  = len(fixtures)

        summary_color = ACCENT if total_pnl >= 0 else "#ef4444"
        pnl_display = (
            f"{total_pnl * bankroll:+.2f}€" if bankroll > 0
            else f"{total_pnl:+.4f}u"
        )
        fix_part = f"  ⚽ {fix_n}" if fix_n else ""
        pnl_part = f"   P&L: {pnl_display}" if non_fixture else ""

        ctk.CTkLabel(
            self._detail_box,
            text=f"✅ {wins}  ❌ {losses}  ⏳ {pend}{fix_part}{pnl_part}",
            text_color=summary_color, font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=4, pady=(0, 8))

        # Separador
        ctk.CTkFrame(
            self._detail_box, height=1,
            fg_color=BORDER,
        ).pack(fill="x", padx=4, pady=(0, 8))

        # Cards de picks
        for p in picks:
            self._render_pick_card(p)

    def _render_fixture_card(self, p: dict) -> None:
        """Tarjeta especial para fixtures del análisis (aún no apostados)."""
        color = _STATUS_COLOR["FIXTURE"]   # #a78bfa morado
        bg    = _STATUS_BG["FIXTURE"]      # #1a0a38

        card = ctk.CTkFrame(
            self._detail_box, fg_color=bg, corner_radius=8,
            border_color=color, border_width=1,
        )
        card.pack(fill="x", padx=4, pady=3)

        home   = str(p.get("home_team", ""))
        away   = str(p.get("away_team", ""))
        pick   = str(p.get("pick", ""))
        league = str(p.get("league", ""))
        time_  = str(p.get("time", ""))
        p_h    = p.get("p_home", 0.0)
        p_d    = p.get("p_draw", 0.0)
        p_a    = p.get("p_away", 0.0)
        edge   = p.get("edge", 0.0)
        rel    = p.get("reliability_score", 0.0)

        # Liga + hora + icono
        parts = []
        if league:
            parts.append(league)
        if time_:
            parts.append(f"🕐 {time_}")
        header_text = "⚽  " + "  ·  ".join(parts) if parts else "⚽  Análisis IA"
        ctk.CTkLabel(
            card,
            text=header_text,
            text_color=color, font=ctk.CTkFont(size=9),
        ).pack(anchor="w", padx=8, pady=(5, 0))

        # Partido
        ctk.CTkLabel(
            card,
            text=f"{home[:17]} vs {away[:17]}",
            text_color=TEXT, font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(1, 0))

        # Pick + probabilidades
        probs_str = f"1:{p_h*100:.0f}%  X:{p_d*100:.0f}%  2:{p_a*100:.0f}%"
        edge_str  = f"  edge {edge*100:+.1f}%" if edge else ""
        ctk.CTkLabel(
            card,
            text=f"Pick: {pick}   {probs_str}{edge_str}",
            text_color="#c4b5fd", font=ctk.CTkFont(size=9),
        ).pack(anchor="w", padx=8, pady=(0, 5))

    def _render_pick_card(self, p: dict) -> None:
        """Renderiza una tarjeta de pick en el panel de detalle."""
        status = p.get("status", "PENDING")

        # Los fixtures tienen su propio card
        if status == "FIXTURE":
            self._render_fixture_card(p)
            return

        color   = _STATUS_COLOR.get(status, MUTED)
        bg      = _STATUS_BG.get(status, CARD)
        icon    = {"WIN": "✅", "LOSS": "❌", "VOID": "⬜", "PENDING": "⏳"}.get(status, "⏳")

        card = ctk.CTkFrame(
            self._detail_box, fg_color=bg, corner_radius=8,
            border_color=color, border_width=1,
        )
        card.pack(fill="x", padx=4, pady=3)

        home  = str(p.get("home_team", ""))
        away  = str(p.get("away_team", ""))
        pick  = str(p.get("pick", ""))
        odds  = p.get("odds")
        pnl   = p.get("pnl") or 0.0
        bankroll = max(0.0, float(self.app.bankroll_eur.get() or 0))

        # Línea 1: partido
        ctk.CTkLabel(
            card,
            text=f"{home[:18]} vs {away[:18]}",
            text_color=TEXT, font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(6, 0))

        # Línea 2: pick, cuota, estado, P&L
        odds_str = f"@ {float(odds):.2f}" if odds else ""
        pnl_str  = ""
        if status in ("WIN", "LOSS"):
            pnl_val  = pnl * bankroll if bankroll > 0 else pnl
            pnl_unit = "€" if bankroll > 0 else "u"
            pnl_str  = f"  {pnl_val:+.2f}{pnl_unit}"

        ctk.CTkLabel(
            card,
            text=f"{icon} {pick} {odds_str}{pnl_str}",
            text_color=color, font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=8, pady=(0, 6))

    # ── Navegación de mes ─────────────────────────────────────────────────────

    def _prev_month(self) -> None:
        self._month -= 1
        if self._month < 1:
            self._month = 12
            self._year -= 1
        self._selected_date = None
        self._render_calendar()

    def _next_month(self) -> None:
        self._month += 1
        if self._month > 12:
            self._month = 1
            self._year += 1
        self._selected_date = None
        self._render_calendar()

    def _go_today(self) -> None:
        self._year  = self._today.year
        self._month = self._today.month
        self._selected_date = str(self._today)
        self._render_calendar()
        self._show_day_detail(str(self._today))
