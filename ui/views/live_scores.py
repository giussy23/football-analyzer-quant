# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/live_scores.py — Seguimiento de marcadores en tiempo real.

Muestra únicamente los partidos donde el usuario tiene picks PENDING,
consultando la ESPN Scores API cada 60 segundos.
Cuando un partido termina y el pick queda resuelto, lanza un toast
y lo marca visualmente.
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime, date
from tkinter import ttk
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ...core.auto_settler import (
    _DIV_TO_ESPN, _FALLBACK_ORDER, _get, _team_match, pick_is_win,
)
from ..toast import show_toast

if TYPE_CHECKING:
    from ...app import PremiumApp

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Colores de estado
_STATUS_COLORS = {
    "live":      "#22c55e",    # verde vivo
    "ht":        "#fbbf24",    # ámbar mitad tiempo
    "ft":        "#6b7280",    # gris partido terminado
    "scheduled": "#60a5fa",    # azul programado
    "winning":   "#22c55e",
    "losing":    "#ef4444",
    "drawing":   "#fbbf24",
}

_REFRESH_INTERVAL = 60_000    # 60 segundos


def _fetch_live(league_div: str, today_str: str) -> list[dict]:
    """Descarga eventos del día para una liga ESPN."""
    espn_id = _DIV_TO_ESPN.get(league_div)
    if not espn_id:
        return []
    url  = f"{_ESPN_BASE}/{espn_id}/scoreboard"
    data = _get(url, {"dates": today_str})
    return data.get("events", [])


def _score_for_pick(event: dict) -> dict | None:
    """
    Extrae marcador, minuto y estado de un evento ESPN.
    Devuelve dict o None si el evento no tiene datos suficientes.
    """
    comps = event.get("competitions", [])
    if not comps:
        return None
    comp  = comps[0]
    competitors = comp.get("competitors", [])
    home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home_c or not away_c:
        return None

    status_obj = comp.get("status", {})
    status_type = status_obj.get("type", {})
    state   = status_type.get("name", "")       # STATUS_IN_PROGRESS / STATUS_FINAL / …
    display = status_type.get("shortDetail", "") # "45'", "HT", "FT", etc.
    completed = status_type.get("completed", False)

    try:
        hg = int(home_c.get("score", "") or 0)
        ag = int(away_c.get("score", "") or 0)
    except (ValueError, TypeError):
        hg = ag = 0

    kind = "scheduled"
    if completed:
        kind = "ft"
    elif "IN_PROGRESS" in state or "HALFTIME" in state:
        kind = "ht" if "HALF" in state else "live"

    return {
        "home_goals": hg,
        "away_goals": ag,
        "display":    display or state,
        "kind":       kind,
        "completed":  completed,
    }


