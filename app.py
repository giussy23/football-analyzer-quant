"""
app.py — Clase principal PremiumApp: orquesta vistas, lógica y datos.
"""

from __future__ import annotations

import logging
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
from .core.odds_api import fetch_odds_fixtures
from .core.storage import Storage
from .ui.views.accumulator import AccumulatorView
from .ui.views.quiniela import QuinielaView
from .ui.views.analysis import AnalysisView
from .ui.views.portfolio import ExecutionView, PortfolioView
from .ui.views.settings import SettingsView

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class PremiumApp(ctk.CTk):
    """Aplicación principal Football Analyzer Quant Pro v10.0."""

    def __init__(self) -> None:
        super().__init__()
        self.storage = Storage()

        self.title("Football Analyzer Quant Pro v10.0")
        self.geometry("1780x1040")
        self.configure(fg_color=BG)

        # ── State ─────────────────────────────────────────────────────────────
        self.results:          pd.DataFrame = pd.DataFrame()
        self.filtered:         pd.DataFrame = pd.DataFrame()
        self.backtest_summary: dict         = {}
        self.diagnostics:      list[str]    = []
        self.history:          list[dict]   = self.storage.load_combos()
        self.bet_sim_history:  list[dict]   = self.storage.load_sims()
        self.odds_api_remaining: Optional[str] = None

        # ── Settings vars ─────────────────────────────────────────────────────
        def _sv(key: str, default: str) -> tk.StringVar:
            return tk.StringVar(value=self.storage.get_setting(key, default))

        def _bv(key: str, default: str = "0") -> tk.BooleanVar:
            return tk.BooleanVar(value=self.storage.get_setting(key, default) == "1")

        self.edge1       = _sv("edge1",       "0.03")
        self.edge2       = _sv("edge2",       "0.03")
        self.unit_stake  = _sv("unit_stake",  "100")
        self.search_var  = tk.StringVar()
        self.only_green  = _bv("only_green",  "1")
        self.only_picks  = _bv("only_picks",  "0")

        self.use_odds_api            = _bv("use_odds_api",            "0")
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
            background="#0a1422", fieldbackground="#0a1422",
            foreground="#dbe7f8", rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#12233d", foreground="#eaf2ff",
            font=("Segoe UI Semibold", 10),
        )

    # ── UI layout ─────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_stage()

        self.show_analysis_view()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self, fg_color="#09121f", width=220,
            corner_radius=18, border_color=BORDER, border_width=1,
        )
        sidebar.grid(row=0, column=0, sticky="nsw", padx=(14, 10), pady=14)
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar, text="Football Analyzer\nQuant Pro v10",
            justify="left", text_color=TEXT,
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(18, 12))

        ctk.CTkLabel(
            sidebar, text="Walk-forward OOS · Kelly fraccionado · Módulos separados",
            justify="left", text_color=MUTED, wraplength=180,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("analysis",     "Trading Desk",    self.show_analysis_view),
            ("accumulator",  "⚡ Combinadas IA", self.show_accumulator_view),
            ("quiniela",     "⚽ Quiniela IA",   self.show_quiniela_view),
            ("execution",    "Manual Slip",     self.show_execution_view),
            ("portfolio",    "Portfolio",       self.show_portfolio_view),
            ("settings",     "Strategy",        self.show_settings_view),
        ]
        for key, label, cmd in nav_items:
            btn = ctk.CTkButton(
                sidebar, text=label, command=cmd,
                fg_color="#18253d", hover_color="#22365b", height=42,
            )
            btn.pack(fill="x", padx=14, pady=6)
            self._nav_btns[key] = btn

        ctk.CTkButton(
            sidebar, text="▶  Run Analysis",
            command=self.run_analysis,
            fg_color=ACCENT, hover_color=ACCENT_2, height=42,
        ).pack(fill="x", padx=14, pady=(16, 6))

        # ── Contador de peticiones API ─────────────────────────────────────
        api_card = ctk.CTkFrame(
            sidebar, fg_color="#0d1a2e", corner_radius=10,
            border_color="#1e2b44", border_width=1,
        )
        api_card.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            api_card, text="⚡ Odds API",
            text_color="#3b82f6", font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.api_counter_lbl = ctk.CTkLabel(
            api_card, text="— / 500 req.",
            text_color=MUTED, font=ctk.CTkFont(size=12),
        )
        self.api_counter_lbl.pack(anchor="w", padx=10, pady=(0, 8))

    def _build_stage(self) -> None:
        stage = ctk.CTkFrame(self, fg_color="transparent")
        stage.grid(row=0, column=1, sticky="nsew", padx=(0, 14), pady=14)
        stage.grid_rowconfigure(1, weight=1)
        stage.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(stage, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        self.view_title = ctk.CTkLabel(
            header, text="Analysis", text_color=TEXT,
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.view_title.grid(row=0, column=0, sticky="w")
        self.view_hint = ctk.CTkLabel(
            header, text="Solo próximos partidos, filtros y picks", text_color=MUTED
        )
        self.view_hint.grid(row=1, column=0, sticky="w")

        content = ctk.CTkFrame(stage, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.analysis_view    = AnalysisView(content, self)
        self.accumulator_view = AccumulatorView(content, self)
        self.quiniela_view    = QuinielaView(content, self)
        self.execution_view   = ExecutionView(content, self)
        self.portfolio_view   = PortfolioView(content, self)
        self.settings_view    = SettingsView(content, self)

        for view in [self.analysis_view, self.accumulator_view, self.quiniela_view,
                     self.execution_view, self.portfolio_view, self.settings_view]:
            view.grid(row=0, column=0, sticky="nsew")

    # ── Navigation ────────────────────────────────────────────────────────────

    _NAV_META = {
        "analysis":    ("Trading Desk",   "Top picks, mercado, tabla principal y ranking"),
        "accumulator": ("Combinadas IA",  "Combinadas 2-4 legs generadas por el modelo IA"),
        "quiniela":    ("Quiniela IA",    "Picks 1/X/2 con dobles, triples, coste y probabilidad"),
        "execution":   ("Manual Slip",    "Simulación manual 1X2, cuota, stake y retorno"),
        "portfolio":   ("Portfolio",      "Historial de combinadas, ROI y liquidación"),
        "settings":    ("Strategy",       "Telegram, combo builder y configuración"),
    }

    def _set_nav(self, active: str) -> None:
        for key, btn in self._nav_btns.items():
            btn.configure(fg_color=ACCENT if key == active else "#18253d")
        title, hint = self._NAV_META[active]
        self.view_title.configure(text=title)
        self.view_hint.configure(text=hint)

    def _hide_all(self) -> None:
        for v in [self.analysis_view, self.accumulator_view, self.quiniela_view,
                  self.execution_view, self.portfolio_view, self.settings_view]:
            v.grid_remove()

    def show_analysis_view(self):
        self._hide_all(); self.analysis_view.grid(); self._set_nav("analysis")

    def show_accumulator_view(self):
        self._hide_all(); self.accumulator_view.grid(); self._set_nav("accumulator")

    def show_quiniela_view(self):
        self._hide_all(); self.quiniela_view.grid(); self._set_nav("quiniela")

    def show_execution_view(self):
        self._hide_all(); self.execution_view.grid(); self._set_nav("execution")

    def show_portfolio_view(self):
        self._hide_all(); self.portfolio_view.grid(); self._set_nav("portfolio")
        self._refresh_portfolio()

    def show_settings_view(self):
        self._hide_all(); self.settings_view.grid(); self._set_nav("settings")

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
            "only_green":               int(self.only_green.get()),
            "only_picks":               int(self.only_picks.get()),
            "combo_size":               self.combo_size.get(),
        }
        for k, v in payload.items():
            self.storage.set_setting(k, v)

    # ── Main analysis pipeline ────────────────────────────────────────────────

    def run_analysis(self) -> None:
        try:
            self.save_settings()

            selected = [k for k, v in self.analysis_view.league_vars.items() if v.get()]
            if not selected:
                raise ValueError("Selecciona al menos una liga.")

            self.analysis_view.update_status("Descargando datos...")
            self.update_idletasks()

            # Descargar histórico solo para ligas que lo tienen (csv_url != None)
            hist = {}
            for name in selected:
                div, csv_url, _ = LEAGUE_MAP[name]
                if csv_url:
                    hist[div] = fetch_csv(csv_url)

            # ── Fuente de fixtures ────────────────────────────────────────────
            odds_api_key  = self.storage.get_setting("odds_api_key", "")
            use_odds_api  = self.use_odds_api.get() and bool(odds_api_key)

            if use_odds_api:
                self.analysis_view.update_status("⚡ Descargando cuotas en tiempo real (The Odds API)...")
                self.update_idletasks()
                div_codes = [LEAGUE_MAP[n][0] for n in selected]
                fixtures, remaining = fetch_odds_fixtures(odds_api_key, div_codes)
                self.odds_api_remaining = remaining
                self._update_api_counter()
                if fixtures.empty:
                    self.analysis_view.update_status("⚠ Sin fixtures de Odds API, usando football-data.co.uk...")
                    self.update_idletasks()
                    fixtures = fetch_csv(FIXTURES_URL)
            else:
                fixtures = fetch_csv(FIXTURES_URL)

            # Para ligas sin histórico (Mundial, Libertadores…) mostramos
            # solo cuotas en tiempo real sin predicción del modelo IA
            divs_with_history = [LEAGUE_MAP[n][0] for n in selected if LEAGUE_MAP[n][1]]
            divs_odds_only    = [LEAGUE_MAP[n][0] for n in selected if not LEAGUE_MAP[n][1]]

            if divs_odds_only and not divs_with_history:
                # Solo ligas sin histórico → mostrar cuotas directamente
                from .core.data import prepare_fixtures
                self.results = self._build_odds_only_df(prepare_fixtures(fixtures), divs_odds_only)
                self.backtest_summary = {}
                self.diagnostics = [
                    "Modo cuotas en tiempo real (sin modelo IA)",
                    f"Ligas: {', '.join(divs_odds_only)}",
                    f"Fixtures cargados: {len(self.results)}",
                ]
            else:
                self.analysis_view.update_status("Entrenando modelo...")
                self.update_idletasks()
                analyzer = Analyzer(hist, fixtures)
                self.results = analyzer.run(
                    divs_with_history,
                    float(self.edge1.get()),
                    float(self.edge2.get()),
                )
                # Añadir fixtures de ligas sin histórico (solo cuotas)
                if divs_odds_only:
                    from .core.data import prepare_fixtures
                    odds_df = self._build_odds_only_df(
                        prepare_fixtures(fixtures), divs_odds_only
                    )
                    if not odds_df.empty:
                        self.results = pd.concat(
                            [self.results, odds_df], ignore_index=True
                        )
                self.backtest_summary = analyzer.backtest_summary
                self.diagnostics      = analyzer.diagnostics
            self.filtered = self.results.copy()

            self.apply_filters()
            self._fill_summary()
            self._refresh_combo()
            self._refresh_simulator_matches()
            self.accumulator_view.refresh(self.results)
            self.quiniela_view.generate_ai(self.results)

            self.analysis_view.update_status("✓ Completado")
            logger.info("Análisis completado: %d fixtures", len(self.results))

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

        except Exception as exc:
            logger.exception("Error en run_analysis")
            messagebox.showerror("Error", str(exc))
            self.analysis_view.update_status("✗ Error")

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
                "analysis":          (
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
            clv_count = (
                int(self.results["clv"].notna().sum())
                if "clv" in self.results.columns else 0
            )
            self.analysis_view.update_metrics(total, picks, avg_roi, clv_count)

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
        """Liquida la fila seleccionada en el Treeview del historial."""
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

        # Buscar en memoria
        sim = next((s for s in self.bet_sim_history if s.get("_db_id") == db_id), None)
        if not sim:
            messagebox.showwarning("Historial", "Simulación no encontrada.")
            return
        if sim.get("status") != "PENDING":
            messagebox.showinfo("Historial", f"Ya está liquidada como {sim['status']}.")
            return

        stake = float(sim.get("stake", 0))
        odds  = float(sim.get("odds",  0))
        pnl   = round(stake * (odds - 1), 2) if result == "WIN" else round(-stake, 2)

        # Actualizar DB y memoria
        self.storage.update_sim_status(db_id, result, pnl)
        sim["status"] = result
        sim["pnl"]    = pnl

        self.execution_view.refresh_history_panel(self.bet_sim_history)
        self.execution_view.refresh_stats(self.bet_sim_history)
        self.execution_view.settle_lbl.configure(
            text=f"✓  Liquidada como {result}  (PnL {pnl:+.2f} €)"
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
        labels = [
            f"{row.get('date','')} | {row.get('league','')} | "
            f"{row.get('home_team','')} vs {row.get('away_team','')}"
            for _, row in df.iterrows()
        ]
        self.execution_view.refresh_match_list(labels)

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
        df = self._future_results_only(self.results)
        if df.empty:
            messagebox.showwarning("Simulator", "Primero ejecuta el análisis.")
            return
        try:
            stake = float(self.manual_stake_var.get())
            odds  = float(self.manual_odds_var.get())
        except ValueError:
            messagebox.showerror("Simulator", "Introduce stake y cuota válidos.")
            return
        if stake <= 0 or odds <= 1:
            messagebox.showerror("Simulator", "Stake > 0 y cuota > 1 requeridos.")
            return

        selected = self.sim_match_var.get().strip()
        chosen   = None
        for _, row in df.iterrows():
            label = (
                f"{row.get('date','')} | {row.get('league','')} | "
                f"{row.get('home_team','')} vs {row.get('away_team','')}"
            )
            if label == selected:
                chosen = row
                break

        if chosen is None:
            messagebox.showwarning("Simulator", "Selecciona un partido futuro válido.")
            return

        status  = self.sim_result_var.get().strip()
        profit  = round((odds - 1) * stake, 2)
        pnl     = 0.0 if status == "PENDING" else (profit if status == "WIN" else round(-stake, 2))

        payload = {
            "timestamp":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "league":      chosen.get("league", ""),
            "match":       f"{chosen.get('home_team','')} vs {chosen.get('away_team','')}",
            "pick":        self.manual_pick_var.get().strip(),
            "odds":        odds,
            "stake":       round(stake, 2),
            "gross_return": round(stake * odds, 2),
            "net_profit":   profit,
            "status":       status,
            "pnl":          pnl,
        }
        db_id = self.storage.save_sim(payload)
        payload["_db_id"] = db_id
        self.bet_sim_history.insert(0, payload)
        self.execution_view.refresh_history_panel(self.bet_sim_history)
        self.execution_view.refresh_stats(self.bet_sim_history)
        messagebox.showinfo("Simulator", "Apuesta guardada.")

    # ── Telegram ──────────────────────────────────────────────────────────────

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
