# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/alerts.py — Vista de Alertas: Monitor de Líneas + Ajuste de Bajas.

Dos paneles en una sola vista:
  ① Monitor de Líneas: tabla de odds en tiempo real + alertas steam detectadas
  ② Ajuste de Bajas:   panel manual para introducir ausencias + prob ajustada
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT
from ...core.injury_adjuster import (
    InjuryAdjuster, PlayerAbsence,
    POS_LABELS, ROLE_LABELS,
)
from ...core.lineups import get_lineup_for_match
from ..widgets import make_card, make_textbox

if TYPE_CHECKING:
    from ...app import PremiumApp


import logging

logger = logging.getLogger(__name__)


class AlertsView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app: "PremiumApp", **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()
        # Actualizar cada 30 s si el monitor está corriendo
        self._schedule_refresh()

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_monitor_section()
        self._build_injury_section()
        self._build_lineups_section()

    # ─────────────────────────────────────────────────────────────────────────
    # SECCIÓN 1: Monitor de Líneas
    # ─────────────────────────────────────────────────────────────────────────

    def _build_monitor_section(self) -> None:
        card = make_card(self, "📡 Monitor de Líneas — Steam & Movimientos")
        card.pack(fill="x", pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 12))

        # ── Fila de estado + controles ────────────────────────────────────────
        ctrl_row = ctk.CTkFrame(body, fg_color="transparent")
        ctrl_row.pack(fill="x", pady=(0, 8))

        self._monitor_status_lbl = ctk.CTkLabel(
            ctrl_row, text="🔴  Monitor detenido",
            text_color="#ef4444", font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._monitor_status_lbl.pack(side="left")

        self._last_poll_lbl = ctk.CTkLabel(
            ctrl_row, text="", text_color=MUTED,
            font=ctk.CTkFont(size=10),
        )
        self._last_poll_lbl.pack(side="left", padx=(12, 0))

        self._start_btn = ctk.CTkButton(
            ctrl_row, text="▶  Iniciar Monitor",
            command=self._start_monitor,
            fg_color="#166534", hover_color="#14532d", width=140,
        )
        self._start_btn.pack(side="right", padx=(8, 0))

        self._stop_btn = ctk.CTkButton(
            ctrl_row, text="⏹  Detener",
            command=self._stop_monitor,
            fg_color="#991b1b", hover_color="#7f1d1d", width=100,
            state="disabled",
        )
        self._stop_btn.pack(side="right")

        self._poll_btn = ctk.CTkButton(
            ctrl_row, text="🔄  Poll Manual",
            command=self._manual_poll,
            fg_color=CARD_2, width=120,
        )
        self._poll_btn.pack(side="right", padx=(0, 8))

        # ── Explicación ───────────────────────────────────────────────────────
        ctk.CTkLabel(
            body,
            text=(
                "🔴 STEAM: caída >2.5% en probabilidad implícita (dinero sharp detectado)\n"
                "🟡 LINE_MOVE: movimiento 1.5–2.5% (seguimiento de línea)"
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # ── Tabla de snapshots actuales ───────────────────────────────────────
        ctk.CTkLabel(
            body, text="Cuotas actuales (Pinnacle sharp reference)",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))

        snap_frame = ctk.CTkFrame(body, fg_color=CARD_2, corner_radius=8)
        snap_frame.pack(fill="x", pady=(0, 10))

        headers = ["Liga", "Local", "Visitante", "1", "X", "2", "O2.5", "U2.5"]
        widths  = [50,     120,     120,          55,  55,  55,  55,     55]
        for col, (h, w) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(
                snap_frame, text=h, text_color=MUTED,
                font=ctk.CTkFont(size=10, weight="bold"), width=w,
            ).grid(row=0, column=col, padx=4, pady=4, sticky="w")

        self._snap_frame      = snap_frame
        self._snap_row_widgets: list[list] = []

        # ── Log de alertas ────────────────────────────────────────────────────
        ctk.CTkLabel(
            body, text="Alertas detectadas",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(8, 4))

        self._alerts_log = make_textbox(body, height=160)
        self._alerts_log.pack(fill="x")
        self._alerts_log.configure(state="disabled")

    # ─────────────────────────────────────────────────────────────────────────
    # SECCIÓN 2: Ajuste de Bajas
    # ─────────────────────────────────────────────────────────────────────────

    def _build_injury_section(self) -> None:
        card = make_card(self, "🏥 Ajuste de Bajas — Corrección de Probabilidades")
        card.pack(fill="x", pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 12))

        # ── Descripción ───────────────────────────────────────────────────────
        ctk.CTkLabel(
            body,
            text=(
                "Introduce bajas conocidas antes del partido. El sistema ajusta las "
                "probabilidades del modelo con factores empíricos calibrados."
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left", wraplength=720,
        ).pack(anchor="w", pady=(0, 10))

        # ── Partido seleccionado ──────────────────────────────────────────────
        sel_row = ctk.CTkFrame(body, fg_color="transparent")
        sel_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(sel_row, text="Partido:", text_color=MUTED).pack(side="left")
        self._match_var = tk.StringVar(value="— Selecciona un partido —")
        self._match_menu = ctk.CTkOptionMenu(
            sel_row, variable=self._match_var,
            values=["— Selecciona un partido —"],
            fg_color=CARD_2, button_color=ACCENT, button_hover_color=ACCENT_2,
            text_color=TEXT, width=360,
        )
        self._match_menu.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            sel_row, text="↻ Refrescar lista",
            command=self._refresh_match_list,
            fg_color=CARD_2, width=130,
        ).pack(side="left", padx=8)

        # ── Formulario de baja ────────────────────────────────────────────────
        form = ctk.CTkFrame(body, fg_color=CARD_2, corner_radius=8)
        form.pack(fill="x", pady=(0, 8))

        form_inner = ctk.CTkFrame(form, fg_color="transparent")
        form_inner.pack(fill="x", padx=10, pady=8)

        # Fila 1: nombre + equipo
        row1 = ctk.CTkFrame(form_inner, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(row1, text="Jugador:", text_color=MUTED, width=70).pack(side="left")
        self._player_entry = ctk.CTkEntry(
            row1, fg_color="#0a1e0c", border_color=BORDER, text_color=TEXT,
            placeholder_text="Nombre del jugador", width=200,
        )
        self._player_entry.pack(side="left", padx=(4, 16))

        ctk.CTkLabel(row1, text="Equipo:", text_color=MUTED, width=55).pack(side="left")
        self._team_var = tk.StringVar(value="home")
        ctk.CTkRadioButton(
            row1, text="Local", variable=self._team_var, value="home",
            text_color=TEXT, fg_color=ACCENT,
        ).pack(side="left", padx=4)
        ctk.CTkRadioButton(
            row1, text="Visitante", variable=self._team_var, value="away",
            text_color=TEXT, fg_color=ACCENT,
        ).pack(side="left", padx=4)

        # Fila 2: rol + posición + razón
        row2 = ctk.CTkFrame(form_inner, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(row2, text="Rol:", text_color=MUTED, width=70).pack(side="left")
        self._role_var = tk.StringVar(value="KEY")
        ctk.CTkOptionMenu(
            row2, variable=self._role_var,
            values=list(ROLE_LABELS.keys()),
            fg_color=CARD_2, button_color=ACCENT, button_hover_color=ACCENT_2,
            text_color=TEXT, width=160,
        ).pack(side="left", padx=(4, 16))

        ctk.CTkLabel(row2, text="Posición:", text_color=MUTED, width=70).pack(side="left")
        self._pos_var = tk.StringVar(value="MID")
        ctk.CTkOptionMenu(
            row2, variable=self._pos_var,
            values=list(POS_LABELS.keys()),
            fg_color=CARD_2, button_color=ACCENT, button_hover_color=ACCENT_2,
            text_color=TEXT, width=140,
        ).pack(side="left", padx=(4, 16))

        ctk.CTkLabel(row2, text="Motivo:", text_color=MUTED, width=55).pack(side="left")
        self._reason_entry = ctk.CTkEntry(
            row2, fg_color="#0a1e0c", border_color=BORDER, text_color=TEXT,
            placeholder_text="Lesión / Suspensión / …", width=180,
        )
        self._reason_entry.pack(side="left", padx=4)

        # Botones del formulario
        btn_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(4, 0))

        ctk.CTkButton(
            btn_row, text="+ Añadir Baja",
            command=self._add_absence,
            fg_color=ACCENT, hover_color=ACCENT_2,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="🗑 Limpiar todas",
            command=self._clear_absences,
            fg_color="#991b1b", hover_color="#7f1d1d",
        ).pack(side="left", padx=8)

        # ── Lista de bajas activas ────────────────────────────────────────────
        ctk.CTkLabel(
            body, text="Bajas activas",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(10, 4))

        self._absence_listbox = make_textbox(body, height=100)
        self._absence_listbox.pack(fill="x")
        self._absence_listbox.configure(state="disabled")

        # ── Panel de probabilidad ajustada ────────────────────────────────────
        prob_card = ctk.CTkFrame(body, fg_color=CARD_2, corner_radius=8)
        prob_card.pack(fill="x", pady=(10, 0))

        prob_inner = ctk.CTkFrame(prob_card, fg_color="transparent")
        prob_inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(
            prob_inner, text="Probabilidad ajustada por bajas",
            text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", pady=(0, 6))

        self._prob_text = make_textbox(prob_inner, height=90)
        self._prob_text.pack(fill="x")
        self._prob_text.configure(state="disabled")

        ctk.CTkButton(
            prob_inner, text="Calcular ajuste",
            command=self._calculate_adjustment,
            fg_color=ACCENT, hover_color=ACCENT_2,
        ).pack(anchor="w", pady=(8, 0))

    # ── Lógica del monitor ────────────────────────────────────────────────────

    def _start_monitor(self) -> None:
        api_key = self.app.storage.get_setting("odds_api_key", "")
        if not api_key:
            messagebox.showwarning(
                "Monitor de Líneas",
                "Configura tu API key de The Odds API en ⚙️ Strategy primero.",
            )
            return

        if self.app.line_monitor and self.app.line_monitor.is_running():
            return

        from ...core.line_monitor import LineMonitor
        divs = [
            v[0] for v in self.app._selected_leagues_divs()
        ] if hasattr(self.app, "_selected_leagues_divs") else ["E0", "SP1", "I1"]

        # Bug fix: _selected_leagues_divs() ya devuelve list[str], no list[tuple]
        divs = (
            self.app._selected_leagues_divs()
            if hasattr(self.app, "_selected_leagues_divs")
            else ["E0", "SP1", "I1"]
        )

        self.app.line_monitor = LineMonitor(
            api_key=api_key,
            div_codes=divs,
            storage=self.app.storage,
            on_alert=self._on_alert_received,
        )
        self.app.line_monitor.start()
        self._update_monitor_status()

    def _stop_monitor(self) -> None:
        if self.app.line_monitor:
            self.app.line_monitor.stop()
        self._update_monitor_status()

    def _manual_poll(self) -> None:
        if not self.app.line_monitor:
            self._start_monitor()
            return
        import threading
        threading.Thread(
            target=self.app.line_monitor.poll_once,
            daemon=True,
        ).start()
        self.after(3000, self.refresh)

    def _on_alert_received(self, alert) -> None:
        """Callback desde el hilo del monitor.

        Bug fix: no tocar tk.BooleanVar ni widgets desde este hilo de fondo.
        Todo se programa en el hilo principal con after(0, ...).
        """
        try:
            self.after(0, lambda a=alert: self._handle_alert_main_thread(a))
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _handle_alert_main_thread(self, alert) -> None:
        """Ejecutado en el hilo principal de tkinter."""
        self._append_alert(alert)
        try:
            if self.app.telegram_enabled.get():  # seguro: estamos en el main thread
                self.app.send_telegram_text(alert.message)
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _append_alert(self, alert) -> None:
        try:
            self._alerts_log.configure(state="normal")
            self._alerts_log.insert("end", alert.message + "\n")
            self._alerts_log.configure(state="disabled")
            self._alerts_log.see("end")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _update_monitor_status(self) -> None:
        running = bool(self.app.line_monitor and self.app.line_monitor.is_running())
        if running:
            self._monitor_status_lbl.configure(
                text="🟢  Monitor activo — escuchando movimientos",
                text_color="#22c55e",
            )
            self._start_btn.configure(state="disabled")
            self._stop_btn.configure(state="normal")
        else:
            self._monitor_status_lbl.configure(
                text="🔴  Monitor detenido",
                text_color="#ef4444",
            )
            self._start_btn.configure(state="normal")
            self._stop_btn.configure(state="disabled")

    def refresh(self) -> None:
        """Refresca tabla de snapshots y estado del monitor."""
        self._update_monitor_status()

        # Timestamp del último poll
        if self.app.line_monitor:
            ts = self.app.line_monitor.last_poll_time()
            if ts:
                self._last_poll_lbl.configure(text=f"Último poll: {ts}")

        # Actualizar tabla de snapshots
        if self.app.line_monitor:
            snaps = self.app.line_monitor.get_snapshots()
            self._update_snap_table(list(snaps.values()))

        # Recargar alertas del monitor
        if self.app.line_monitor:
            alerts = self.app.line_monitor.get_alerts(max_items=80)
            self._reload_alerts_log(alerts)

    def _update_snap_table(self, snaps) -> None:
        # Limpiar filas antiguas
        for widgets in self._snap_row_widgets:
            for w in widgets:
                try:
                    w.destroy()
                except Exception:
                    logger.debug("Excepción ignorada", exc_info=True)
        self._snap_row_widgets.clear()

        for row_idx, snap in enumerate(snaps[:20], start=1):
            def _fmt(v: float) -> str:
                return f"{v:.2f}" if v > 1.0 else "—"

            cells = [
                snap.div,
                snap.home_team[:16],
                snap.away_team[:16],
                _fmt(snap.home_odds),
                _fmt(snap.draw_odds),
                _fmt(snap.away_odds),
                _fmt(snap.over25_odds),
                _fmt(snap.under25_odds),
            ]
            widths = [50, 120, 120, 55, 55, 55, 55, 55]
            row_color = "#091408" if row_idx % 2 == 0 else "#0a1e0c"
            row_widgets = []
            for col, (text, w) in enumerate(zip(cells, widths)):
                lbl = ctk.CTkLabel(
                    self._snap_frame, text=text, text_color=TEXT,
                    font=ctk.CTkFont(size=10), width=w,
                    fg_color=row_color, corner_radius=0,
                )
                lbl.grid(row=row_idx, column=col, padx=4, pady=2, sticky="w")
                row_widgets.append(lbl)
            self._snap_row_widgets.append(row_widgets)

    def _reload_alerts_log(self, alerts) -> None:
        try:
            self._alerts_log.configure(state="normal")
            self._alerts_log.delete("1.0", "end")
            for alert in reversed(alerts):
                self._alerts_log.insert("end", alert.message + "\n")
            self._alerts_log.configure(state="disabled")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    # ── Lógica de bajas ───────────────────────────────────────────────────────

    def _refresh_match_list(self) -> None:
        matches = ["— Selecciona un partido —"]
        results = getattr(self.app, "results", None)
        if results is not None and not results.empty:
            for _, row in results.iterrows():
                home = row.get("home_team", "")
                away = row.get("away_team", "")
                div  = row.get("div", "")
                if home and away:
                    matches.append(f"{div}: {home} vs {away}")
        self._match_menu.configure(values=matches)
        if len(matches) > 1:
            self._match_var.set(matches[1])

    def _add_absence(self) -> None:
        player = self._player_entry.get().strip()
        if not player:
            messagebox.showwarning("Baja", "Introduce el nombre del jugador.")
            return

        absence = PlayerAbsence(
            player_name=player,
            team=self._team_var.get(),
            role=self._role_var.get(),
            position=self._pos_var.get(),
            reason=self._reason_entry.get().strip() or "Lesión",
        )
        self.app.injury_adjuster.add(absence)
        self._player_entry.delete(0, "end")
        self._reason_entry.delete(0, "end")
        self._refresh_absence_list()

    def _clear_absences(self) -> None:
        self.app.injury_adjuster.clear()
        self._refresh_absence_list()
        self._clear_prob_text()

    def _refresh_absence_list(self) -> None:
        lines = self.app.injury_adjuster.summary_lines()
        try:
            self._absence_listbox.configure(state="normal")
            self._absence_listbox.delete("1.0", "end")
            if lines:
                self._absence_listbox.insert("end", "\n".join(lines))
            else:
                self._absence_listbox.insert("end", "Sin bajas introducidas.")
            self._absence_listbox.configure(state="disabled")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _calculate_adjustment(self) -> None:
        match_str = self._match_var.get()
        if "—" in match_str:
            messagebox.showinfo("Ajuste", "Selecciona un partido de la lista primero.")
            return

        if not self.app.injury_adjuster.has_absences():
            messagebox.showinfo("Ajuste", "Añade al menos una baja para calcular el ajuste.")
            return

        # Buscar probabilidades base en los resultados actuales
        results = getattr(self.app, "results", None)
        if results is None or results.empty:
            messagebox.showwarning("Ajuste", "Ejecuta el análisis primero.")
            return

        # Parsear "DIV: Local vs Visitante"
        try:
            rest      = match_str.split(": ", 1)[1]
            home_name = rest.split(" vs ")[0].strip()
            away_name = rest.split(" vs ")[1].strip()
        except Exception:
            messagebox.showerror("Ajuste", "No se pudo identificar el partido.")
            return

        row = results[
            (results["home_team"] == home_name) &
            (results["away_team"] == away_name)
        ]
        if row.empty:
            messagebox.showwarning("Ajuste", "Partido no encontrado en los resultados actuales.")
            return

        r = row.iloc[0]
        hp = float(r.get("home_prob") or r.get("model_prob") or 0.0)
        dp = float(r.get("draw_prob") or 0.0)
        ap = float(r.get("away_prob") or 0.0)

        # Si no tenemos todas las probs, intentar reconstruirlas
        if hp + dp + ap < 0.5:
            messagebox.showwarning(
                "Ajuste",
                "Probabilidades base no disponibles.\n"
                "Asegúrate de que el análisis haya generado columnas home_prob/draw_prob/away_prob.",
            )
            return

        summary = self.app.injury_adjuster.impact_summary(hp, dp, ap)

        try:
            self._prob_text.configure(state="normal")
            self._prob_text.delete("1.0", "end")
            self._prob_text.insert("end", summary)
            self._prob_text.configure(state="disabled")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _clear_prob_text(self) -> None:
        try:
            self._prob_text.configure(state="normal")
            self._prob_text.delete("1.0", "end")
            self._prob_text.configure(state="disabled")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    # ─────────────────────────────────────────────────────────────────────────
    # SECCIÓN 3: Alineaciones pre-partido (ESPN, sin registro)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_lineups_section(self) -> None:
        card = make_card(self, "🏟️ Alineaciones Pre-Partido")
        card.pack(fill="x", pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 12))

        # ── Cabecera ──────────────────────────────────────────────────────────
        hdr_row = ctk.CTkFrame(body, fg_color="transparent")
        hdr_row.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(
            hdr_row,
            text="Datos vía ESPN · gratis · sin registro · disponibles ~1h antes del partido.",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(side="left")

        ctk.CTkLabel(
            hdr_row,
            text="📡 ESPN",
            text_color=ACCENT, font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="right")

        # ── Fila de búsqueda ──────────────────────────────────────────────────
        search_row = ctk.CTkFrame(body, fg_color="transparent")
        search_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            search_row, text="Partido:", text_color=MUTED, width=55,
        ).pack(side="left")

        self._lineup_match_var = tk.StringVar(value="")
        self._lineup_entry = ctk.CTkEntry(
            search_row,
            textvariable=self._lineup_match_var,
            fg_color="#0a1e0c", border_color=BORDER, text_color=TEXT,
            placeholder_text="Ej: Real Madrid vs Barcelona  (YYYY-MM-DD)",
            width=340,
        )
        self._lineup_entry.pack(side="left", padx=(4, 8))

        self._lineup_date_var = tk.StringVar(value="")
        self._lineup_date_entry = ctk.CTkEntry(
            search_row,
            textvariable=self._lineup_date_var,
            fg_color="#0a1e0c", border_color=BORDER, text_color=TEXT,
            placeholder_text="YYYY-MM-DD",
            width=110,
        )
        self._lineup_date_entry.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            search_row, text="Buscar",
            command=self._fetch_lineups,
            fg_color=ACCENT, hover_color=ACCENT_2, width=80,
        ).pack(side="left")

        # ── Mensaje de estado ─────────────────────────────────────────────────
        self._lineup_status_lbl = ctk.CTkLabel(
            body,
            text="Introduce 'Local vs Visitante' y la fecha para buscar la alineación.",
            text_color=MUTED, font=ctk.CTkFont(size=11),
            wraplength=680, justify="left",
        )
        self._lineup_status_lbl.pack(anchor="w", pady=(0, 6))

        # ── Panel de dos columnas ─────────────────────────────────────────────
        cols_frame = ctk.CTkFrame(body, fg_color=CARD_2, corner_radius=8)
        cols_frame.pack(fill="x", pady=(0, 6))
        cols_frame.columnconfigure(0, weight=1)
        cols_frame.columnconfigure(1, weight=1)

        # LOCAL
        home_col = ctk.CTkFrame(cols_frame, fg_color="transparent")
        home_col.grid(row=0, column=0, padx=10, pady=8, sticky="nsew")

        ctk.CTkLabel(
            home_col, text="LOCAL",
            text_color=ACCENT, font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")

        self._home_formation_lbl = ctk.CTkLabel(
            home_col, text="Formación: —",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._home_formation_lbl.pack(anchor="w")

        self._home_players_box = make_textbox(home_col, height=200)
        self._home_players_box.pack(fill="x", pady=(4, 0))
        self._home_players_box.configure(state="disabled")

        # VISITANTE
        away_col = ctk.CTkFrame(cols_frame, fg_color="transparent")
        away_col.grid(row=0, column=1, padx=10, pady=8, sticky="nsew")

        ctk.CTkLabel(
            away_col, text="VISITANTE",
            text_color="#60a5fa", font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w")

        self._away_formation_lbl = ctk.CTkLabel(
            away_col, text="Formación: —",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._away_formation_lbl.pack(anchor="w")

        self._away_players_box = make_textbox(away_col, height=200)
        self._away_players_box.pack(fill="x", pady=(4, 0))
        self._away_players_box.configure(state="disabled")

        # ── Fuente de datos ───────────────────────────────────────────────────
        self._lineup_calls_lbl = ctk.CTkLabel(
            body, text="Fuente: ESPN API pública · Premier League, LaLiga, Serie A, Bundesliga, Ligue 1",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        self._lineup_calls_lbl.pack(anchor="w")

    # ── Lógica de alineaciones ────────────────────────────────────────────────

    def _fetch_lineups(self) -> None:
        """Lee el campo de partido, llama a ESPN y muestra resultados."""
        raw = self._lineup_match_var.get().strip()
        date = self._lineup_date_var.get().strip()

        if not raw or "vs" not in raw.lower():
            messagebox.showwarning(
                "Alineaciones",
                "Formato: 'Local vs Visitante' en el campo partido.",
            )
            return

        if not date:
            from datetime import date as _date
            date = str(_date.today())

        try:
            parts = raw.split(" vs ", 1)
            if len(parts) != 2:
                parts = raw.split(" VS ", 1)
            home_team = parts[0].strip()
            away_team = parts[1].strip()
        except Exception:
            messagebox.showerror("Alineaciones", "No se pudo parsear el partido.")
            return

        self._lineup_status_lbl.configure(text="Buscando alineaciones…")
        self.update_idletasks()

        import threading

        def _worker():
            lineup = get_lineup_for_match(home_team, away_team, date)
            self.after(0, lambda: self._display_lineups(lineup, home_team, away_team))

        threading.Thread(target=_worker, daemon=True).start()

    def _display_lineups(self, lineup: dict, home_team: str, away_team: str) -> None:
        """Muestra los resultados de la búsqueda en el panel de dos columnas."""
        self._update_calls_label()

        if not lineup:
            self._lineup_status_lbl.configure(
                text=(
                    f"Alineación no disponible para {home_team} vs {away_team}. "
                    "Puede que el partido no esté en ESPN o las alineaciones aún no se han publicado (~1h antes)."
                ),
            )
            self._clear_lineup_boxes()
            return

        # Formaciones
        self._home_formation_lbl.configure(
            text=f"Formación: {lineup.get('home_formation', '?')}",
        )
        self._away_formation_lbl.configure(
            text=f"Formación: {lineup.get('away_formation', '?')}",
        )

        # Titulares locales
        home_starters = lineup.get("home_starting", [])
        self._set_players_box(self._home_players_box, home_starters)

        # Titulares visitantes
        away_starters = lineup.get("away_starting", [])
        self._set_players_box(self._away_players_box, away_starters)

        self._lineup_status_lbl.configure(
            text=f"Alineaciones de {home_team} vs {away_team} cargadas correctamente.",
        )

    def _set_players_box(self, box, players: list[str]) -> None:
        """Rellena un textbox con la lista de jugadores numerada."""
        try:
            box.configure(state="normal")
            box.delete("1.0", "end")
            if players:
                for i, name in enumerate(players, 1):
                    box.insert("end", f"{i:2}. {name}\n")
            else:
                box.insert("end", "Alineación no disponible")
            box.configure(state="disabled")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _clear_lineup_boxes(self) -> None:
        """Limpia los textboxes de alineaciones."""
        for box in (self._home_players_box, self._away_players_box):
            try:
                box.configure(state="normal")
                box.delete("1.0", "end")
                box.insert("end", "Alineación no disponible")
                box.configure(state="disabled")
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)
        self._home_formation_lbl.configure(text="Formación: —")
        self._away_formation_lbl.configure(text="Formación: —")

    def _update_calls_label(self) -> None:
        """Sin límite con ESPN — no-op."""

    # ── Refresh periódico ─────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        try:
            self.refresh()
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)
        self.after(30_000, self._schedule_refresh)
