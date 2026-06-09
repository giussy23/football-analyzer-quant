# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
app.py — Clase principal PremiumApp: orquesta vistas, lógica y datos.
"""

from __future__ import annotations

import logging
import math
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk
import numpy as np
import pandas as pd
import requests
from tkinter import ttk

from .core.analyzer import Analyzer
from .core.config import (
    ACCENT, ACCENT_2, BG, BORDER, CARD, CARD_2,
    FIXTURES_URL, LEAGUE_MAP, MUTED, TEXT,
)
from .core.data import fetch_csv
from .core.injury_adjuster import InjuryAdjuster
try:
    from .core.weather import get_match_weather as _get_weather
    _WEATHER_AVAILABLE = True
except ImportError:
    _WEATHER_AVAILABLE = False
from .core.odds_api import fetch_odds_fixtures
from .core.storage import Storage
from .ui.views.accumulator import AccumulatorView
from .ui.views.alerts import AlertsView
from .ui.views.quiniela import QuinielaView
from .ui.views.analysis import AnalysisView
from .ui.views.portfolio import ExecutionView, PortfolioView
from .ui.views.results import ResultsView
from .ui.views.settings import SettingsView
from .ui.views.chat import ChatView
from .ui.views.live_scores import LiveScoresView
from .ui.views.calendar_view import CalendarView
from .ui.views.performance import PerformanceView

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


class PremiumApp(ctk.CTk):
    """Aplicación principal AlphaBet v15.0."""

    def __init__(self) -> None:
        super().__init__()
        self.storage = Storage()

        self.title("AlphaBet v15.0")
        self.configure(fg_color=BG)

        # ── Tamaño inicial adaptado a la resolución de pantalla ───────────────
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # NUNCA exceder la pantalla: h siempre ≤ sh-80 para dejar barra de tareas
        w  = min(sw - 20,  1780)
        h  = min(sh - 80,  1040)
        # Mínimos razonables (pueden ser menores que la pantalla en monitores muy pequeños)
        w  = max(w, min(1100, sw - 10))
        h  = max(h, min(600,  sh - 40))
        x  = max(0, (sw - w) // 2)
        y  = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(900, 560)

        # Maximizar automáticamente en Windows (se llama después del event-loop,
        # para que tkinter ya haya colocado la ventana correctamente)
        self.after(50, self._try_maximize)

        # ── Icono de ventana ──────────────────────────────────────────────────
        import os as _os
        _icon = _os.path.join(_os.path.dirname(__file__), "assets", "alphabet_icon.ico")
        if _os.path.exists(_icon):
            try:
                self.iconbitmap(_icon)
            except Exception:
                pass

        # ── Telegram bot ──────────────────────────────────────────────────────
        self._tg_bot: Optional[object] = None   # TelegramBot, importado tarde
        self._last_analysis_ts: str = "—"
        # Caché thread-safe: se rellena en el hilo principal, lo lee el hilo del bot
        self._bot_cache: dict = {}

        # ── Módulos nuevos v13 ────────────────────────────────────────────────
        self.line_monitor: Optional[object] = None  # LineMonitor (arranca on-demand)
        self.injury_adjuster: InjuryAdjuster = InjuryAdjuster()
        # Caché xG Understat: {div → {team → {xg, xga, npxg, matches}}}
        self._understat_cache: dict[str, dict] = {}

        # ── State ─────────────────────────────────────────────────────────────
        self.results:          pd.DataFrame = pd.DataFrame()
        self.filtered:         pd.DataFrame = pd.DataFrame()
        self.backtest_summary: dict         = {}
        self.diagnostics:      list[str]    = []
        self.history:          list[dict]   = self.storage.load_combos()
        self.bet_sim_history:  list[dict]   = self.storage.load_sims()
        self.odds_api_remaining:  Optional[str] = None
        self._analysis_running:   bool          = False

        # ── Settings vars ─────────────────────────────────────────────────────
        def _sv(key: str, default: str) -> tk.StringVar:
            return tk.StringVar(value=self.storage.get_setting(key, default))

        def _bv(key: str, default: str = "0") -> tk.BooleanVar:
            return tk.BooleanVar(value=self.storage.get_setting(key, default) == "1")

        self.edge1        = _sv("edge1",        "0.03")
        self.edge2        = _sv("edge2",        "0.03")
        self.unit_stake   = _sv("unit_stake",   "100")
        self.bankroll_eur = _sv("bankroll_eur", "0")    # banca total en euros (para P&L real)
        self.search_var  = tk.StringVar()
        self.only_green  = _bv("only_green",  "1")
        self.only_picks  = _bv("only_picks",  "0")

        self.use_odds_api            = _bv("use_odds_api",            "0")
        self.use_claude_analysis     = _bv("use_claude_analysis",     "0")
        self.use_injury_api          = _bv("use_injury_api",          "0")
        self.telegram_enabled        = _bv("telegram_enabled",        "0")
        self.send_combo_enabled      = _bv("send_combo_enabled",      "1")
        self.auto_send_after_analysis = _bv("auto_send_after_analysis", "0")

        self.combo_size = tk.IntVar(
            value=int(self.storage.get_setting("combo_size", "2"))
        )

        # Simulator vars (set later by ExecutionView)
        self.sim_match_var   = tk.StringVar()
        self.manual_pick_var = tk.StringVar(value="1")
        self.manual_odds_var = tk.StringVar(value="0.00")
        self.manual_stake_var = tk.StringVar(value="10")
        self.sim_result_var  = tk.StringVar(value="PENDING")

        self._setup_style()
        self._build_ui()
        self._refresh_portfolio()

        # Poblar historial de simulaciones desde la DB al arrancar
        if self.bet_sim_history:
            self.execution_view.refresh_history_panel(self.bet_sim_history)
            self.execution_view.refresh_stats(self.bet_sim_history)

        # Verificar frescura de datos al arrancar
        self.after(500, self._check_data_freshness)

    def _try_maximize(self) -> None:
        """Maximiza la ventana en Windows; en otros OS la deja al tamaño calculado."""
        try:
            self.state("zoomed")        # Windows
        except Exception:
            try:
                self.attributes("-zoomed", True)   # Linux (algunos WM)
            except Exception:
                pass                    # macOS: no existe, se queda al tamaño calculado

    def _update_claude_counter(self) -> None:
        """Refresca el contador de uso de Claude IA en el sidebar."""
        from .core.ai_analysis import get_session_usage
        u = get_session_usage()
        calls = u["calls"]
        cost  = u["cost_usd"]
        model = u["model"]

        # Color según gasto: verde → amarillo → naranja
        if cost == 0:
            cost_color = MUTED
        elif cost < 0.10:
            cost_color = ACCENT
        elif cost < 0.50:
            cost_color = "#fbbf24"   # amarillo
        else:
            cost_color = "#f97316"   # naranja

        # Formato inteligente: muestra decimales suficientes
        if cost == 0:
            cost_str = "$0.00"
        elif cost < 0.01:
            cost_str = f"${cost:.4f}"
        else:
            cost_str = f"${cost:.2f}"

        self.claude_cost_lbl.configure(text=cost_str, text_color=cost_color)
        self.claude_counter_lbl.configure(
            text=f"  ·  {calls} llamada{'s' if calls != 1 else ''}",
            text_color=cost_color if calls > 0 else MUTED,
        )
        # Modelo: extraer la familia (haiku, sonnet, opus) del nombre completo
        short = "—"
        if calls > 0 and model != "—":
            m = model.lower()
            if "haiku"  in m: short = "haiku"
            elif "sonnet" in m: short = "sonnet"
            elif "opus"   in m: short = "opus"
            else:
                parts = model.split("-")
                short = parts[-1] if parts else model
        self.claude_model_lbl.configure(text=short, text_color=MUTED)

    def _update_api_counter(self) -> None:
        """Refresca el contador de peticiones en el sidebar."""
        remaining = self.odds_api_remaining
        if remaining is None:
            text  = "— / 500 req."
            color = MUTED
        else:
            n = int(remaining)
            text  = f"{n} / 500 restantes"
            color = "#00c853" if n > 100 else "#ffd600" if n > 20 else "#ff5252"
        self.api_counter_lbl.configure(text=text, text_color=color)

    # ── Style ─────────────────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#050e1c", fieldbackground="#050e1c",
            foreground="#e0f2fe", rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#030a16", foreground="#e0f2fe",
            font=("Segoe UI Semibold", 10),
        )
        style.map("Treeview", background=[("selected", "#0e3a4a")])

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_stage()

        self.show_analysis_view()

    def _build_pitch_bg(self) -> None:
        """
        Canvas de fondo que rellena la ventana con el color BG del campo.

        Usa tk.Misc.lower() (no Canvas.lower(), que es para items canvas)
        para quedar DETRÁS de todos los demás widgets. Los CTkFrames con
        fg_color='transparent' muestran este fondo en lugar de negro puro.
        """
        W = self.winfo_screenwidth()
        H = self.winfo_screenheight()
        GD = "#093d18"   # verde oscuro del césped
        GL = "#0b5c22"   # verde claro (franjas alternas)

        c = tk.Canvas(self, width=W, height=H, bg="#020810",
                      highlightthickness=0, bd=0)
        c.place(x=0, y=0, relwidth=1, relheight=1)

        # Cuadrícula de puntos (estilo terminal financiero)
        spacing = 50
        for x in range(0, W, spacing):
            for y in range(0, H, spacing):
                c.create_oval(x-1, y-1, x+1, y+1,
                              fill="#0d1e33", outline="")

        # Líneas horizontales muy tenues
        for y in range(0, H, 80):
            c.create_line(0, y, W, y, fill="#090f1c", width=1)

        # Poner el canvas DETRÁS de todos los demás widgets
        tk.Misc.lower(c)

    def _draw_logo_header(self, parent) -> tk.Canvas:
        """Logo galáctico: fondo PNG con nebulosa+estrellas + colas de cometa animadas."""
        import os
        from PIL import Image, ImageTk

        W, H = 210, 248
        cx, cy = W // 2, 96   # centro del símbolo α en el PNG

        # ── Fondo: PNG PIL (fondo galáctico + α con glow) ────────────────────
        logo_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "sidebar_logo.png"
        )
        if not os.path.exists(logo_path):
            try:
                import sys as _sys
                _sys.path.insert(0, os.path.dirname(logo_path))
                from generate_logo import generate_sidebar_logo
                generate_sidebar_logo(logo_path)
            except Exception:
                pass

        c = tk.Canvas(parent, width=W, height=H,
                      highlightthickness=0, bd=0, bg="#02060e")
        try:
            pil_img = Image.open(logo_path)
            photo   = ImageTk.PhotoImage(pil_img)
            c._bg_photo = photo
            c.create_image(0, 0, anchor="nw", image=photo)
        except Exception:
            c.create_text(cx, cy, text="α", font=("Georgia", 42, "bold italic"),
                          fill="#34d399", anchor="center")

        # ── Función: elipse inclinada como polígono suave ─────────────────────
        def _draw_orbit_ring(ea, eb, tilt_deg, color, w=1):
            rot = math.radians(tilt_deg)
            pts = []
            for deg in range(362):
                t = math.radians(deg)
                ux = ea * math.cos(t);  uy = eb * math.sin(t)
                pts += [cx + ux*math.cos(rot) - uy*math.sin(rot),
                        cy + ux*math.sin(rot) + uy*math.cos(rot)]
            c.create_polygon(pts, outline=color, fill="", width=w, smooth=True)

        _draw_orbit_ring(74, 22,  28, "#163f2c")
        _draw_orbit_ring(58, 20, -42, "#12304a")

        # ── Cola de cometa: genera N colores interpolando a negro ─────────────
        TAIL = 10

        def _tail_palette(r1, g1, b1):
            return ["#{:02x}{:02x}{:02x}".format(
                max(0, int(r1 * (1 - i / (TAIL - 1)) ** 1.6)),
                max(0, int(g1 * (1 - i / (TAIL - 1)) ** 1.6)),
                max(0, int(b1 * (1 - i / (TAIL - 1)) ** 1.6)),
            ) for i in range(TAIL)]

        def _tail_sizes(head_r):
            return [max(0.3, head_r * (1 - i / (TAIL - 1)) ** 0.9)
                    for i in range(TAIL)]

        PAL_1A = _tail_palette(56, 189, 248)    # cyan brillante
        PAL_1B = _tail_palette(125, 211, 250)   # cyan claro
        PAL_2  = _tail_palette(74, 222, 128)    # verde
        SZ_BIG = _tail_sizes(3.8)
        SZ_MED = _tail_sizes(3.0)
        SZ_GRN = _tail_sizes(2.8)

        # ── Pre-crear todos los ítems de cola + cabeza + glow ────────────────
        p1a_tail = [c.create_oval(0,0,0,0, fill=col, outline="") for col in PAL_1A]
        p1b_tail = [c.create_oval(0,0,0,0, fill=col, outline="") for col in PAL_1B]
        p2_tail  = [c.create_oval(0,0,0,0, fill=col, outline="") for col in PAL_2]

        p1a_g = c.create_oval(0,0,0,0, fill="#04232f", outline="")
        p1a   = c.create_oval(0,0,0,0, fill="#38bdf8", outline="")
        p1b_g = c.create_oval(0,0,0,0, fill="#04232f", outline="")
        p1b   = c.create_oval(0,0,0,0, fill="#7dd3fa", outline="")
        p2_g  = c.create_oval(0,0,0,0, fill="#042518", outline="")
        p2    = c.create_oval(0,0,0,0, fill="#4ade80", outline="")

        # Anillo pulsante alrededor de α (halo de energía)
        pulse = c.create_oval(cx-42, cy-42, cx+42, cy+42,
                              outline="#0d3d2c", fill="", width=1)

        def _pos(ea, eb, tilt_deg, angle):
            rot = math.radians(tilt_deg)
            ux = ea * math.cos(angle);  uy = eb * math.sin(angle)
            return (cx + ux*math.cos(rot) - uy*math.sin(rot),
                    cy + ux*math.sin(rot) + uy*math.cos(rot))

        def _place(item, x, y, r):
            c.coords(item, x - r, y - r, x + r, y + r)

        def _hide(item):
            c.coords(item, -10, -10, -9, -9)

        anim_id = [None]

        def _animate(t=0.0):
            step1 = 0.042 * 1.15   # incremento angular por frame órbita 1
            step2 = 0.042 * 0.80   # incremento angular por frame órbita 2

            # ── Órbita 1 – partícula A (cyan) con cola ──
            ang1a = t * 1.15
            for i, (item, sz) in enumerate(zip(p1a_tail, SZ_BIG)):
                xp, yp = _pos(74, 22, 28, ang1a - i * step1)
                _place(item, xp, yp, sz)
            x1a, y1a = _pos(74, 22, 28, ang1a)
            _place(p1a_g, x1a, y1a, 8);   _place(p1a, x1a, y1a, 3.8)

            # ── Órbita 1 – partícula B (180° opuesta) con cola ──
            ang1b = ang1a + math.pi
            for i, (item, sz) in enumerate(zip(p1b_tail, SZ_MED)):
                xp, yp = _pos(74, 22, 28, ang1b - i * step1)
                _place(item, xp, yp, sz)
            x1b, y1b = _pos(74, 22, 28, ang1b)
            _place(p1b_g, x1b, y1b, 7);   _place(p1b, x1b, y1b, 3.0)

            # ── Órbita 2 – partícula verde (sentido contrario) con cola ──
            ang2 = -t * 0.80 + 0.8
            for i, (item, sz) in enumerate(zip(p2_tail, SZ_GRN)):
                xp, yp = _pos(58, 20, -42, ang2 + i * step2)  # cola en sentido +
                _place(item, xp, yp, sz)
            x2, y2 = _pos(58, 20, -42, ang2)
            _place(p2_g, x2, y2, 7);      _place(p2, x2, y2, 2.8)

            # ── Anillo pulsante ──
            pr = 42 + 7 * math.sin(t * 0.48)
            ri = int(13 + 20 * (math.sin(t * 0.48) * 0.5 + 0.5))
            rg = int(50 + 48 * (math.sin(t * 0.48) * 0.5 + 0.5))
            rb = int(38 + 36 * (math.sin(t * 0.48) * 0.5 + 0.5))
            c.coords(pulse, cx - pr, cy - pr, cx + pr, cy + pr)
            c.itemconfig(pulse, outline=f"#{ri:02x}{rg:02x}{rb:02x}")

            anim_id[0] = c.after(33, lambda: _animate(t + 0.042))

        c.bind("<Destroy>",
               lambda e: c.after_cancel(anim_id[0]) if anim_id[0] else None)
        _animate()
        return c

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self, fg_color="#040c18", width=240,
            corner_radius=20, border_color="#0d9488", border_width=1,
        )
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(14, 10), pady=14)
        sidebar.grid_propagate(False)

        # ── Contenedor scrollable ─────────────────────────────────────────────
        inner = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent",
            scrollbar_button_color="#0e4d6c",
            scrollbar_button_hover_color="#0891b2",
            scrollbar_fg_color="#050e1c",
        )
        inner.pack(fill="both", expand=True, padx=0, pady=0)

        # ── Logo AlphaBet ──────────────────────────────────────────────────────
        logo_wrap = ctk.CTkFrame(inner, fg_color="#080f0a", corner_radius=10)
        logo_wrap.pack(fill="x", padx=8, pady=(10, 4))
        self._draw_logo_header(logo_wrap).pack(padx=2, pady=4)

        # ── Navegación ─────────────────────────────────────────────────────────
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("analysis",    "📊  Trading Desk",   self.show_analysis_view),
            ("accumulator", "⚡  Combinadas IA",  self.show_accumulator_view),
            ("quiniela",    "⚽  Quiniela IA",    self.show_quiniela_view),
            ("alerts",      "🔔  Alertas",        self.show_alerts_view),
            ("results",     "📋  Resultados",     self.show_results_view),
            ("live",        "🟢  Live Scores",    self.show_live_view),
            ("calendar",    "📅  Calendario",     self.show_calendar_view),
            ("execution",   "🎯  Manual Slip",    self.show_execution_view),
            ("portfolio",    "📈  Portfolio",      self.show_portfolio_view),
            ("performance", "📉  Performance",    self.show_performance_view),
            ("chat",        "🧠  Chat IA",        self.show_chat_view),
            ("settings",    "⚙️  Strategy",       self.show_settings_view),
        ]
        for key, label, cmd in nav_items:
            btn = ctk.CTkButton(
                inner, text=label, command=cmd,
                fg_color="#060f1e", hover_color="#0a1830",
                text_color="#7eb8cc",
                anchor="w", height=40,
                corner_radius=10,
                font=ctk.CTkFont(size=12),
                border_spacing=8,
            )
            btn.pack(fill="x", padx=12, pady=3)
            self._nav_btns[key] = btn

        self._run_btn = ctk.CTkButton(
            inner, text="▶  Run Analysis",
            command=self.run_analysis,
            fg_color="#0e7490", hover_color="#0891b2",
            height=46, corner_radius=12,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e0f2fe",
        )
        self._run_btn.pack(fill="x", padx=12, pady=(16, 4))

        # ── Barra de progreso ──────────────────────────────────────────────────
        prog_card = ctk.CTkFrame(
            inner, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        prog_card.pack(fill="x", padx=14, pady=(0, 6))
        prog_card.grid_columnconfigure(0, weight=1)

        prog_header = ctk.CTkFrame(prog_card, fg_color="transparent")
        prog_header.pack(fill="x", padx=10, pady=(8, 4))
        prog_header.grid_columnconfigure(0, weight=1)

        self._prog_lbl = ctk.CTkLabel(
            prog_header, text="Listo",
            text_color=MUTED, font=ctk.CTkFont(size=10), anchor="w",
        )
        self._prog_lbl.pack(side="left", fill="x", expand=True)

        self._prog_pct = ctk.CTkLabel(
            prog_header, text="",
            text_color=ACCENT, font=ctk.CTkFont(size=10, weight="bold"),
            width=34, anchor="e",
        )
        self._prog_pct.pack(side="right")

        self._progress_bar = ctk.CTkProgressBar(
            prog_card, height=7, corner_radius=4,
            fg_color="#060f1e", progress_color=ACCENT,
            mode="determinate",
        )
        self._progress_bar.set(0)
        self._progress_bar.pack(fill="x", padx=10, pady=(0, 10))

        # ── Contador Odds API ──────────────────────────────────────────────────
        api_card = ctk.CTkFrame(
            inner, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        api_card.pack(fill="x", padx=14, pady=(8, 2))
        ctk.CTkLabel(
            api_card, text="⚡ Odds API",
            text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.api_counter_lbl = ctk.CTkLabel(
            api_card, text="— / 500 req.",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        )
        self.api_counter_lbl.pack(anchor="w", padx=10, pady=(0, 8))

        # ── Contador Claude IA ─────────────────────────────────────────────────
        claude_card = ctk.CTkFrame(
            inner, fg_color=CARD, corner_radius=10,
            border_color=BORDER, border_width=1,
        )
        claude_card.pack(fill="x", padx=14, pady=(2, 14))

        # Fila 1: título + modelo
        _cc_row1 = ctk.CTkFrame(claude_card, fg_color="transparent")
        _cc_row1.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            _cc_row1, text="🧠 Claude IA",
            text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        self.claude_model_lbl = ctk.CTkLabel(
            _cc_row1, text="—",
            text_color=MUTED, font=ctk.CTkFont(size=9),
        )
        self.claude_model_lbl.pack(side="right")

        # Fila 2: coste (destacado) + llamadas en la misma línea
        _cc_row2 = ctk.CTkFrame(claude_card, fg_color="transparent")
        _cc_row2.pack(fill="x", padx=10, pady=(0, 8))
        self.claude_cost_lbl = ctk.CTkLabel(
            _cc_row2, text="$0.00",
            text_color=MUTED,
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.claude_cost_lbl.pack(side="left")
        self.claude_counter_lbl = ctk.CTkLabel(
            _cc_row2, text="  ·  0 llamadas",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        self.claude_counter_lbl.pack(side="left")

    def _build_stage(self) -> None:
        stage = ctk.CTkFrame(self, fg_color="transparent")
        stage.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        stage.grid_rowconfigure(2, weight=1)   # row 2 = content (expandable)
        stage.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(stage, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.grid_columnconfigure(0, weight=1)

        self.view_title = ctk.CTkLabel(
            header, text="Analysis", text_color="#f0fff4",
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        self.view_title.grid(row=0, column=0, sticky="w")
        self.view_hint = ctk.CTkLabel(
            header, text="Solo próximos partidos, filtros y picks",
            text_color="#4ade80",
            font=ctk.CTkFont(size=11),
        )
        self.view_hint.grid(row=1, column=0, sticky="w", pady=(2, 0))
        # Separador visual bajo el header
        tk.Frame(header, bg="#1a5c2a", height=1).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

        # ── Ticker de picks (flotando bajo el header) ─────────────────────────
        self._build_ticker(stage)   # ocupa row=1

        content = ctk.CTkFrame(stage, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.analysis_view    = AnalysisView(content, self)
        self.accumulator_view = AccumulatorView(content, self)
        self.quiniela_view    = QuinielaView(content, self)
        self.alerts_view      = AlertsView(content, self)
        self.results_view     = ResultsView(content, self)
        self.live_view        = LiveScoresView(content, self)
        self.calendar_view    = CalendarView(content, self)
        self.execution_view   = ExecutionView(content, self)
        self.portfolio_view   = PortfolioView(content, self)
        self.performance_view = PerformanceView(content, self)
        self.settings_view    = SettingsView(content, self)
        self.chat_view        = ChatView(content, self)

        for view in [self.analysis_view, self.accumulator_view, self.quiniela_view,
                     self.alerts_view, self.results_view, self.live_view,
                     self.calendar_view, self.execution_view,
                     self.portfolio_view, self.performance_view,
                     self.settings_view, self.chat_view]:
            view.grid(row=0, column=0, sticky="nsew")

    # ── Ticker ────────────────────────────────────────────────────────────────

    def _build_ticker(self, parent) -> None:
        """Barra scrolling estilo Sky Sports con los próximos picks."""
        outer = tk.Frame(parent, bg="#060f07", height=28)
        outer.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        outer.grid_propagate(False)

        # Etiqueta fija izquierda: "⚽ LIVE"
        tk.Label(
            outer, text=" ⚽ PICKS ", bg="#0d9488", fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", ipadx=2)

        # Canvas scrollable para el texto
        self._ticker_canvas = tk.Canvas(
            outer, bg="#060f07", height=28,
            highlightthickness=0, bd=0,
        )
        self._ticker_canvas.pack(side="left", fill="both", expand=True)

        self._ticker_text_id = self._ticker_canvas.create_text(
            0, 14,
            text="  —  Sin análisis cargado. Pulsa ▶ Run Analysis para ver picks.  ",
            anchor="w",
            fill="#4ade80",
            font=("Consolas", 10),
        )
        self._ticker_x     = 0.0        # posición X actual del texto
        self._ticker_speed = 2.5        # px por frame
        self._ticker_after: str | None = None
        self._ticker_token: int        = 0   # token de generación — evita loops duplicados
        self._ticker_after = self.after(200, lambda: self._ticker_step(0))

    def _ticker_step(self, token: int = 0) -> None:
        """Mueve el texto del ticker un paso a la izquierda.

        El token evita loops concurrentes: si el token no coincide con
        _ticker_token (incrementado por update_ticker), este callback es
        de una generación anterior y se descarta sin reprogramar.
        """
        if not hasattr(self, "_ticker_canvas"):
            return
        if token != getattr(self, "_ticker_token", 0):
            return  # callback obsoleto — ignorar, NO reprogramar
        try:
            c   = self._ticker_canvas
            cw  = c.winfo_width()
            if cw <= 1:          # todavía no dibujado
                self._ticker_after = self.after(300, lambda: self._ticker_step(token))
                return

            bbox = c.bbox(self._ticker_text_id)
            if not bbox:
                self._ticker_after = self.after(150, lambda: self._ticker_step(token))
                return

            txt_w = bbox[2] - bbox[0]
            self._ticker_x -= self._ticker_speed
            # Reiniciar cuando el texto salga por la izquierda
            if self._ticker_x + txt_w < 0:
                self._ticker_x = cw
            c.coords(self._ticker_text_id, self._ticker_x, 14)
            self._ticker_after = self.after(150, lambda: self._ticker_step(token))  # ~7 fps
        except Exception:
            pass

    def update_ticker(self) -> None:
        """Reconstruye el texto del ticker con los picks del análisis actual."""
        if not hasattr(self, "_ticker_canvas"):
            return
        # Nuevo token → todos los callbacks viejos ya en la event queue
        # verán que su token no coincide y se auto-ignorarán.
        tok = getattr(self, "_ticker_token", 0) + 1
        self._ticker_token = tok
        if getattr(self, "_ticker_after", None):
            try:
                self.after_cancel(self._ticker_after)
            except Exception:
                pass
            self._ticker_after = None
        try:
            df = getattr(self, "filtered", pd.DataFrame())
            if df.empty:
                df = getattr(self, "results", pd.DataFrame())
            if df.empty:
                msg = "   Sin análisis cargado. Pulsa  Run Analysis  para ver picks.   "
            else:
                # Solo picks VERDE y AMARILLO
                if "risk_light" in df.columns:
                    visible = df[df["risk_light"].isin(["VERDE", "AMARILLO"])]
                    if visible.empty:
                        visible = df
                else:
                    visible = df
                parts = []
                for _, row in visible.iterrows():
                    home = str(row.get("home_team", ""))
                    away = str(row.get("away_team", ""))
                    pick = str(row.get("pick", ""))
                    try:
                        odds_str = f"@{float(row.get('odds', 0)):.2f}"
                    except Exception:
                        odds_str = ""
                    try:
                        e_raw = row.get("edge_1x2", None) or row.get("edge", 0)
                        e = float(e_raw or 0)
                        edge_str = f"  edge +{e*100:.1f}%" if e > 0 else ""
                    except Exception:
                        edge_str = ""
                    risk  = str(row.get("risk_light", ""))
                    icon  = "[V]" if risk == "VERDE" else "[A]" if risk == "AMARILLO" else "[ ]"
                    parts.append(
                        f"   {icon} {home}  vs  {away}  |  {pick} {odds_str}{edge_str}   |"
                    )
                msg = "".join(parts) + "        "
            self._ticker_canvas.itemconfigure(self._ticker_text_id, text=msg)
            cw = self._ticker_canvas.winfo_width() or 800
            self._ticker_x = float(cw)
            self._ticker_canvas.coords(self._ticker_text_id, self._ticker_x, 14)
        except Exception:
            pass
        # Reiniciar el loop con el nuevo token — solo este callback continuará
        self._ticker_after = self.after(200, lambda: self._ticker_step(tok))

    # ── Navigation ────────────────────────────────────────────────────────────

    _NAV_META = {
        "analysis":    ("Trading Desk",    "Top picks, mercado, tabla principal y ranking"),
        "accumulator": ("Combinadas IA",   "Combinadas 2-4 legs generadas por el modelo IA"),
        "quiniela":    ("Quiniela IA",     "Picks 1/X/2 con dobles, triples, coste y probabilidad"),
        "alerts":      ("Alertas",         "Monitor de líneas · Steam detection · Ajuste de bajas"),
        "results":     ("Resultados",      "Seguimiento de picks reales · ROI verificado"),
        "live":        ("Live Scores",     "Marcadores en tiempo real · Auto-refresh 60 s · Notificaciones"),
        "calendar":    ("Calendario",      "Vista mensual de picks · Click en un día para ver detalle"),
        "execution":   ("Manual Slip",     "Simulación manual 1X2, cuota, stake y retorno"),
        "portfolio":   ("Portfolio",       "Historial de combinadas, ROI y liquidación"),
        "chat":        ("Chat IA",         "Analista cuantitativo · Pregunta sobre picks, estrategia y bankroll"),
        "settings":    ("Strategy",        "Telegram, combo builder y configuración"),
    }

    def _set_nav(self, active: str) -> None:
        for key, btn in self._nav_btns.items():
            is_active = key == active
            btn.configure(
                fg_color="#0e3a50" if is_active else "#060f1e",
                text_color="#22d3ee" if is_active else TEXT,
                font=ctk.CTkFont(size=12, weight="bold" if is_active else "normal"),
            )
        title, hint = self._NAV_META[active]
        self.view_title.configure(text=title)
        self.view_hint.configure(text=hint)

    def _hide_all(self) -> None:
        for v in [self.analysis_view, self.accumulator_view, self.quiniela_view,
                  self.alerts_view, self.results_view, self.live_view,
                  self.calendar_view, self.execution_view,
                  self.portfolio_view, self.performance_view,
                  self.settings_view, self.chat_view]:
            v.grid_remove()
        # Pausar auto-refresh del live tracker cuando se oculta
        try:
            self.live_view.on_hide()
        except Exception:
            pass

    def show_analysis_view(self):
        self._hide_all(); self.analysis_view.grid(); self._set_nav("analysis")

    def show_accumulator_view(self):
        self._hide_all()
        self.accumulator_view.grid()
        self._set_nav("accumulator")
        # Refrescar DESPUÉS de hacer visible la vista para que CTkScrollableFrame
        # actualice su scrollregion correctamente (evita tarjetas negras)
        try:
            df = getattr(self, "results", pd.DataFrame())
            if not df.empty:
                self.accumulator_view.refresh(df)
        except Exception:
            pass

    def show_quiniela_view(self):
        self._hide_all(); self.quiniela_view.grid(); self._set_nav("quiniela")

    def show_results_view(self):
        self._hide_all(); self.results_view.grid(); self._set_nav("results")

    def show_live_view(self):
        self._hide_all(); self.live_view.grid(); self._set_nav("live")
        try:
            self.live_view.on_show()
        except Exception:
            pass

    def show_calendar_view(self):
        self._hide_all(); self.calendar_view.grid(); self._set_nav("calendar")
        try:
            self.calendar_view.refresh()
        except Exception:
            pass

    def show_execution_view(self):
        self._hide_all(); self.execution_view.grid(); self._set_nav("execution")

    def show_portfolio_view(self):
        self._hide_all(); self.portfolio_view.grid(); self._set_nav("portfolio")
        self._refresh_portfolio()

    def show_performance_view(self):
        self._hide_all(); self.performance_view.grid(); self._set_nav("performance")
        try:
            self.performance_view.refresh()
        except Exception:
            pass

    def show_alerts_view(self):
        self._hide_all(); self.alerts_view.grid(); self._set_nav("alerts")
        self.alerts_view.refresh()

    def show_settings_view(self):
        self._hide_all(); self.settings_view.grid(); self._set_nav("settings")

    def show_chat_view(self, source_view: str = "", prefill: str = "") -> None:
        self._hide_all(); self.chat_view.grid(); self._set_nav("chat")
        try:
            if source_view or prefill:
                self.chat_view.open_with_context(source_view, prefill)
            else:
                self.chat_view.refresh_context()
        except Exception:
            pass

    # ── Settings persistence ──────────────────────────────────────────────────

    def save_settings(self) -> None:
        token   = self.settings_view.get_token()
        chat_id = self.settings_view.get_chat_id()
        payload = {
            "edge1":                    self.edge1.get(),
            "edge2":                    self.edge2.get(),
            "unit_stake":               self.unit_stake.get(),
            "telegram_token":           token,
            "telegram_chat_id":         chat_id,
            "telegram_enabled":         int(self.telegram_enabled.get()),
            "send_combo_enabled":       int(self.send_combo_enabled.get()),
            "auto_send_after_analysis": int(self.auto_send_after_analysis.get()),
            "odds_api_key":             self.settings_view.get_odds_api_key(),
            "use_odds_api":             int(self.use_odds_api.get()),
            "anthropic_api_key":        self.settings_view.get_anthropic_api_key(),
            "use_claude_analysis":      int(self.use_claude_analysis.get()),
            "injury_api_key":           self.settings_view.get_injury_api_key(),
            "use_injury_api":           int(self.use_injury_api.get()),
            "betfair_app_key":          self.settings_view.get_betfair_app_key(),
            "betfair_username":         self.settings_view.get_betfair_username(),
            "betfair_password":         self.settings_view.get_betfair_password(),
            "only_green":               int(self.only_green.get()),
            "only_picks":               int(self.only_picks.get()),
            "combo_size":               self.combo_size.get(),
            "bankroll_eur":             self.settings_view.get_bankroll_eur(),
        }
        for k, v in payload.items():
            self.storage.set_setting(k, v)

    # ── Main analysis pipeline ────────────────────────────────────────────────

    # ── Analysis pipeline (threaded) ──────────────────────────────────────────

    def run_analysis(self) -> None:
        """Punto de entrada — hilo principal. Lanza el worker en segundo plano."""
        if self._analysis_running:
            return  # evitar doble click

        self.save_settings()
        selected = [k for k, v in self.analysis_view.league_vars.items() if v.get()]
        if not selected:
            messagebox.showwarning("Aviso", "Selecciona al menos una liga.")
            return

        self._analysis_running = True
        self._set_run_btn(enabled=False, text="⏳  Analizando…")
        self.analysis_view.update_status("Iniciando…")

        threading.Thread(
            target=self._analysis_worker,
            args=(selected,),
            daemon=True,
        ).start()

    def _ui(self, fn) -> None:
        """Ejecuta fn en el hilo principal de tkinter de forma segura."""
        self.after(0, fn)

    def _set_status(self, msg: str) -> None:
        """Actualización de estado thread-safe."""
        self._ui(lambda m=msg: self.analysis_view.update_status(m))

    def _set_progress(self, value: float, label: str = "") -> None:
        """Actualiza la barra de progreso (modo determinado) desde cualquier hilo."""
        def _update(v=value, l=label):
            self._progress_bar.configure(mode="determinate")
            self._progress_bar.set(v)
            pct = int(v * 100)
            self._prog_pct.configure(
                text=f"{pct}%",
                text_color="#00c853" if v >= 1.0 else ACCENT,
            )
            self._prog_lbl.configure(
                text=l or ("✓ Completado" if v >= 1.0 else ""),
                text_color="#00c853" if v >= 1.0 else MUTED,
            )
        self._ui(_update)

    def _set_progress_spin(self, active: bool, label: str = "") -> None:
        """Alterna la barra entre modo animado (activo) y detenido."""
        def _update(a=active, l=label):
            if a:
                self._progress_bar.configure(mode="indeterminate")
                self._progress_bar.start()
                self._prog_pct.configure(text="…", text_color=ACCENT)
            else:
                self._progress_bar.stop()
                self._progress_bar.configure(mode="determinate")
            if l:
                self._prog_lbl.configure(text=l, text_color=MUTED)
        self._ui(_update)

    def _set_run_btn(self, enabled: bool, text: str = "▶  Run Analysis") -> None:
        """Activa o desactiva el botón Run Analysis (hilo principal)."""
        self._ui(lambda: self._run_btn.configure(
            state="normal" if enabled else "disabled",
            text=text,
        ))

    def _check_data_freshness(self) -> None:
        """
        Comprueba si el último análisis tiene más de 24h de antigüedad.

        Si los datos están frescos (<24h): botón verde normal.
        Si están obsoletos (>24h): botón color ámbar con aviso de horas.
        Si nunca se analizó: mensaje neutro de bienvenida.

        Llama a sí mismo cada 30 min para mantener el indicador actualizado.
        """
        from datetime import datetime as _dt

        ts_str = self.storage.get_setting("last_analysis_at", "")
        if not ts_str:
            # Nunca se ha ejecutado un análisis
            self._run_btn.configure(
                fg_color="#1d4ed8",    # azul oscuro — "primer análisis"
                hover_color="#1e40af",
                text="▶  Primer análisis",
            )
        else:
            try:
                last_ts = _dt.fromisoformat(ts_str)
                elapsed = _dt.now() - last_ts
                hours   = elapsed.total_seconds() / 3600

                if hours < 24:
                    # Datos frescos — botón verde normal
                    self._run_btn.configure(
                        fg_color=ACCENT,
                        hover_color=ACCENT_2,
                        text="▶  Run Analysis",
                    )
                elif hours < 48:
                    # Datos un poco obsoletos — ámbar
                    h = int(hours)
                    self._run_btn.configure(
                        fg_color="#92400e",    # ámbar oscuro
                        hover_color="#78350f",
                        text=f"▶  Re-analizar ({h}h)",
                    )
                else:
                    # Muy obsoleto (>48h) — naranja rojizo
                    h = int(hours)
                    self._run_btn.configure(
                        fg_color="#7f1d1d",    # rojo apagado
                        hover_color="#6b1111",
                        text=f"▶  Re-analizar ({h}h)",
                    )
            except Exception:
                # ts inválido — no cambiar el botón
                pass

        # Re-comprobar cada 30 minutos mientras la app esté abierta
        self.after(30 * 60 * 1000, self._check_data_freshness)

    def _analysis_worker(self, selected: list) -> None:
        """Todo el trabajo pesado en hilo de fondo. Sin tocar widgets directamente."""
        try:
            # Reset alertas de valor para el nuevo análisis
            if self.line_monitor:
                try:
                    self.line_monitor.reset_value_alerts()
                except Exception:
                    pass

            # ── Calcular pasos y pesos ────────────────────────────────────────
            # Pesos aproximados al tiempo real de cada fase:
            #   CSV por liga: 1 | Fixtures: 1 | ML: 4 | DC: 3 | Análisis: 2 | Final: 1
            n_csv  = sum(1 for n in selected if LEAGUE_MAP[n][1])
            total_weight = n_csv * 1.0 + 1 + 4 + 3 + 2 + 1
            done = 0.0

            def step(w: float, label: str) -> None:
                nonlocal done
                done += w
                self._set_progress(min(done / total_weight, 0.99), label)
                self._set_status(label)

            # ── Descargar histórico ───────────────────────────────────────────
            hist: dict = {}
            for name in selected:
                div, csv_url, _ = LEAGUE_MAP[name]
                if csv_url:
                    step(1.0, f"Descargando {name}…")
                    hist[div] = fetch_csv(csv_url)

            # ── xG real de Understat (gratis, sin API key) ───────────────────
            from .core.understat import fetch_league_xg as _fetch_xg
            self._understat_cache = {}
            for name in selected:
                div, csv_url, _ = LEAGUE_MAP[name]
                if csv_url:   # solo ligas con histórico que Understat también cubre
                    try:
                        xg_data = _fetch_xg(div)
                        if xg_data:
                            self._understat_cache[div] = xg_data
                            self._set_status(f"xG real Understat: {name} ({len(xg_data)} equipos)")
                    except Exception:
                        pass

            # ── Fixtures ─────────────────────────────────────────────────────
            odds_api_key = self.storage.get_setting("odds_api_key", "")
            # Leer de storage (save_settings() ya lo guardó antes de iniciar el hilo).
            # Acceder a BooleanVar/StringVar desde un hilo de fondo no es thread-safe en Win.
            use_odds_api = (self.storage.get_setting("use_odds_api", "0") == "1") and bool(odds_api_key)

            if use_odds_api:
                step(1.0, "⚡ Cuotas en tiempo real (The Odds API)…")
                div_codes = [LEAGUE_MAP[n][0] for n in selected]
                fixtures, remaining = fetch_odds_fixtures(odds_api_key, div_codes)
                self._ui(lambda r=remaining: self._store_remaining(r))
                if fixtures.empty:
                    self._set_status("⚠ Sin fixtures de Odds API, usando football-data.co.uk…")
                    fixtures = fetch_csv(FIXTURES_URL)
            else:
                step(1.0, "Descargando fixtures…")
                fixtures = fetch_csv(FIXTURES_URL)

            # ── Separar ligas con/sin histórico ───────────────────────────────
            divs_with_history = [LEAGUE_MAP[n][0] for n in selected if LEAGUE_MAP[n][1]]
            divs_odds_only    = [LEAGUE_MAP[n][0] for n in selected if not LEAGUE_MAP[n][1]]

            if divs_odds_only and not divs_with_history:
                step(4 + 3 + 2, "Cargando cuotas en tiempo real…")
                from .core.data import prepare_fixtures as _pf
                results          = self._build_odds_only_df(_pf(fixtures), divs_odds_only)
                backtest_summary = {}
                diagnostics      = [
                    "ℹ️  Modo cuotas en tiempo real (sin modelo IA)",
                    f"Ligas sin histórico: {', '.join(divs_odds_only)}",
                    f"Fixtures cargados: {len(results)}",
                    "",
                    "Los partidos se muestran en GRIS — hay cuotas pero sin predicción del modelo.",
                    "Para picks IA usa: ⚽ Quiniela IA  o  ⚡ Combinadas IA",
                    "Las ligas europeas (Premier, La Liga…) estarán disponibles en agosto 2026.",
                ]
            else:
                # ── Modelos (pasos pesados — barra animada) ───────────────────
                self._set_progress_spin(True, "Entrenando modelos IA…")
                analyzer = Analyzer(
                    hist, fixtures,
                    claude_api_key=self.storage.get_setting("anthropic_api_key", ""),
                )

                def _on_progress(msg: str) -> None:
                    self._set_status(msg)
                    self._ui(lambda m=msg: self._prog_lbl.configure(text=m))

                # Leer edge y flags desde storage (thread-safe; save_settings() ya los guardó)
                _edge1      = float(self.storage.get_setting("edge1",        "0.03"))
                _edge2      = float(self.storage.get_setting("edge2",        "0.03"))
                _use_injury = self.storage.get_setting("use_injury_api", "0") == "1"
                _injury_key = self.storage.get_setting("injury_api_key", "") if _use_injury else ""

                results = analyzer.run(
                    divs_with_history,
                    _edge1,
                    _edge2,
                    progress_cb=_on_progress,
                    injury_api_key=_injury_key,
                )

                # Enriquecer con xG real de Understat (columnas adicionales de display)
                results = self._enrich_with_xg(results)

                # Volver a barra determinada al terminar los modelos
                done += 4.0 + 3.0
                self._set_progress_spin(False)
                step(2.0, "Calculando picks, edge y combinadas…")
                if divs_odds_only:
                    from .core.data import prepare_fixtures as _pf
                    odds_df = self._build_odds_only_df(_pf(fixtures), divs_odds_only)
                    if not odds_df.empty:
                        results = pd.concat([results, odds_df], ignore_index=True)

                backtest_summary  = analyzer.backtest_summary
                diagnostics       = analyzer.diagnostics
                self._last_drift_info = getattr(analyzer, "drift_info", None)

            step(1.0, "Actualizando vistas…")

            # ── Actualizar UI en hilo principal ───────────────────────────────
            self._ui(lambda r=results, b=backtest_summary, d=diagnostics:
                     self._on_analysis_done(r, b, d))

        except Exception as exc:
            logger.exception("Error en _analysis_worker")
            self._ui(lambda e=exc: self._on_analysis_error(e))

    def _store_remaining(self, remaining: Optional[str]) -> None:
        self.odds_api_remaining = remaining
        self._update_api_counter()

    def _enrich_with_xg(self, df: pd.DataFrame) -> pd.DataFrame:
        """Añade columnas xg_real_home/away al DataFrame de resultados usando Understat."""
        from .core.understat import get_team_xg
        if df.empty or not self._understat_cache:
            return df

        xg_h, xg_a, xga_h, xga_a = [], [], [], []
        for _, row in df.iterrows():
            div       = str(row.get("div", ""))
            home_team = str(row.get("home_team", ""))
            away_team = str(row.get("away_team", ""))
            league_xg = self._understat_cache.get(div, {})

            h = get_team_xg(home_team, league_xg)
            a = get_team_xg(away_team, league_xg)

            xg_h.append(round(h["xg"],  2) if h else None)
            xga_h.append(round(h["xga"], 2) if h else None)
            xg_a.append(round(a["xg"],  2) if a else None)
            xga_a.append(round(a["xga"], 2) if a else None)

        df = df.copy()
        df["xg_real_home"]  = xg_h
        df["xg_real_away"]  = xg_a
        df["xga_real_home"] = xga_h
        df["xga_real_away"] = xga_a
        return df

    def _selected_leagues_divs(self) -> list[str]:
        """Devuelve los div_codes de las ligas actualmente activas (para el line monitor)."""
        try:
            return [
                LEAGUE_MAP[n][0]
                for n, v in self.analysis_view.league_vars.items()
                if v.get()
            ]
        except Exception:
            return ["E0", "SP1", "I1", "D1", "F1"]

    def _on_analysis_done(
        self,
        results: pd.DataFrame,
        backtest_summary: dict,
        diagnostics: list,
    ) -> None:
        """Llamado en el hilo principal cuando el análisis termina bien."""
        self.results          = results
        self.backtest_summary = backtest_summary
        self.diagnostics      = diagnostics
        self.filtered         = results.copy()

        from datetime import datetime as _dt
        _now = _dt.now()
        self._last_analysis_ts = _now.strftime("%d/%m/%Y %H:%M")
        # Persistir timestamp para la detección de datos obsoletos al reiniciar
        self.storage.set_setting("last_analysis_at", _now.isoformat())
        self.apply_filters()
        self._fill_summary()
        self._refresh_combo()
        self._refresh_simulator_matches()
        # Solo refrescar combinadas si la vista ya está visible (evita tarjetas negras
        # al construir widgets en CTkScrollableFrame cuando la vista está oculta).
        # show_accumulator_view() llamará refresh() cuando el usuario navegue allí.
        try:
            if self.accumulator_view.winfo_viewable():
                self.accumulator_view.refresh(self.results)
        except Exception:
            pass
        self.update_ticker()          # actualizar ticker con los nuevos picks

        # ── Monte Carlo: pasar picks al simulador ─────────────────────────────
        try:
            verde = self.results[self.results["risk_light"] == "VERDE"]
            mc_picks = []
            for _, row in verde.iterrows():
                ev   = float(row.get("ev",   0) or 0)
                odds = float(row.get("odds", 0) or 0)
                if odds <= 1.0:
                    continue

                # ── Probabilidad correcta según dirección del pick ────────────
                pick = str(row.get("pick", "1"))
                p_h  = float(row.get("p_home", 0) or 0)
                p_d  = float(row.get("p_draw", 0) or 0)
                p_a  = float(row.get("p_away", 0) or 0)
                if   pick == "1":  prob = p_h
                elif pick == "X":  prob = p_d
                elif pick == "2":  prob = p_a
                elif pick == "1X": prob = p_h + p_d
                elif pick == "12": prob = p_h + p_a
                elif pick == "X2": prob = p_d + p_a
                else:
                    # OVER/UNDER u otros — usar model_prob si existe
                    prob = float(row.get("model_prob", 0) or 0)

                if prob <= 0:
                    continue

                # ── Kelly: bankroll_pct se almacena como % (e.g. 1.5 = 1.5%)  ─
                # Convertir a fracción para el simulador (e.g. 0.015)
                kelly = float(row.get("bankroll_pct", 0.0) or 0.0) / 100.0

                mc_picks.append({
                    "ev":         ev,
                    "model_prob": prob,
                    "odds":       odds,
                    "kelly_pct":  kelly,
                })
            self.portfolio_view.refresh_montecarlo(mc_picks)
        except Exception as _e:
            logger.debug("Monte Carlo refresh error: %s", _e)

        # ── Alertas proactivas de valor ───────────────────────────────────────
        if self.line_monitor and self._tg_bot:
            try:
                picks_for_alerts = self.results.to_dict("records")
                threshold = getattr(self._tg_bot, "_value_edge_threshold", 0.05)
                def _notify_pick(pick):
                    try:
                        self._tg_bot.notify_value_pick(pick)
                    except Exception:
                        pass
                self.line_monitor.check_value_alerts(
                    picks_for_alerts,
                    edge_threshold=threshold,
                    notify_fn=_notify_pick,
                )
            except Exception as _e:
                logger.debug("Value alerts error: %s", _e)

        # ── Drift banner ──────────────────────────────────────────────────────
        try:
            if hasattr(self.analysis_view, "show_drift_banner"):
                self.analysis_view.show_drift_banner(getattr(self, "_last_drift_info", None))
        except Exception as _e:
            logger.debug("Drift banner error: %s", _e)

        self.quiniela_view.generate_ai(self.results)
        self._start_claude_enrichment(results)
        # Actualizar caché del bot con los nuevos datos (hilo principal)
        self.after(200, self.update_bot_cache)

        self.analysis_view.update_status(f"✓ Completado — {len(results)} fixtures")
        logger.info("Análisis completado: %d fixtures", len(results))
        self._set_progress(1.0, "✓ Completado")

        self._analysis_running = False
        self._set_run_btn(enabled=True)
        # Restablecer color del botón a verde (datos recién actualizados)
        self.after(300, self._check_data_freshness)

        if (
            self.telegram_enabled.get()
            and self.send_combo_enabled.get()
            and self.auto_send_after_analysis.get()
        ):
            msg = self._combo_message()
            if msg:
                try:
                    self.send_telegram_text(msg)
                    self._add_history_entry(sent=True)
                except Exception:
                    pass

    # ── Claude enrichment ─────────────────────────────────────────────────────

    def _start_claude_enrichment(self, results: pd.DataFrame) -> None:
        """Lanza el enriquecimiento Claude en hilo de fondo si está activado."""
        if not self.use_claude_analysis.get():
            return
        api_key = self.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            return

        # Picks con valor del modelo (VERDE/AMARILLO)
        verde = results[results["risk_light"].isin(["VERDE", "AMARILLO"])].copy()

        # Partidos sin modelo ML (Mundial, Libertadores…) que tienen cuotas
        grey = results[
            (results["pick"] == "NO BET") &
            results["B365H"].notna() &
            results["B365D"].notna() &
            results["B365A"].notna()
        ].copy()

        if verde.empty and grey.empty:
            return

        threading.Thread(
            target=self._claude_enrichment_worker,
            args=(verde, grey, api_key),
            daemon=True,
        ).start()

    def _claude_enrichment_worker(
        self,
        verde: pd.DataFrame,
        grey: pd.DataFrame,
        api_key: str,
    ) -> None:
        """Hilo de fondo: análisis cuantitativo para VERDE/AMARILLO + tipster para grises."""
        from .core.ai_analysis import generate_pick_analysis, generate_tipster_analysis

        # ── Picks con modelo ML ───────────────────────────────────────────────
        for _, row in verde.iterrows():
            text = generate_pick_analysis(row.to_dict(), api_key)
            if not text:
                continue
            home = str(row["home_team"])
            away = str(row["away_team"])
            mask = (self.results["home_team"] == home) & (self.results["away_team"] == away)
            self.results.loc[mask, "analysis"] = text
            key  = f"{home}::{away}"
            self._ui(lambda k=key, t=text: self.analysis_view.update_pick_analysis(k, t))
            self._ui(self._update_claude_counter)

        # ── Partidos sin modelo — tipster profesional ─────────────────────────
        claude_updated = False
        for _, row in grey.iterrows():
            result = generate_tipster_analysis(row.to_dict(), api_key)
            if not result:
                continue
            pick_rec, text = result
            home = str(row["home_team"])
            away = str(row["away_team"])

            # Calcular odds y prob implícita para el pick de Claude
            try:
                bh = float(row.get("B365H") or 0)
                bd = float(row.get("B365D") or 0)
                ba = float(row.get("B365A") or 0)
                if bh > 1 and bd > 1 and ba > 1:
                    total     = 1/bh + 1/bd + 1/ba
                    odds_map  = {"1": bh,              "X": bd,              "2": ba}
                    prob_map  = {"1": (1/bh)/total,    "X": (1/bd)/total,    "2": (1/ba)/total}
                    pick_odds = odds_map.get(pick_rec, bh)
                    pick_prob = prob_map.get(pick_rec, (1/bh)/total)
                    pick_ev   = round(pick_prob * pick_odds - 1.0, 4)
                else:
                    pick_odds = pick_prob = pick_ev = None
            except Exception:
                pick_odds = pick_prob = pick_ev = None

            # Fiabilidad basada en liquidez del mercado y edge del pick
            # (no hardcodeada a 65 — varía por partido)
            try:
                if bh > 1 and bd > 1 and ba > 1:
                    overround    = 1/bh + 1/bd + 1/ba - 1.0   # 0 = mercado perfecto
                    # Mercado líquido (overround bajo) → más fiable
                    mkt_base     = max(50, min(72, 72 - int(overround * 300)))
                    # Bonus si el edge del pick es claro
                    edge_bonus   = int(max(0, (pick_prob - (1/(bh if pick_rec=="1" else bd if pick_rec=="X" else ba))/total) * 200))
                    claude_rel   = min(78, mkt_base + edge_bonus)
                else:
                    claude_rel = 52
            except Exception:
                claude_rel = 58

            mask = (self.results["home_team"] == home) & (self.results["away_team"] == away)
            self.results.loc[mask, "analysis"]           = text
            self.results.loc[mask, "pick"]               = pick_rec
            self.results.loc[mask, "odds"]               = pick_odds
            self.results.loc[mask, "model_prob"]         = pick_prob
            self.results.loc[mask, "edge"]               = 0.0
            self.results.loc[mask, "ev"]                 = pick_ev
            self.results.loc[mask, "no_bet"]             = "NO"
            self.results.loc[mask, "risk_light"]         = "CLAUDE"
            self.results.loc[mask, "reliability_score"]  = claude_rel

            key = f"{home}::{away}"
            self._ui(lambda k=key, t=text, p=pick_rec:
                     self.analysis_view.update_grey_pick(k, t, p))
            self._ui(self._update_claude_counter)
            claude_updated = True

        # Refrescar combinadas con los nuevos picks Claude
        if claude_updated:
            self._ui(lambda: self.accumulator_view.refresh(self.results))

    def _on_analysis_error(self, exc: Exception) -> None:
        """Llamado en el hilo principal si el análisis falla."""
        messagebox.showerror("Error en análisis", str(exc))
        self.analysis_view.update_status("✗ Error")
        self._set_progress(0.0, "✗ Error")
        self._analysis_running = False
        self._set_run_btn(enabled=True)

    # ── Odds-only mode (ligas sin histórico: Mundial, Libertadores…) ─────────

    def _build_odds_only_df(self, fixtures: pd.DataFrame, div_codes: list) -> pd.DataFrame:
        """
        Construye un DataFrame de resultados básico para ligas sin datos históricos.
        Muestra cuotas en tiempo real sin predicción del modelo IA.
        """
        if fixtures.empty:
            return pd.DataFrame()

        fx = fixtures[fixtures["div"].str.upper().isin([d.upper() for d in div_codes])].copy()
        if fx.empty:
            return pd.DataFrame()

        rows = []
        for _, r in fx.iterrows():
            b365h = r.get("B365H")
            b365d = r.get("B365D")
            b365a = r.get("B365A")
            has_odds = pd.notna(b365h) and pd.notna(b365d) and pd.notna(b365a)
            b365o25 = r.get("B365O25")
            b365u25 = r.get("B365U25")
            rows.append({
                "date":              r.get("date"),
                "time":              r.get("time", ""),
                "league":            r.get("div", ""),
                "home_team":         r.get("home_team", ""),
                "away_team":         r.get("away_team", ""),
                "pick":              "NO BET",
                "odds":              None,
                "edge":              None,
                "model_prob":        None,
                "fair_prob":         None,
                "open_fair_prob":    None,
                "close_fair_prob":   None,
                "clv":               None,
                "market_move":       None,
                "open_overround":    None,
                "close_overround":   None,
                "market_entropy":    None,
                "ev":                None,
                "expected_goals":    None,
                "p_home":            round(1 / float(b365h), 4) if has_odds else None,
                "p_draw":            round(1 / float(b365d), 4) if has_odds else None,
                "p_away":            round(1 / float(b365a), 4) if has_odds else None,
                "p_over25":          None,
                "reliability_score": 0,
                "risk_light":        "ROJO",
                "no_bet":            "SI",
                "bankroll_pct":      0.0,
                "stake_units":       0.0,
                # ── Cuotas brutas para el simulador ───────────────────────────
                "B365H":   float(b365h)   if has_odds else None,
                "B365D":   float(b365d)   if has_odds else None,
                "B365A":   float(b365a)   if has_odds else None,
                "B365O25": float(b365o25) if pd.notna(b365o25) else None,
                "B365U25": float(b365u25) if pd.notna(b365u25) else None,
                "analysis": (
                    f"Cuotas: {b365h}/{b365d}/{b365a} — Sin modelo IA (sin histórico)"
                    if has_odds else "Sin cuotas disponibles"
                ),
            })
        return pd.DataFrame(rows)

    # ── Filters ───────────────────────────────────────────────────────────────

    def apply_filters(self) -> None:
        df = self.results.copy() if not self.results.empty else pd.DataFrame()

        if df.empty:
            self.analysis_view.fill_tree(df)
            self.analysis_view.fill_cards(df)
            self._refresh_combo()
            return

        q = self.search_var.get().strip().lower()
        if q:
            df = df[
                df["home_team"].astype(str).str.lower().str.contains(q)
                | df["away_team"].astype(str).str.lower().str.contains(q)
                | df["league"].astype(str).str.lower().str.contains(q)
            ]

        if self.only_green.get():
            df = df[df["risk_light"] == "VERDE"]
        if self.only_picks.get():
            df = df[df["pick"] != "NO BET"]

        self.filtered = df.copy()
        self.analysis_view.fill_tree(df)
        # fill_cards() crea ~25 widgets CTk por fila. Con 200+ partidos son miles de
        # widgets que bloquean el hilo principal. Solo construir si la vista Cards está activa.
        if getattr(self.analysis_view, "_view_mode", "table") == "cards":
            self.analysis_view.fill_cards(df)
        self.analysis_view.fill_top_picks(df)
        self.analysis_view.fill_league_ranking(df)
        self._refresh_combo()

    def _fill_summary(self) -> None:
        self.analysis_view.fill_summary(self.backtest_summary, self.diagnostics)

        if not self.results.empty:
            total = len(self.results)
            picks = len(
                self.results[
                    (self.results["pick"] != "NO BET")
                    & (self.results["no_bet"] == "NO")
                ]
            )
            avg_roi = (
                float(np.mean([v.get("roi", 0) for v in self.backtest_summary.values()]))
                if self.backtest_summary else 0.0
            )
            verde_count = int(
                (self.results.get("risk_light", pd.Series(dtype=str)) == "VERDE").sum()
            ) if "risk_light" in self.results.columns else 0
            amar_count = int(
                (self.results.get("risk_light", pd.Series(dtype=str)) == "AMARILLO").sum()
            ) if "risk_light" in self.results.columns else 0
            self.analysis_view.update_metrics(total, picks, avg_roi, verde_count, amar_count)

    # ── Combo builder ─────────────────────────────────────────────────────────

    def _build_combo_df(self) -> pd.DataFrame:
        df = self.filtered.copy() if not self.filtered.empty else self.results.copy()
        if df.empty:
            return df

        df = df[
            (df["pick"] != "NO BET")
            & (df["no_bet"] == "NO")
            & (df["risk_light"] != "ROJO")
        ].dropna(subset=["odds", "edge", "reliability_score", "ev", "bankroll_pct"]).copy()

        if df.empty:
            return df

        df = df[df["odds"].astype(float) <= 2.0].copy()
        if df.empty:
            return df

        df["combo_score"] = (
            df["reliability_score"] * 0.55
            + df["edge"] * 100 * 0.20
            + df["ev"]   * 100 * 0.15
            + df["bankroll_pct"]    * 0.10
        )
        df = df.sort_values(
            ["odds", "combo_score", "reliability_score", "ev", "edge"],
            ascending=[True, False, False, False, False],
        )

        legs: list = []
        used: set  = set()
        running    = 1.0
        max_odds   = 2.0

        for _, row in df.iterrows():
            key = f"{row['home_team']}::{row['away_team']}"
            odd = float(row["odds"])
            if key in used or running * odd > max_odds:
                continue
            used.add(key)
            legs.append(row)
            running *= odd
            if len(legs) >= self.combo_size.get():
                break

        return pd.DataFrame(legs)

    def _combo_snapshot(self) -> Optional[dict]:
        combo = self._build_combo_df()
        if combo.empty:
            return None

        total_odds   = float(np.prod(combo["odds"].astype(float)))
        avg_rel      = float(combo["reliability_score"].mean())
        avg_bankroll = float(combo["bankroll_pct"].mean())
        risk         = "VERDE" if avg_rel >= 78 else "AMARILLO" if avg_rel >= 68 else "ROJO"
        bankroll_base = float(self.unit_stake.get() or 100)
        suggested_pct = min(1.0, max(0.25, avg_bankroll))
        stake_amount  = round(bankroll_base * suggested_pct / 100, 2)

        legs = [
            {
                "league":       row["league"],
                "match":        f"{row['home_team']} vs {row['away_team']}",
                "pick":         row["pick"],
                "odds":         float(row["odds"]),
                "edge":         float(row["edge"]),
                "reliability":  int(row["reliability_score"]),
                "risk":         row["risk_light"],
                "ev":           float(row["ev"]),
                "bankroll_pct": float(row["bankroll_pct"]),
            }
            for _, row in combo.iterrows()
        ]

        return {
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "size":        len(combo),
            "total_odds":  round(total_odds, 2),
            "risk":        risk,
            "stake_units": round(suggested_pct, 2),
            "stake_amount": stake_amount,
            "legs":        legs,
            "status":      "PENDING",
            "profit":      0.0,
            "roi":         0.0,
        }

    def _combo_message(self) -> Optional[str]:
        snap = self._combo_snapshot()
        if not snap:
            return None
        lines = [f"Conservative Builder Pro v10 ({snap['size']} selecciones)"]
        for i, leg in enumerate(snap["legs"], 1):
            lines.append(
                f"{i}. {leg['match']} | {leg['pick']} @ {leg['odds']:.2f} | "
                f"EV {leg['ev']:.2%} | Kelly {leg['bankroll_pct']:.2f}%"
            )
        lines += [
            f"Cuota total: {snap['total_odds']:.2f}",
            f"Riesgo agregado: {snap['risk']}",
            f"Stake sugerido: {snap['stake_units']:.2f}% bankroll ({snap['stake_amount']:.2f})",
        ]
        return "\n".join(lines)

    def _refresh_combo(self) -> None:
        # Actualiza en execution view (Combo Builder) y en portfolio si existe
        snap = self._combo_snapshot()
        text = self._combo_message() if snap else (
            "No hay picks suficientes para generar una combinada con cuota total ≤ 2.00."
        )
        if hasattr(self.execution_view, "combo_text"):
            from .ui.widgets import textbox_set
            textbox_set(self.execution_view.combo_text, text)

    # ── Portfolio & ROI ───────────────────────────────────────────────────────

    def _aggregate_roi(self) -> dict:
        settled = [h for h in self.history if h.get("status") in ("WIN", "LOSS")]
        if not settled:
            return {"count": 0, "stake": 0.0, "profit": 0.0, "roi": 0.0, "wins": 0, "losses": 0}
        total_stake  = sum(float(h.get("stake_amount", 0)) for h in settled)
        total_profit = sum(float(h.get("profit",       0)) for h in settled)
        wins         = sum(1 for h in settled if h.get("status") == "WIN")
        losses       = sum(1 for h in settled if h.get("status") == "LOSS")
        roi = round((total_profit / total_stake) * 100, 2) if total_stake else 0.0
        return {
            "count": len(settled), "stake": round(total_stake, 2),
            "profit": round(total_profit, 2), "roi": roi,
            "wins": wins, "losses": losses,
        }

    def _refresh_portfolio(self) -> None:
        self.portfolio_view.refresh_roi(self._aggregate_roi())
        self.portfolio_view.refresh_history(self.history)

    def _add_history_entry(self, sent: bool = False) -> None:
        snap = self._combo_snapshot()
        if not snap:
            return
        snap["sent_to_telegram"] = sent
        self.storage.save_combo(snap)
        self.history = self.storage.load_combos()
        self._refresh_portfolio()

    def settle_combo_selected(self, result: str) -> None:
        """Liquida la combinada seleccionada en el Portfolio (cualquier fila)."""
        db_id = self.portfolio_view.selected_db_id()
        if db_id is None:
            return
        entry = next((h for h in self.history if h.get("_db_id") == db_id), None)
        if entry is None:
            messagebox.showwarning("Portfolio", "Combinada no encontrada.")
            return
        if entry.get("status") != "PENDING":
            messagebox.showinfo("Portfolio", f"Ya liquidada como {entry['status']}.")
            return
        stake  = float(entry.get("stake_amount", 0))
        odds   = float(entry.get("total_odds",   0))
        profit = round(stake * (odds - 1), 2) if result == "WIN" else round(-stake, 2)
        roi    = round((profit / stake) * 100, 2) if stake else 0.0
        entry.update({
            "status":     result,
            "profit":     profit,
            "roi":        roi,
            "settled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.storage.update_combo_by_id(db_id, entry)
        self.history = self.storage.load_combos()
        self._refresh_portfolio()

    def delete_combo(self) -> None:
        """Elimina la combinada seleccionada del Portfolio."""
        db_id = self.portfolio_view.selected_db_id()
        if db_id is None:
            return
        if not messagebox.askyesno("Eliminar combinada", "¿Eliminar esta combinada del historial?"):
            return
        self.storage.delete_combo_by_id(db_id)
        self.history = self.storage.load_combos()
        self._refresh_portfolio()

    def settle_last(self, result: str) -> None:
        if not self.history:
            return
        entry = self.history[0]
        if entry.get("status") != "PENDING":
            messagebox.showinfo("Histórico", "La última combinada ya estaba resuelta.")
            return
        stake  = float(entry.get("stake_amount", 0))
        odds   = float(entry.get("total_odds",   0))
        profit = round(stake * (odds - 1), 2) if result == "WIN" else round(-stake, 2)
        roi    = round((profit / stake) * 100, 2) if stake else 0.0
        entry.update({
            "status":     result,
            "profit":     profit,
            "roi":        roi,
            "settled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.storage.replace_latest_combo(entry)
        self.history = self.storage.load_combos()
        self._refresh_portfolio()

    # ── Sim history settlement ────────────────────────────────────────────────

    def settle_sim_selected(self, result: str) -> None:
        """Liquida la fila seleccionada.
        Singles → WIN/LOSS directo.
        Acumuladores → abre el diálogo de liquidación por marcador.
        """
        tree = self.execution_view.sim_tree
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("Historial", "Selecciona una fila para liquidar.")
            return

        iid = selection[0]
        try:
            db_id = int(iid)
        except ValueError:
            messagebox.showerror("Historial", "ID de simulación inválido.")
            return

        sim = next((s for s in self.bet_sim_history if s.get("_db_id") == db_id), None)
        if not sim:
            messagebox.showwarning("Historial", "Simulación no encontrada.")
            return
        if sim.get("status") != "PENDING":
            messagebox.showinfo("Historial", f"Ya está liquidada como {sim['status']}.")
            return

        # ── Acumulador → diálogo con marcadores ─────────────────────────────
        if sim.get("type") == "accumulator":
            self.execution_view._show_settlement_dialog(sim, db_id)
            return

        # ── Apuesta simple → liquidación directa ─────────────────────────────
        stake = float(sim.get("stake", 0))
        odds  = float(sim.get("odds",  0))
        pnl   = round(stake * (odds - 1), 2) if result == "WIN" else round(-stake, 2)

        self.storage.update_sim_status(db_id, result, pnl)
        sim["status"] = result
        sim["pnl"]    = pnl

        self.execution_view.refresh_history_panel(self.bet_sim_history)
        self.execution_view.refresh_stats(self.bet_sim_history)
        self.execution_view.settle_lbl.configure(
            text=f"✓  Liquidada como {result}  (PnL {pnl:+.2f} €)",
            text_color=MUTED,
        )

    # ── Simulator ─────────────────────────────────────────────────────────────

    def _future_results_only(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        now = pd.Timestamp.now()
        if "date" in df.columns:
            return df[pd.to_datetime(df["date"], errors="coerce") >= now]
        return df

    def _refresh_simulator_matches(self) -> None:
        df = self._future_results_only(self.results)
        matches = []
        for _, row in df.iterrows():
            matches.append({
                "date":       row.get("date", ""),
                "league":     row.get("league", ""),
                "home_team":  row.get("home_team", ""),
                "away_team":  row.get("away_team", ""),
                "pick":       row.get("pick", "NO BET"),
                "risk_light": row.get("risk_light", "ROJO"),
                "B365H":      row.get("B365H"),
                "B365D":      row.get("B365D"),
                "B365A":      row.get("B365A"),
                "B365O25":    row.get("B365O25"),
                "B365U25":    row.get("B365U25"),
            })
        self.execution_view.refresh_match_list(matches)

    def load_selected_match_into_simulator(self) -> None:
        df = self._future_results_only(self.results)
        if df.empty:
            return
        selected = self.sim_match_var.get().strip()
        row = None
        for _, r in df.iterrows():
            label = (
                f"{r.get('date','')} | {r.get('league','')} | "
                f"{r.get('home_team','')} vs {r.get('away_team','')}"
            )
            if label == selected:
                row = r
                break
        if row is None:
            return

        from .ui.widgets import textbox_set
        lines = [
            f"Partido: {row.get('home_team','')} vs {row.get('away_team','')}",
            f"Liga: {row.get('league','')}  Fecha: {row.get('date','')}",
            f"Pick: {row.get('pick','—')}  Cuota: {row.get('odds','—')}",
            f"Edge: {row.get('edge','—')}  EV: {row.get('ev','—')}",
            f"Modelo: H={row.get('p_home','—')} D={row.get('p_draw','—')} A={row.get('p_away','—')}",
            f"Goles esperados: {row.get('expected_goals','—')}  P(O2.5): {row.get('p_over25','—')}",
            f"Reliability: {row.get('reliability_score','—')}  Riesgo: {row.get('risk_light','—')}",
            f"CLV: {row.get('clv','—')}  Kelly: {row.get('bankroll_pct','—')}%",
            f"Análisis: {row.get('analysis','—')}",
        ]
        textbox_set(self.execution_view.sim_detail, "\n".join(lines))

        pick = str(row.get("pick", "1"))
        if pick in ("1", "X", "2"):
            self.manual_pick_var.set(pick)
        if pd.notna(row.get("odds")):
            self.manual_odds_var.set(str(row["odds"]))

    def auto_fill_sim_odds(self) -> None:
        """Auto-rellena la cuota al cambiar partido o mercado."""
        df = self._future_results_only(self.results)
        if df is None or df.empty:
            return

        selected = self.sim_match_var.get().strip()
        pick     = self.manual_pick_var.get().strip()

        for _, row in df.iterrows():
            label = (
                f"{row.get('date','')} | {row.get('league','')} | "
                f"{row.get('home_team','')} vs {row.get('away_team','')}"
            )
            if label != selected:
                continue

            # Mapa mercado → cuota
            odds_map = {
                "1":       row.get("B365H"),
                "X":       row.get("B365D"),
                "2":       row.get("B365A"),
                "OVER2.5": row.get("B365O25"),
                "UNDER2.5":row.get("B365U25"),
            }
            # Si el pick coincide con la recomendación del análisis, usa la cuota directa
            if str(row.get("pick", "")) == pick and pd.notna(row.get("odds")):
                odd = float(row["odds"])
            else:
                raw = odds_map.get(pick)
                odd = float(raw) if raw is not None and pd.notna(raw) else None

            if odd and odd > 1:
                self.manual_odds_var.set(f"{odd:.2f}")
                # Actualiza preview automáticamente
                self.update_manual_quote_preview()
            break

    def update_manual_quote_preview(self) -> None:
        try:
            odds  = float(self.manual_odds_var.get())
            stake = float(self.manual_stake_var.get())
        except ValueError:
            return
        if odds <= 1 or stake <= 0:
            return
        gross   = round(stake * odds, 2)
        profit  = round((odds - 1) * stake, 2)
        from .ui.widgets import textbox_set
        textbox_set(
            self.execution_view.sim_detail,
            f"Cuota: {odds:.2f}  Stake: {stake:.2f} €\n"
            f"Retorno bruto: {gross:.2f} €\n"
            f"Beneficio neto: {profit:.2f} €",
        )

    def save_bet_simulation(self) -> None:
        """Guarda el boleto actual (single o acumulador multi-leg)."""
        legs = list(self.execution_view._slip_legs)
        if not legs:
            messagebox.showwarning("Simulator", "Añade al menos una selección al slip.")
            return
        try:
            stake = float(self.manual_stake_var.get())
        except ValueError:
            messagebox.showerror("Simulator", "Introduce un stake válido.")
            return
        if stake <= 0:
            messagebox.showerror("Simulator", "El stake debe ser mayor que 0.")
            return

        # ── Validar que los legs corresponden a partidos del análisis actual ──
        if not self.results.empty:
            future_df = self._future_results_only(self.results)
            valid_keys: set[str] = set()
            for _, row in future_df.iterrows():
                key = (
                    f"{row.get('date','')} | {row.get('league','')} | "
                    f"{row.get('home_team','')} vs {row.get('away_team','')}"
                )
                valid_keys.add(key)
            invalid = [
                l["match_name"]
                for l in legs
                if l.get("match_key") not in valid_keys
            ]
            if invalid:
                names = "\n  • ".join(invalid)
                if not messagebox.askyesno(
                    "Advertencia",
                    f"Algunos partidos no están en el análisis actual o ya se han jugado:\n"
                    f"  • {names}\n\n¿Guardar de todos modos?",
                ):
                    return

        status    = self.sim_result_var.get().strip()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if len(legs) == 1:
            # ── Apuesta simple ───────────────────────────────────────────────
            leg    = legs[0]
            odds   = leg["odds"]
            profit = round((odds - 1) * stake, 2)
            pnl    = (
                0.0 if status == "PENDING"
                else profit if status == "WIN"
                else round(-stake, 2)
            )
            payload: dict = {
                "timestamp":    timestamp,
                "type":         "single",
                "match":        leg["match_name"],
                "pick":         leg["pick"],
                "odds":         odds,
                "stake":        round(stake, 2),
                "gross_return": round(stake * odds, 2),
                "net_profit":   profit,
                "status":       status,
                "pnl":          pnl,
            }
        else:
            # ── Acumulador multi-leg ─────────────────────────────────────────
            total_odds = round(math.prod(l["odds"] for l in legs), 4)
            profit = round((total_odds - 1) * stake, 2)
            pnl    = (
                0.0 if status == "PENDING"
                else profit if status == "WIN"
                else round(-stake, 2)
            )
            payload = {
                "timestamp":  timestamp,
                "type":       "accumulator",
                "legs": [
                    {"match": l["match_name"], "pick": l["pick"],
                     "odds": l["odds"], "status": "PENDING"}
                    for l in legs
                ],
                "total_odds":   total_odds,
                "stake":        round(stake, 2),
                "gross_return": round(stake * total_odds, 2),
                "net_profit":   profit,
                "status":       status,
                "pnl":          pnl,
            }

        db_id = self.storage.save_sim(payload)
        payload["_db_id"] = db_id
        self.bet_sim_history.insert(0, payload)
        self.execution_view.refresh_history_panel(self.bet_sim_history)
        self.execution_view.refresh_stats(self.bet_sim_history)

        # Limpiar el slip tras guardar
        self.execution_view._clear_slip()

        n = len(legs)
        msg = (
            f"Boleto guardado ✓\n{n} leg{'s' if n > 1 else ''}  ·  "
            f"Cuota total: {payload.get('total_odds', payload.get('odds', 0)):.2f}  ·  "
            f"Stake: {stake:.2f} €"
        )
        messagebox.showinfo("Simulator", msg)

    # ── Telegram Bot ──────────────────────────────────────────────────────────

    def update_bot_cache(self) -> None:
        """
        Rellena el caché de datos para el bot.
        DEBE ejecutarse en el hilo principal de tkinter (widget access seguro).
        El hilo del bot solo lee `self._bot_cache` — sin tocar widgets directamente.
        """
        try:
            self._update_bot_cache_inner()
        except Exception as exc:
            logger.error("update_bot_cache error: %s", exc, exc_info=True)
            # Notificar al bot si está corriendo
            if self._tg_bot:
                try:
                    self._tg_bot._notify(f"⚠ Error al actualizar caché: {exc}")
                except Exception:
                    pass

    def _update_bot_cache_inner(self) -> None:
        import re as _re

        # Definido inline — DESCOMPOSICION está en ui/views/quiniela.py,
        # no en core/quiniela_lae.py, así que evitamos el import circular
        _DESCOMPOSICION = {
            "1": ["H"], "X": ["D"], "2": ["A"],
            "1X": ["H", "D"], "X2": ["D", "A"],
            "12": ["H", "A"], "1X2": ["H", "D", "A"],
        }
        _MULT = {"1": 1, "X": 1, "2": 1, "1X": 2, "X2": 2, "12": 2, "1X2": 3}

        # ── Combinadas IA (de AccumulatorView — las mismas que ve el usuario) ──
        # Las legs son pd.Series; las convertimos a dicts planos aquí (hilo ppal)
        def _leg_to_dict(leg) -> dict:
            return {
                "match":       f"{leg.get('home_team','?')} vs {leg.get('away_team','?')}",
                "pick":        str(leg.get("pick", "?")),
                "odds":        float(leg.get("odds", 0) or 0),
                "edge":        float(leg.get("edge", 0) or 0),
                "ev":          float(leg.get("ev", 0) or 0),
                "reliability": int(leg.get("reliability_score", 0) or 0),
                "risk":        str(leg.get("risk_light", "?")),
                "market_type": str(leg.get("market_type", "1X2")),
                "p_home":      float(leg.get("p_home", 0) or 0),
                "p_draw":      float(leg.get("p_draw", 0) or 0),
                "p_away":      float(leg.get("p_away", 0) or 0),
                "p_over25":    float(leg.get("p_over25", 0) or 0),
            }

        bot_combos: list[dict] = []

        # 1. Apuesta recomendada (triple filtro)
        if not self.results.empty:
            try:
                from .core.accumulator import build_recommended_combo
                rec = build_recommended_combo(self.results)
                if rec and rec.get("legs"):
                    bot_combos.append({
                        "label":           "⭐ RECOMENDADA",
                        "n_legs":          rec.get("n_legs", 2),
                        "combined_odds":   rec.get("combined_odds", 0),
                        "combined_prob":   rec.get("combined_prob", 0),
                        "ev":              rec.get("ev", 0),
                        "avg_edge":        rec.get("avg_edge", 0),
                        "avg_reliability": rec.get("avg_reliability", 0),
                        "legs":            [_leg_to_dict(l) for l in rec["legs"]],
                    })
            except Exception as e:
                logger.debug("build_recommended_combo error: %s", e)

        # 2. Combinadas inteligentes (AccumulatorView)
        acum_combos = getattr(self.accumulator_view, "_combos", [])
        for combo in acum_combos[:4]:
            if not combo.get("legs"):
                continue
            bot_combos.append({
                "label":         f"{combo.get('n_legs','?')} legs",
                "n_legs":        combo.get("n_legs", 0),
                "combined_odds": combo.get("combined_odds", 0),
                "combined_prob": combo.get("combined_prob", 0),
                "ev":            combo.get("ev", 0),
                "avg_edge":      combo.get("avg_edge", 0),
                "avg_reliability": combo.get("avg_reliability", 0),
                "legs":          [_leg_to_dict(l) for l in combo["legs"]],
            })

        # Compatibilidad hacia atrás (combo_snapshot del Portfolio Builder)
        combo_snap = self._combo_snapshot()

        # ── Picks VERDE ───────────────────────────────────────────────────────
        results_green: list[dict] = []
        if not self.results.empty:
            verde = self.results[self.results["risk_light"] == "VERDE"]
            keep  = ["home_team", "away_team", "pick", "odds",
                     "edge", "ev", "reliability_score"]
            cols  = [c for c in keep if c in verde.columns]
            results_green = verde[cols].to_dict("records")

        # ── Quiniela (leemos tk.StringVar aquí, en el hilo principal) ─────────
        quiniela_picks: list[dict] = []
        quiniela_info:  dict       = {}
        q_rows = getattr(self.quiniela_view, "_rows", [])
        if q_rows:
            total_mult = 1
            total_prob = 1.0
            has_prob   = True

            for i, r in enumerate(q_rows):
                pick = r.pick_var.get()          # seguro — hilo principal
                total_mult *= _MULT.get(pick, 1)

                if r.p_h > 0:
                    prob_map = {"H": r.p_h, "D": r.p_d, "A": r.p_a}
                    p_pick   = sum(prob_map.get(x, 0) for x in _DESCOMPOSICION.get(pick, []))
                    total_prob *= max(p_pick, 1e-9)
                else:
                    has_prob = False

                quiniela_picks.append({
                    "num":      i + 1,
                    "home":     str(r.data.get("home_team", "?")),
                    "away":     str(r.data.get("away_team", "?")),
                    "pick":     pick,
                    "p_source": r.data.get("p_source"),
                    "p_home":   float(r.p_h or 0),
                    "p_draw":   float(r.p_d or 0),
                    "p_away":   float(r.p_a or 0),
                })

            # Número de jornada desde la etiqueta de estado (hilo principal)
            jornada = "?"
            try:
                txt = self.quiniela_view.status_lbl.cget("text")
                m   = _re.search(r"Jornada\s+(\S+)", txt)
                if m:
                    jornada = m.group(1)
            except Exception:
                pass

            quiniela_info = {
                "jornada":       jornada,
                "fecha":         getattr(self.quiniela_view, "_jornada_fecha", ""),
                "combinaciones": total_mult,
                "coste":         round(total_mult * 0.55, 2),
                "prob":          f"{total_prob:.3%}" if has_prob else "?",
            }

        # ── Escribir en el caché (dict plano, sin objetos tkinter) ────────────
        # Notificar al bot que hay datos frescos
        if self._tg_bot and (results_green or quiniela_picks or bot_combos):
            try:
                n_v = len(results_green)
                n_q = len(quiniela_picks)
                n_c = len(bot_combos)
                self._tg_bot._notify(
                    f"✓ Caché: {n_v} picks verdes, "
                    f"{n_c} combinada(s), "
                    f"{n_q} partidos quiniela"
                )
            except Exception:
                pass

        # ── Picks para notificaciones del bot ────────────────────────────────
        from datetime import date as _d
        _today_str = str(_d.today())
        _all_picks = self.storage.load_model_picks(limit=500)
        _today_picks = [
            p for p in _all_picks
            if str(p.get("date", ""))[:10] == _today_str
            and p.get("status") == "PENDING"
        ]
        _today_results = [
            p for p in _all_picks
            if str(p.get("settled_at", ""))[:10] == _today_str
            and p.get("status") in ("WIN", "LOSS")
        ]

        # ── Fixtures próximos del análisis (para /calendario) ─────────────────
        _upcoming: list[dict] = []
        if not self.results.empty:
            _keep_cols = [
                "date", "time", "league", "home_team", "away_team",
                "pick", "odds", "p_home", "p_draw", "p_away",
                "edge", "edge_1x2", "reliability_score", "risk_light",
            ]
            _avail = [c for c in _keep_cols if c in self.results.columns]
            _fut = self.results[
                self.results["date"].astype(str).str[:10] >= _today_str
            ][_avail].copy()
            # Normalizar edge
            if "edge_1x2" in _fut.columns and "edge" in _fut.columns:
                _fut["edge"] = _fut["edge_1x2"].combine_first(_fut["edge"])
            elif "edge_1x2" in _fut.columns:
                _fut["edge"] = _fut["edge_1x2"]
            # Normalizar hora
            if "time" in _fut.columns:
                def _norm_time(t):
                    s = str(t or "").strip()
                    if s.count(":") == 2:
                        s = s[:5]
                    return s if (len(s) in (4, 5) and ":" in s) else ""
                _fut["time"] = _fut["time"].apply(_norm_time)
            # Ordenar por fecha y hora
            sort_cols = [c for c in ("date", "time") if c in _fut.columns]
            if sort_cols:
                _fut = _fut.sort_values(sort_cols)
            _upcoming = _fut.to_dict("records")

        self._bot_cache = {
            "bot_combos":        bot_combos,
            "combo_snapshot":    combo_snap,
            "results_green":     results_green,
            "backtest_summary":  dict(self.backtest_summary),
            "n_total":           len(self.results) if not self.results.empty else 0,
            "n_picks":           len(results_green),
            "last_analysis":     self._last_analysis_ts,
            "quiniela_picks":    quiniela_picks,
            "quiniela_info":     quiniela_info,
            # ── Notificaciones automáticas ─────────────────────────────────────
            "all_picks":         _all_picks,
            "today_picks":       _today_picks,
            "today_results":     _today_results,
            "bankroll_eur":      self.bankroll_eur.get(),
            # ── Calendario ────────────────────────────────────────────────────
            "upcoming_fixtures": _upcoming,
        }
        logger.debug("Bot cache actualizado: %d picks verdes, %d legs quiniela",
                     len(results_green), len(quiniela_picks))

    def _bot_data_provider(self) -> dict:
        """Devuelve el caché precomputado — seguro desde cualquier hilo."""
        return self._bot_cache

    def _bot_status_update(self, msg: str) -> None:
        """Recibe mensajes de estado del hilo del bot y los muestra en la UI (thread-safe)."""
        def _ui_update(m=msg):
            try:
                self.settings_view.append_bot_log(m)
                # Si el mensaje indica arranque correcto, actualizar indicador
                if "Listo" in m or "escuchando" in m:
                    self.settings_view.update_bot_status(running=True)
                elif "Token inválido" in m or "detenido" in m.lower():
                    self.settings_view.update_bot_status(running=False)
            except Exception:
                pass
        self.after(0, _ui_update)

    def start_telegram_bot(self) -> None:
        """Inicia el bot de Telegram en segundo plano."""
        from .core.telegram_bot import TelegramBot
        token = self.settings_view.get_token()
        if not token or ":" not in token:
            messagebox.showerror("Bot Telegram",
                                 "Configura el Bot Token primero en ⚙️ Strategy.\n"
                                 "Créalo en @BotFather si aún no tienes uno.")
            return
        if self._tg_bot and self._tg_bot.running:
            messagebox.showinfo("Bot Telegram", "El bot ya está en marcha.")
            return
        try:
            self._tg_bot = TelegramBot(token)
            self._tg_bot.set_data_provider(self._bot_data_provider)
            self._tg_bot.set_status_callback(self._bot_status_update)
            # Acceso a BD para /apostar, /pendientes, /resultado, /bankroll
            self._tg_bot.set_storage(self.storage)
            # Callback para que el bot solicite una actualización del caché
            # desde el hilo principal (tkinter-safe)
            self._tg_bot.set_refresh_callback(
                lambda: self.after(0, self.update_bot_cache)
            )
            self._tg_bot.start()
            self.settings_view.update_bot_status(running=True)
            self.settings_view.append_bot_log("Iniciando bot…")
            # Poblar el caché con los datos actuales al arrancar
            # (captura análisis / quiniela cargados ANTES de iniciar el bot)
            self.after(300, self.update_bot_cache)
        except Exception as exc:
            messagebox.showerror("Bot Telegram", f"Error al iniciar el bot:\n{exc}")

    def stop_telegram_bot(self) -> None:
        """Detiene el bot de Telegram."""
        if self._tg_bot:
            self._tg_bot.stop()
        self.settings_view.update_bot_status(running=False)
        messagebox.showinfo("Bot Telegram", "Bot detenido.")

    @property
    def bot_running(self) -> bool:
        return self._tg_bot is not None and self._tg_bot.running

    # ── Telegram (envío directo) ───────────────────────────────────────────────

    def send_telegram_text(self, text: str) -> None:
        token   = self.settings_view.get_token()
        chat_id = self.settings_view.get_chat_id()

        if not token or ":" not in token:
            raise ValueError("Token de Telegram inválido.")
        if not chat_id:
            raise ValueError("Chat ID vacío.")

        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        data = resp.json()
        if not (resp.ok and data.get("ok")):
            raise RuntimeError(data.get("description", "Error desconocido de Telegram"))

    def send_combo(self) -> None:
        text = self._combo_message()
        if not text:
            messagebox.showwarning("Telegram", "No hay combinada disponible.")
            return
        try:
            self.send_telegram_text(text)
            self._add_history_entry(sent=True)
            messagebox.showinfo("Telegram", "Combinada enviada.")
        except Exception as exc:
            messagebox.showerror("Telegram", f"Error: {exc}")
