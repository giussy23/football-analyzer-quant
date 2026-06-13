# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/settings.py — Vista Settings: Telegram, parámetros de estrategia.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import requests

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD_2, MUTED, TEXT
from ..widgets import make_card, make_textbox


import logging

logger = logging.getLogger(__name__)


class SettingsView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()

    def _build(self):
        self._build_theme_picker()
        self._build_odds_api()
        self._build_line_monitor()
        self._build_bankroll()
        self._build_claude_api()
        self._build_injury_api()
        self._build_betfair_api()
        self._build_telegram()
        self._build_combo_settings()
        self._build_info()

    def _build_theme_picker(self):
        from ...core.themes import THEMES, theme_names

        card = make_card(self, "🎨  Tema de color")
        card.pack(fill="x", pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=12, pady=(0, 14))

        ctk.CTkLabel(
            body,
            text="Elige el esquema de color de la app. El cambio es instantáneo.",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 10))

        # Fila de swatches
        swatches_row = ctk.CTkFrame(body, fg_color="transparent")
        swatches_row.pack(fill="x")

        saved = self.app.storage.get_setting("theme", "Navy")
        self._theme_swatch_btns: dict[str, ctk.CTkButton] = {}

        for col, name in enumerate(theme_names()):
            t = THEMES[name]
            is_active = (name == saved)

            col_frame = ctk.CTkFrame(swatches_row, fg_color="transparent")
            col_frame.grid(row=0, column=col, padx=6)

            # Círculo de color (botón cuadrado redondeado)
            swatch_btn = ctk.CTkButton(
                col_frame,
                text="✓" if is_active else "",
                width=44, height=44,
                corner_radius=22,
                fg_color=t["swatch"],
                hover_color=t["accent"],
                text_color="#ffffff",
                font=ctk.CTkFont(size=16, weight="bold"),
                command=lambda n=name: self._select_theme(n),
            )
            swatch_btn.pack()

            # Nombre debajo del swatch
            ctk.CTkLabel(
                col_frame,
                text=t["label"],
                text_color=TEXT if is_active else MUTED,
                font=ctk.CTkFont(size=9, weight="bold" if is_active else "normal"),
            ).pack(pady=(4, 0))

            self._theme_swatch_btns[name] = swatch_btn

        # Nota
        self._theme_note = ctk.CTkLabel(
            body,
            text="Los paneles de contenido mostrarán el tema completo al refrescarse.",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        self._theme_note.pack(anchor="w", pady=(10, 0))

    def _select_theme(self, name: str) -> None:
        """Aplica el tema seleccionado y actualiza los swatches."""
        from ...core.themes import THEMES

        # Actualizar apariencia de swatches
        for n, btn in self._theme_swatch_btns.items():
            is_active = (n == name)
            btn.configure(text="✓" if is_active else "")

        # Aplicar tema a la app
        self.app.apply_theme(name, save=True)

        # Feedback visual
        self._theme_note.configure(
            text=f"✅  Tema '{name}' aplicado.",
            text_color=ACCENT,
        )
        self.after(2500, lambda: self._theme_note.configure(
            text="Los paneles de contenido mostrarán el tema completo al refrescarse.",
            text_color=MUTED,
        ))

    def _build_odds_api(self):
        card = make_card(self, "⚡ The Odds API — Cuotas en tiempo real")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        # Descripción
        ctk.CTkLabel(
            tb,
            text="Plan gratuito · 500 peticiones/mes · Sin tarjeta de crédito",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 10))

        # Campo API key
        ctk.CTkLabel(tb, text="API Key", text_color=MUTED).pack(anchor="w")
        self.odds_api_key_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*",
            placeholder_text="Pega aquí tu API key de the-odds-api.com",
        )
        self.odds_api_key_entry.pack(fill="x", pady=(4, 10))
        saved_key = self.app.storage.get_setting("odds_api_key", "")
        if saved_key:
            self.odds_api_key_entry.insert(0, saved_key)

        # Toggle de activación
        ctk.CTkCheckBox(
            tb,
            text="Usar The Odds API (cuotas actualizadas en tiempo real)",
            variable=self.app.use_odds_api,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=(0, 10))

        # Botones
        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(
            btn_row, text="Probar API Key",
            command=self._test_odds_api,
            fg_color="#0a2210",
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar",
            command=self.app.save_settings,
            fg_color=ACCENT,
        ).pack(side="left", padx=8)

        # Link de registro
        ctk.CTkLabel(
            tb,
            text="👉  Regístrate gratis en:  the-odds-api.com",
            text_color="#22c55e", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(8, 0))

    def _build_line_monitor(self):
        card = make_card(self, "📡 Monitor de Líneas — Configuración")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(
            tb,
            text=(
                "Detecta steam moves (dinero sharp) y movimientos de línea en tiempo real.\n"
                "Usa la misma API key de The Odds API configurada arriba. Sin coste adicional."
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # Intervalo de poll
        ctk.CTkLabel(
            tb, text="Intervalo de polling (minutos):", text_color=MUTED,
        ).pack(anchor="w")
        self._poll_interval_slider = ctk.CTkSlider(
            tb, from_=2, to=15, number_of_steps=13,
        )
        saved_interval = int(self.app.storage.get_setting("line_poll_interval", "5"))
        self._poll_interval_slider.set(saved_interval)
        self._poll_interval_slider.pack(fill="x", pady=(4, 2))

        self._poll_interval_lbl = ctk.CTkLabel(
            tb, text=f"{saved_interval} min", text_color=MUTED,
        )
        self._poll_interval_lbl.pack(anchor="w")
        self._poll_interval_slider.configure(
            command=lambda v: self._poll_interval_lbl.configure(text=f"{int(v)} min")
        )

        # Umbral de steam
        ctk.CTkLabel(
            tb, text="Umbral steam (% caída en prob):", text_color=MUTED,
        ).pack(anchor="w", pady=(6, 0))
        self._steam_thresh_slider = ctk.CTkSlider(
            tb, from_=1.0, to=5.0, number_of_steps=8,
        )
        saved_thresh = float(self.app.storage.get_setting("steam_threshold_pct", "2.5"))
        self._steam_thresh_slider.set(saved_thresh)
        self._steam_thresh_slider.pack(fill="x", pady=(4, 2))

        self._steam_thresh_lbl = ctk.CTkLabel(
            tb, text=f"{saved_thresh:.1f}%", text_color=MUTED,
        )
        self._steam_thresh_lbl.pack(anchor="w")
        self._steam_thresh_slider.configure(
            command=lambda v: self._steam_thresh_lbl.configure(text=f"{float(v):.1f}%")
        )

        # Guardar
        ctk.CTkButton(
            tb, text="Guardar configuración del monitor",
            command=self._save_monitor_settings,
            fg_color=ACCENT,
        ).pack(anchor="w", pady=(10, 0))

    def _save_monitor_settings(self) -> None:
        interval = int(self._poll_interval_slider.get())
        thresh   = float(self._steam_thresh_slider.get())
        self.app.storage.set_setting("line_poll_interval", interval)
        self.app.storage.set_setting("steam_threshold_pct", thresh)
        from tkinter import messagebox
        messagebox.showinfo("Monitor", f"Guardado: poll cada {interval} min, steam ≥ {thresh:.1f}%")

    def _build_bankroll(self):
        card = make_card(self, "💰 Banca — P&L en euros reales")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(
            tb,
            text=(
                "Configura tu banca total en euros. El Tracker de Resultados mostrará\n"
                "stake real y P&L en euros en lugar de unidades de banca."
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 10))

        row = ctk.CTkFrame(tb, fg_color="transparent")
        row.pack(anchor="w")

        ctk.CTkLabel(row, text="Banca total:", text_color=MUTED, width=100).pack(side="left")
        self._bankroll_entry = ctk.CTkEntry(
            row, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            placeholder_text="Ej: 1000", width=140,
        )
        self._bankroll_entry.pack(side="left", padx=(6, 8))
        ctk.CTkLabel(row, text="€", text_color=TEXT,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        saved = self.app.storage.get_setting("bankroll_eur", "0")
        if saved and saved != "0":
            self._bankroll_entry.insert(0, saved)

        ctk.CTkButton(
            tb, text="Guardar banca",
            command=self.app.save_settings,
            fg_color=ACCENT, hover_color=ACCENT_2,
        ).pack(anchor="w", pady=(10, 0))

    def get_bankroll_eur(self) -> str:
        try:
            return self._bankroll_entry.get().strip()
        except Exception:
            return "0"

    def _build_claude_api(self):
        card = make_card(self, "🧠 Claude IA — Análisis narrativo de picks")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(
            tb,
            text="Genera análisis en lenguaje natural para cada pick VERDE/AMARILLO tras el análisis",
            text_color="#22c55e", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(tb, text="API Key (Anthropic)", text_color="#98d4aa").pack(anchor="w")
        self.anthropic_key_entry = ctk.CTkEntry(
            tb, fg_color="#091408", border_color="#2dd45b", text_color="#f0fff4",
            show="*",
            placeholder_text="sk-ant-api03-...",
        )
        self.anthropic_key_entry.pack(fill="x", pady=(4, 10))
        saved_key = self.app.storage.get_setting("anthropic_api_key", "")
        if saved_key:
            self.anthropic_key_entry.insert(0, saved_key)

        ctk.CTkCheckBox(
            tb,
            text="Activar análisis IA con Claude tras cada Run Analysis",
            variable=self.app.use_claude_analysis,
            text_color="#f0fff4", fg_color="#22c55e",
        ).pack(anchor="w", pady=(0, 10))

        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 4))
        self._claude_test_btn = ctk.CTkButton(
            btn_row, text="Probar API Key",
            command=self._test_claude_api,
            fg_color="#0a2210",
        )
        self._claude_test_btn.pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar",
            command=self.app.save_settings,
            fg_color="#22c55e",
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            tb,
            text="👉  Consigue tu API key gratuita en:  console.anthropic.com",
            text_color="#22c55e", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(8, 0))

    def _build_injury_api(self):
        card = make_card(self, "🩹 Lesiones en tiempo real — API-Football")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(
            tb,
            text=(
                "Plan gratuito · 100 peticiones/día · Sin tarjeta de crédito\n"
                "Proporciona impacto real de lesiones por equipo en cada partido analizado."
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(tb, text="API Key (API-Football)", text_color=MUTED).pack(anchor="w")
        self.injury_api_key_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*",
            placeholder_text="Pega aquí tu API key de api-sports.io",
        )
        self.injury_api_key_entry.pack(fill="x", pady=(4, 10))
        saved_key = self.app.storage.get_setting("injury_api_key", "")
        if saved_key:
            self.injury_api_key_entry.insert(0, saved_key)

        ctk.CTkCheckBox(
            tb,
            text="Activar datos de lesiones en tiempo real al analizar",
            variable=self.app.use_injury_api,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=(0, 10))

        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 8))

        self._inj_test_btn = ctk.CTkButton(
            btn_row, text="Probar API Key",
            command=self._test_injury_api,
            fg_color="#0a2210",
        )
        self._inj_test_btn.pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar",
            command=self.app.save_settings,
            fg_color=ACCENT,
        ).pack(side="left", padx=8)

        # Etiqueta de estado de la prueba
        self._inj_status_lbl = ctk.CTkLabel(
            tb, text="", text_color=MUTED, font=ctk.CTkFont(size=11),
        )
        self._inj_status_lbl.pack(anchor="w", pady=(4, 0))

        ctk.CTkLabel(
            tb,
            text="👉  Regístrate gratis en:  dashboard.api-football.com",
            text_color="#22c55e", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(8, 0))

    def _test_injury_api(self) -> None:
        """Valida la API key de API-Football en un hilo de fondo."""
        key = self.get_injury_api_key()
        if not key:
            messagebox.showwarning("Lesiones", "Introduce una API key primero.")
            return

        self._inj_test_btn.configure(state="disabled", text="Probando…")
        self._inj_status_lbl.configure(text="Conectando con API-Football…", text_color=MUTED)

        def _worker():
            try:
                import requests
                resp = requests.get(
                    "https://v3.football.api-sports.io/status",
                    headers={"x-apisports-key": key},
                    timeout=10,
                )
                data = resp.json()
                account = data.get("response", {}).get("account", {})
                sub     = data.get("response", {}).get("subscription", {})
                limit   = data.get("response", {}).get("requests", {})

                remaining = limit.get("current", "?")
                total_day = limit.get("limit_day", "?")
                plan      = sub.get("plan", "?")
                msg = f"✅ Conexión correcta\nPlan: {plan}\nPeticiones hoy: {remaining}/{total_day}"
                ok  = True
            except Exception as exc:
                msg = f"❌ Error: {exc}"
                ok  = False

            def _show():
                self._inj_test_btn.configure(state="normal", text="Probar API Key")
                color = "#22c55e" if ok else "#ef4444"
                self._inj_status_lbl.configure(text=msg, text_color=color)

            self.after(0, _show)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def get_injury_api_key(self) -> str:
        return self.injury_api_key_entry.get().strip()

    def _build_betfair_api(self):
        card = make_card(self, "🟢 Betfair Exchange — Auto-ejecución de apuestas")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            tb,
            text=(
                "⚠️  Coloca apuestas REALES directamente en Betfair Exchange.\n"
                "Necesitas una cuenta Betfair y una Developer App Key.\n"
                "Obtén tu clave en: betfair.com → Cuenta → API Developers → Developer App Keys"
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(tb, text="App Key (Developer)", text_color=MUTED).pack(anchor="w")
        self.betfair_app_key_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*",
            placeholder_text="Tu Developer App Key de Betfair",
        )
        self.betfair_app_key_entry.pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(tb, text="Usuario Betfair", text_color=MUTED).pack(anchor="w")
        self.betfair_username_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            placeholder_text="tu@email.com o usuario Betfair",
        )
        self.betfair_username_entry.pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(tb, text="Contraseña Betfair", text_color=MUTED).pack(anchor="w")
        self.betfair_password_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*",
            placeholder_text="••••••••",
        )
        self.betfair_password_entry.pack(fill="x", pady=(4, 10))

        # Cargar valores guardados
        saved_ak = self.app.storage.get_setting("betfair_app_key", "")
        saved_us = self.app.storage.get_setting("betfair_username", "")
        saved_pw = self.app.storage.get_setting("betfair_password", "")
        if saved_ak: self.betfair_app_key_entry.insert(0, saved_ak)
        if saved_us: self.betfair_username_entry.insert(0, saved_us)
        if saved_pw: self.betfair_password_entry.insert(0, saved_pw)

        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(
            btn_row, text="🔗  Probar conexión",
            command=self._test_betfair_login,
            fg_color="#064e3b", hover_color="#065f46",
            height=32, corner_radius=8,
        ).pack(side="left", padx=(0, 8))
        self._betfair_status_lbl = ctk.CTkLabel(
            btn_row, text="", text_color=MUTED, font=ctk.CTkFont(size=11)
        )
        self._betfair_status_lbl.pack(side="left")

    def _test_betfair_login(self) -> None:
        """Prueba las credenciales de Betfair en un hilo de fondo."""
        ak = self.get_betfair_app_key()
        us = self.get_betfair_username()
        pw = self.get_betfair_password()
        if not ak or not us or not pw:
            self._betfair_status_lbl.configure(
                text="Completa App Key, usuario y contraseña.", text_color="#f87171"
            )
            return

        self._betfair_status_lbl.configure(text="Conectando...", text_color="#facc15")

        def _worker():
            try:
                from ...core.betfair import BetfairClient
                client = BetfairClient(ak, us, pw)
                ok, msg = client.login()
                if ok:
                    balance = client.get_balance()
                    bal_str = f"  |  Saldo: €{balance:.2f}" if balance is not None else ""
                    self._betfair_status_lbl.configure(
                        text=f"✅ Conectado{bal_str}", text_color="#4ade80"
                    )
                else:
                    self._betfair_status_lbl.configure(text=msg, text_color="#f87171")
            except Exception as exc:
                self._betfair_status_lbl.configure(
                    text=f"Error: {exc}", text_color="#f87171"
                )

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def get_betfair_app_key(self) -> str:
        return self.betfair_app_key_entry.get().strip()

    def get_betfair_username(self) -> str:
        return self.betfair_username_entry.get().strip()

    def get_betfair_password(self) -> str:
        return self.betfair_password_entry.get()

    def _build_telegram(self):
        card = make_card(self, "📲 Telegram — Bot interactivo + notificaciones")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        # ── Credenciales ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            tb,
            text="Crea tu bot en @BotFather (Telegram) y pega el token aquí",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(tb, text="Bot Token", text_color=MUTED).pack(anchor="w")
        self.token_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*", placeholder_text="123456789:AAxxxxxx…",
        )
        self.token_entry.pack(fill="x", pady=(4, 10))
        token = self.app.storage.get_setting("telegram_token", "")
        if token:
            self.token_entry.insert(0, token)

        ctk.CTkLabel(
            tb,
            text="Chat ID (para notificaciones automáticas — opcional con el bot)",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(tb, text="Chat ID", text_color=MUTED).pack(anchor="w")
        self.chat_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            placeholder_text="p. ej. -100123456789",
        )
        self.chat_entry.pack(fill="x", pady=(4, 10))
        chat_id = self.app.storage.get_setting("telegram_chat_id", "")
        if chat_id:
            self.chat_entry.insert(0, chat_id)

        # ── Opciones de notificación ──────────────────────────────────────────
        flags = ctk.CTkFrame(tb, fg_color="transparent")
        flags.pack(fill="x", pady=(0, 8))
        ctk.CTkCheckBox(
            flags, text="Telegram activado",
            variable=self.app.telegram_enabled,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            flags, text="Enviar combinada al Chat ID",
            variable=self.app.send_combo_enabled,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            flags, text="Auto-enviar tras análisis",
            variable=self.app.auto_send_after_analysis,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)

        # ── Botones de notificación ───────────────────────────────────────────
        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(
            btn_row, text="Test envío",
            command=self._test_telegram,
            fg_color="#0a2210",
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar",
            command=self.app.save_settings,
            fg_color=ACCENT,
        ).pack(side="left", padx=8)

        # ── Separador ─────────────────────────────────────────────────────────
        ctk.CTkFrame(tb, fg_color="#1a3d22", height=1).pack(fill="x", pady=(0, 12))

        # ── Bot interactivo ───────────────────────────────────────────────────
        ctk.CTkLabel(
            tb, text="🤖  Bot interactivo",
            text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            tb,
            text=(
                "El bot escucha comandos de cualquier usuario que le escriba.\n"
                "Comandos disponibles: /combinadas · /picks · /estado · /quiniela · /ayuda"
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 8))

        # Estado del bot
        status_row = ctk.CTkFrame(tb, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 8))

        self._bot_status_lbl = ctk.CTkLabel(
            status_row, text="🔴  Bot detenido",
            text_color="#ef4444", font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._bot_status_lbl.pack(side="left")

        # Botones start / stop
        bot_btns = ctk.CTkFrame(tb, fg_color="transparent")
        bot_btns.pack(fill="x")

        self._start_bot_btn = ctk.CTkButton(
            bot_btns, text="▶  Iniciar Bot",
            command=self.app.start_telegram_bot,
            fg_color="#166534", hover_color="#14532d",
            width=130,
        )
        self._start_bot_btn.pack(side="left")

        self._stop_bot_btn = ctk.CTkButton(
            bot_btns, text="⏹  Detener Bot",
            command=self.app.stop_telegram_bot,
            fg_color="#991b1b", hover_color="#7f1d1d",
            width=130, state="disabled",
        )
        self._stop_bot_btn.pack(side="left", padx=8)

        # ── Log de actividad del bot ──────────────────────────────────────────
        ctk.CTkLabel(
            tb, text="Actividad del bot:",
            text_color=MUTED, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(10, 2))

        self._bot_log = make_textbox(tb, height=90)
        self._bot_log.pack(fill="x")
        self._bot_log.configure(state="disabled")
        self._bot_log_lines: list[str] = []

        # ── Auditoría automática ──────────────────────────────────────────────
        ctk.CTkFrame(tb, fg_color="#1a3d22", height=1).pack(fill="x", pady=(12, 10))
        ctk.CTkLabel(
            tb, text="🔍  Auditoría automática",
            text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            tb,
            text=(
                "Liquida picks pendientes, recalcula Sharpe/ROI/Drawdown y alerta\n"
                "si detecta rachas negativas, drawdown alto o win rate bajo."
            ),
            text_color=MUTED, font=ctk.CTkFont(size=11), justify="left",
        ).pack(anchor="w", pady=(0, 8))

        audit_row = ctk.CTkFrame(tb, fg_color="transparent")
        audit_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(audit_row, text="Intervalo:", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left")

        _AUDIT_OPTIONS = {
            "Desactivada":  "0",
            "Cada 15 min":  "15",
            "Cada 30 min":  "30",   # ← default
            "Cada hora":    "60",
            "Cada 6 horas": "360",
        }
        _AUDIT_REVERSE = {v: k for k, v in _AUDIT_OPTIONS.items()}
        saved_interval = self.app.storage.get_setting("audit_interval_min", "30")
        self._audit_var = ctk.StringVar(
            value=_AUDIT_REVERSE.get(saved_interval, "Cada 30 min"))

        def _on_audit_interval_change(choice: str) -> None:
            mins = _AUDIT_OPTIONS.get(choice, "30")
            self.app.storage.set_setting("audit_interval_min", mins)
            # Reiniciar el loop con el nuevo intervalo
            try:
                if int(mins) > 0:
                    self.app._schedule_next_audit(int(mins))
                elif self.app._audit_after_id:
                    self.app.after_cancel(self.app._audit_after_id)
                    self.app._audit_after_id = None
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)

        ctk.CTkOptionMenu(
            audit_row,
            values=list(_AUDIT_OPTIONS.keys()),
            variable=self._audit_var,
            command=_on_audit_interval_change,
            fg_color="#0a2210", button_color=ACCENT,
            width=140,
        ).pack(side="left", padx=8)

        # Notificar por Telegram
        import tkinter as _tk
        self._audit_tg_var = _tk.BooleanVar(
            value=self.app.storage.get_setting("audit_telegram", "0") == "1")

        def _toggle_audit_tg():
            self.app.storage.set_setting(
                "audit_telegram", "1" if self._audit_tg_var.get() else "0")

        ctk.CTkCheckBox(
            tb,
            text="Enviar alertas de auditoría por Telegram",
            variable=self._audit_tg_var,
            command=_toggle_audit_tg,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=(4, 4))

        # Botón de auditoría manual
        audit_btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        audit_btn_row.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(
            audit_btn_row,
            text="🔍  Auditar ahora",
            command=lambda: self.app._auto_audit_tick(),
            fg_color="#0a2210", hover_color="#14532d",
            width=140,
        ).pack(side="left")

        self._audit_status_lbl = ctk.CTkLabel(
            audit_btn_row, text="",
            text_color=MUTED, font=ctk.CTkFont(size=10))
        self._audit_status_lbl.pack(side="left", padx=10)

    def _build_combo_settings(self):
        card = make_card(self, "Combo Builder — Configuración")
        card.pack(fill="x", pady=(0, 10))

        cb = ctk.CTkFrame(card, fg_color="transparent")
        cb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(cb, text="Tamaño de combinada (patas)", text_color=MUTED).pack(anchor="w", pady=(0, 4))
        ctk.CTkSlider(
            cb, from_=2, to=5, number_of_steps=3,
            variable=self.app.combo_size,
        ).pack(fill="x")

    def _build_info(self):
        card = make_card(self, "Información")
        card.pack(fill="x")

        info = make_textbox(card, height=340)
        info.pack(fill="x", padx=12, pady=(0, 12))
        info.insert(
            "end",
            "AlphaBet  ·  v15.0\n"
            "\n"
            "«Donde el análisis se convierte en ventaja.»\n"
            "\n"
            "No vendemos certezas — en las apuestas no existen.\n"
            "Ofrecemos algo más valioso: método, rigor y honestidad.\n"
            "\n"
            "Cada pick nace de modelos que aprenden de miles de partidos,\n"
            "se calibran contra resultados reales y se miden frente al\n"
            "mercado antes de llegar a ti. Detrás de cada número hay una\n"
            "razón — y aquí siempre la verás: sin humo, sin promesas\n"
            "vacías, sin atajos.\n"
            "\n"
            "No se trata de acertar una vez, sino de decidir mejor una y\n"
            "otra vez, con la disciplina de quien sabe cuidar su banca.\n"
            "\n"
            "Hecho con obsesión por el detalle, para quien se toma esto\n"
            "en serio.\n"
            "\n"
            "──────────────────────────────────────────────\n"
            "Uso exclusivamente informativo. No constituye asesoramiento\n"
            "financiero ni garantiza resultados. Juega con responsabilidad.\n"
            "\n"
            "© 2026 Francesco Giuseppe Manolache.\n"
            "Todos los derechos reservados · Software de uso privado.\n"
        )
        info.configure(state="disabled")


    # ── Claude / Anthropic helpers ─────────────────────────────────────────────

    def get_anthropic_api_key(self) -> str:
        return self.anthropic_key_entry.get().strip()

    def _test_claude_api(self) -> None:
        """Valida la API key en un hilo de fondo para no congelar la UI."""
        key = self.get_anthropic_api_key()
        if not key:
            messagebox.showwarning("Claude IA", "Introduce una API key primero.")
            return

        self._claude_test_btn.configure(state="disabled", text="Probando...")

        def _worker():
            from ...core.ai_analysis import validate_anthropic_key
            ok, msg = validate_anthropic_key(key)

            def _show():
                self._claude_test_btn.configure(state="normal", text="Probar API Key")
                if ok:
                    messagebox.showinfo("Claude IA", msg)
                else:
                    messagebox.showerror("Claude IA", msg)

            self.app.after(0, _show)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Telegram helpers ───────────────────────────────────────────────────────

    def get_odds_api_key(self) -> str:
        return self.odds_api_key_entry.get().strip()

    def get_token(self) -> str:
        return self.token_entry.get().strip()

    def get_chat_id(self) -> str:
        return self.chat_entry.get().strip()

    def _test_odds_api(self):
        from tkinter import messagebox
        from ...core.odds_api import validate_api_key
        key = self.get_odds_api_key()
        ok, msg = validate_api_key(key)
        if ok:
            messagebox.showinfo("The Odds API", msg)
        else:
            messagebox.showerror("The Odds API", msg)

    def update_bot_status(self, running: bool) -> None:
        """Actualiza el indicador visual del bot (llamado desde app.py)."""
        if running:
            self._bot_status_lbl.configure(
                text="🟢  Bot en marcha — escuchando comandos",
                text_color="#22c55e",
            )
            self._start_bot_btn.configure(state="disabled")
            self._stop_bot_btn.configure(state="normal")
        else:
            self._bot_status_lbl.configure(
                text="🔴  Bot detenido",
                text_color="#ef4444",
            )
            self._start_bot_btn.configure(state="normal")
            self._stop_bot_btn.configure(state="disabled")

    def append_bot_log(self, msg: str) -> None:
        """Añade una línea al log de actividad del bot (máx 6 líneas)."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._bot_log_lines.append(line)
        # Mantener solo las últimas 6 líneas
        if len(self._bot_log_lines) > 6:
            self._bot_log_lines = self._bot_log_lines[-6:]
        try:
            self._bot_log.configure(state="normal")
            self._bot_log.delete("1.0", "end")
            self._bot_log.insert("end", "\n".join(self._bot_log_lines))
            self._bot_log.configure(state="disabled")
            self._bot_log.see("end")
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)

    def _test_telegram(self):
        try:
            self.app.send_telegram_text(
                "✅ Prueba correcta desde AlphaBet v15.0"
            )
            messagebox.showinfo("Telegram", "Mensaje de prueba enviado correctamente.")
        except Exception as exc:
            messagebox.showerror("Telegram", f"Error: {exc}")