class LiveScoresView(ctk.CTkFrame):
    """Pestaña de marcadores en tiempo real para picks PENDING."""

    def __init__(self, parent, app: "PremiumApp", **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app     = app
        self._rows: list[dict] = []
        self._refresh_job: str | None = None
        self._setup_style()
        self._build()
        self.refresh()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        s = ttk.Style()
        s.configure(
            "Live.Treeview",
            background="#050e1c", fieldbackground="#050e1c",
            foreground="#f0fff4", rowheight=30,
            font=("Segoe UI", 10),
        )
        s.configure(
            "Live.Treeview.Heading",
            background="#091408", foreground="#f0fff4",
            font=("Segoe UI Semibold", 10),
        )
        s.map("Live.Treeview", background=[("selected", "#1a4d2a")])

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_status_bar()
        self._build_table()

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar, text="Live Score Tracker",
            text_color=TEXT, font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            bar,
            text="Marcadores en tiempo real · Picks PENDING + Combinadas IA · Auto-refresh 60 s",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, sticky="w")

        btn_row = ctk.CTkFrame(bar, fg_color="transparent")
        btn_row.grid(row=0, column=1, rowspan=2, sticky="e")

        ctk.CTkButton(
            btn_row, text="🔄 Refrescar ahora",
            command=self._manual_refresh,
            fg_color=CARD, hover_color=CARD_2,
            border_color=BORDER, border_width=1, text_color=TEXT,
            height=36, corner_radius=10,
        ).pack(side="left", padx=(0, 6))

        self._auto_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            btn_row, text="Auto-refresh",
            variable=self._auto_var,
            command=self._toggle_auto,
            fg_color=ACCENT, hover_color=ACCENT_2,
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                           border_color=BORDER, border_width=1)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(1, weight=1)

        self._status_dot = ctk.CTkLabel(
            bar, text="●",
            text_color="#6b7280", font=ctk.CTkFont(size=14),
            width=24,
        )
        self._status_dot.grid(row=0, column=0, padx=(12, 4), pady=8)

        self._status_lbl = ctk.CTkLabel(
            bar, text="Cargando…",
            text_color=MUTED, font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._status_lbl.grid(row=0, column=1, sticky="ew", pady=8)

        self._last_update_lbl = ctk.CTkLabel(
            bar, text="",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        self._last_update_lbl.grid(row=0, column=2, padx=12, pady=8)

    def _build_table(self) -> None:
        shell = ctk.CTkFrame(
            self, fg_color="#060f07", corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        shell.grid(row=2, column=0, sticky="nsew")
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        cols = ("partido", "liga", "pick", "cuota", "marcador", "min", "estado", "resultado")
        self.tree = ttk.Treeview(
            shell, columns=cols, show="headings",
            style="Live.Treeview", selectmode="browse",
        )

        cfg = {
            "partido":   (220, "w"),
            "liga":      (70,  "center"),
            "pick":      (60,  "center"),
            "cuota":     (60,  "center"),
            "marcador":  (80,  "center"),
            "min":       (60,  "center"),
            "estado":    (100, "center"),
            "resultado": (110, "center"),
        }
        for col in cols:
            w, anch = cfg[col]
            self.tree.heading(col, text=col.upper())
            self.tree.column(col, width=w, anchor=anch, minwidth=w)

        # Tags de color
        self.tree.tag_configure("live",     foreground="#22c55e")
        self.tree.tag_configure("ht",       foreground="#fbbf24")
        self.tree.tag_configure("ft",       foreground="#6b7280")
        self.tree.tag_configure("sched",    foreground="#60a5fa")
        self.tree.tag_configure("winning",  foreground="#22c55e", background="#0c2918")
        self.tree.tag_configure("losing",   foreground="#ef4444", background="#2d0d0d")
        self.tree.tag_configure("drawing",  foreground="#fbbf24", background="#1a1400")
        # Picks de combinada IA (sin apuesta registrada aún)
        self.tree.tag_configure("ia_live",  foreground="#c4b5fd", background="#1a0a38")
        self.tree.tag_configure("ia_sched", foreground="#a78bfa", background="#120726")

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(shell, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

    # ── Refresh logic ─────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Arranca el ciclo de refresco (llamado al mostrar la vista)."""
        self._do_refresh()

    def _manual_refresh(self) -> None:
        if self._refresh_job:
            self.app.after_cancel(self._refresh_job)
            self._refresh_job = None
        self._do_refresh()

    def _do_refresh(self) -> None:
        self._status_dot.configure(text_color="#fbbf24")
        self._status_lbl.configure(text="Consultando ESPN…")

        picks = self.app.storage.load_model_picks(status="PENDING")
        today = date.today()
        today_str = str(today)

        # Solo picks cuya fecha sea hoy o ayer (en juego / recién terminados)
        active = []
        for p in picks:
            try:
                d = datetime.strptime(str(p["date"])[:10], "%Y-%m-%d").date()
                if (today - d).days <= 1:
                    active.append(p)
            except Exception:
                pass

        # ── Añadir fixtures de combinada IA del análisis actual ───────────────
        # Solo los de hoy con edge positivo que no estén ya en active
        results = getattr(self.app, "results", None)
        if results is not None and not results.empty:
            registered_pairs = {
                (str(p.get("home_team", "")), str(p.get("away_team", "")))
                for p in active
            }
            for _, row in results.iterrows():
                d = str(row.get("date", ""))[:10]
                if d != today_str:
                    continue
                try:
                    edge = float(row.get("edge_1x2") or row.get("edge") or 0)
                except Exception:
                    edge = 0.0
                if edge <= 0:
                    continue
                ht = str(row.get("home_team", ""))
                at = str(row.get("away_team", ""))
                if (ht, at) in registered_pairs:
                    continue
                registered_pairs.add((ht, at))
                try:
                    p_h = float(row.get("p_home") or 0)
                    p_d = float(row.get("p_draw") or 0)
                    p_a = float(row.get("p_away") or 0)
                except Exception:
                    p_h = p_d = p_a = 0.0
                # Normalizar hora
                raw_t = str(row.get("time", "") or "").strip()
                if raw_t.count(":") == 2:
                    raw_t = raw_t[:5]
                if len(raw_t) not in (4, 5) or ":" not in raw_t:
                    raw_t = ""
                active.append({
                    "_ia": True,
                    "id":        f"ia_{ht}_{at}",
                    "home_team": ht,
                    "away_team": at,
                    "pick":      str(row.get("pick", "")),
                    "league":    str(row.get("league", row.get("div", ""))),
                    "date":      today_str,
                    "time":      raw_t,
                    "odds":      None,
                    "status":    "PENDING",
                    "p_home":    p_h,
                    "p_draw":    p_d,
                    "p_away":    p_a,
                    "edge":      edge,
                    "reliability_score": float(row.get("reliability_score") or 0),
                })

        if not active:
            self._status_dot.configure(text_color="#6b7280")
            self._status_lbl.configure(text="No hay picks PENDING para hoy ni ayer")
            self._last_update_lbl.configure(
                text=f"Actualizado: {datetime.now().strftime('%H:%M:%S')}"
            )
            self._fill_table([])
            self._schedule_next()
            return

        threading.Thread(
            target=self._fetch_worker,
            args=(active, today.strftime("%Y%m%d")),
            daemon=True,
        ).start()

    def _fetch_worker(self, picks: list[dict], today_str: str) -> None:
        """Hilo de fondo: enriquece cada pick con datos ESPN."""
        # Precarga todos los eventos del día por liga para minimizar peticiones
        events_cache: dict[str, list] = {}
        needed_leagues: set[str] = set()
        for p in picks:
            lg = str(p.get("league", "")).strip()
            needed_leagues.add(lg)

        for lg in needed_leagues:
            div = lg  # normalmente almacenamos el div_code en la columna league
            espn_id = _DIV_TO_ESPN.get(div)
            if not espn_id:
                # Buscar en fallback
                for d, eid in _DIV_TO_ESPN.items():
                    events_cache.setdefault(eid, _fetch_live(d, today_str))
                break
            events_cache[espn_id] = _fetch_live(div, today_str)

        # También cargamos fallback completo si hay picks sin liga reconocida
        for eid in _FALLBACK_ORDER:
            if eid not in events_cache:
                events_cache[eid] = _fetch_live(
                    next(k for k, v in _DIV_TO_ESPN.items() if v == eid), today_str
                )

        all_events = []
        for evs in events_cache.values():
            all_events.extend(evs)

        rows: list[dict] = []
        for p in picks:
            home = str(p.get("home_team", ""))
            away = str(p.get("away_team", ""))
            match_info = self._find_event(home, away, all_events)
            rows.append({**p, "_live": match_info})

        self.app.after(0, lambda r=rows: self._on_fetch_done(r))

    def _find_event(self, home: str, away: str, events: list[dict]) -> dict | None:
        for ev in events:
            comps = ev.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]
            competitors = comp.get("competitors", [])
            hc = next((c for c in competitors if c.get("homeAway") == "home"), None)
            ac = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not hc or not ac:
                continue
            hn = hc.get("team", {}).get("displayName", "")
            an = ac.get("team", {}).get("displayName", "")
            if _team_match(home, hn) and _team_match(away, an):
                return _score_for_pick(ev)
        return None

    def _on_fetch_done(self, rows: list[dict]) -> None:
        """Llamado en el hilo principal con los datos enriquecidos."""
        self._rows = rows
        self._fill_table(rows)

        live_n  = sum(1 for r in rows if r.get("_live") and r["_live"].get("kind") == "live")
        ht_n    = sum(1 for r in rows if r.get("_live") and r["_live"].get("kind") == "ht")
        real_n  = sum(1 for r in rows if not r.get("_ia"))
        ia_n    = sum(1 for r in rows if r.get("_ia"))
        ia_part = f"  ·  ⚽ {ia_n} IA" if ia_n else ""

        if live_n:
            self._status_dot.configure(text_color="#22c55e")
            self._status_lbl.configure(
                text=f"{live_n} partido{'s' if live_n > 1 else ''} en directo  ·  {real_n} picks activos{ia_part}"
            )
        elif ht_n:
            self._status_dot.configure(text_color="#fbbf24")
            self._status_lbl.configure(text=f"Descanso  ·  {real_n} picks activos{ia_part}")
        else:
            self._status_dot.configure(text_color="#6b7280")
            self._status_lbl.configure(
                text=f"{real_n} picks activos hoy/ayer{ia_part} — sin partidos en directo ahora"
            )

        self._last_update_lbl.configure(
            text=f"Actualizado: {datetime.now().strftime('%H:%M:%S')}"
        )

        # Notificar picks ganados/perdidos con resultado final
        self._check_finished(rows)
        self._schedule_next()

    def _check_finished(self, rows: list[dict]) -> None:
        """
        Para picks cuyo partido acaba de terminar (kind=ft), lanza un toast
        y los auto-liquida si el resultado es claro.
        Los picks de combinada IA (_ia=True) no se auto-liquidan.
        """
        for r in rows:
            if r.get("_ia"):          # fixture IA — solo visualización, no liquidar
                continue
            live = r.get("_live")
            if not live or not live.get("completed"):
                continue
            pick_val = str(r.get("pick", ""))
            win = pick_is_win(pick_val, live)
            if win is None:
                continue

            home = r.get("home_team", "")
            away = r.get("away_team", "")
            score = f"{live['home_goals']}-{live['away_goals']}"
            title = f"{'✅ WIN' if win else '❌ LOSS'}  {pick_val}"
            msg   = f"{home[:20]} vs {away[:20]}  {score}"
            show_toast(
                self.app, title, msg,
                kind="success" if win else "loss",
                duration_ms=7000,
            )

    def _fill_table(self, rows: list[dict]) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        if not rows:
            return

        for idx, r in enumerate(rows):
            home  = r.get("home_team", "")
            away  = r.get("away_team", "")
            liga  = str(r.get("league", ""))[:8]
            pick  = str(r.get("pick", ""))
            odds  = r.get("odds")
            live  = r.get("_live")
            is_ia = bool(r.get("_ia"))

            # ── Columna "cuota": odds para picks reales, probabs para IA ─────
            if is_ia:
                p_h = r.get("p_home", 0.0)
                p_d = r.get("p_draw", 0.0)
                p_a = r.get("p_away", 0.0)
                edge = r.get("edge", 0.0)
                odds_str = f"e:{edge*100:+.0f}%"
            else:
                odds_str = f"{float(odds):.2f}" if odds else "—"

            # ── Partido: añadir "(IA)" a picks de combinada ─────────────────
            partido_str = f"{'⚽ ' if is_ia else ''}{home} vs {away}{' (IA)' if is_ia else ''}"

            if live:
                score   = f"{live['home_goals']}-{live['away_goals']}"
                min_str = live["display"]
                kind    = live["kind"]

                status_map = {
                    "live":  "🟢 EN JUEGO",
                    "ht":    "🟡 DESCANSO",
                    "ft":    "⬜ TERMINADO",
                    "scheduled": "🔵 PROGRAMADO",
                }
                estado_str = status_map.get(kind, kind)

                # Resultado parcial del pick
                win = pick_is_win(pick, live)
                if win is True:
                    result_str = "✅ Ganando"
                    tag = "ia_live" if is_ia else "winning"
                elif win is False:
                    result_str = "❌ Perdiendo"
                    tag = "ia_live" if is_ia else "losing"
                else:
                    result_str = "➖ Empate"
                    tag = "ia_live" if is_ia else "drawing"

                if kind == "ft":
                    result_str = ("✅ WIN" if win else "❌ LOSS") if win is not None else "—"
                    tag = "ft"
                elif kind == "scheduled":
                    score      = "—"
                    result_str = "—"
                    # Mostrar hora del partido si la tenemos
                    kick_time  = str(r.get("time", ""))
                    min_str    = kick_time if kick_time else "—"
                    tag        = "ia_sched" if is_ia else "sched"
            else:
                score      = "—"
                # Para picks IA sin datos ESPN, mostrar la hora del partido si existe
                kick_time  = str(r.get("time", ""))
                min_str    = kick_time if kick_time else "—"
                estado_str = "🔵 PROGRAMADO" if kick_time else "⚪ Sin datos"
                result_str = "—"
                tag        = "ia_sched" if is_ia else "sched"

            self.tree.insert(
                "", "end",
                iid=str(r["id"]),
                tags=(tag,),
                values=(
                    partido_str,
                    liga,
                    pick,
                    odds_str,
                    score,
                    min_str,
                    estado_str,
                    result_str,
                ),
            )

    # ── Auto-refresh ──────────────────────────────────────────────────────────

    def _schedule_next(self) -> None:
        if self._auto_var.get():
            self._refresh_job = self.app.after(_REFRESH_INTERVAL, self._do_refresh)

    def _toggle_auto(self) -> None:
        if not self._auto_var.get() and self._refresh_job:
            self.app.after_cancel(self._refresh_job)
            self._refresh_job = None
        elif self._auto_var.get():
            self._do_refresh()

    def on_show(self) -> None:
        """Llamado cuando la vista se hace visible."""
        self._do_refresh()

    def on_hide(self) -> None:
        """Llamado cuando la vista se oculta — para el auto-refresh."""
        if self._refresh_job:
            self.app.after_cancel(self._refresh_job)
            self._refresh_job = None
