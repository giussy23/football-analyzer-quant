"""
ui/views/settings.py — Vista Settings: Telegram, parámetros de estrategia.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import requests

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD_2, MUTED, TEXT
from ..widgets import make_card, make_textbox


class SettingsView(ctk.CTkScrollableFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._build()

    def _build(self):
        self._build_odds_api()
        self._build_telegram()
        self._build_combo_settings()
        self._build_info()

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
            fg_color="#1f3357",
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
            text_color="#3b82f6", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(8, 0))

    def _build_telegram(self):
        card = make_card(self, "Execution Hub — Telegram")
        card.pack(fill="x", pady=(0, 10))

        tb = ctk.CTkFrame(card, fg_color="transparent")
        tb.pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(tb, text="Bot Token", text_color=MUTED).pack(anchor="w")
        self.token_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            show="*",
        )
        self.token_entry.pack(fill="x", pady=(4, 10))
        token = self.app.storage.get_setting("telegram_token", "")
        if token:
            self.token_entry.insert(0, token)

        ctk.CTkLabel(tb, text="Chat ID", text_color=MUTED).pack(anchor="w")
        self.chat_entry = ctk.CTkEntry(
            tb, fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
        )
        self.chat_entry.pack(fill="x", pady=(4, 10))
        chat_id = self.app.storage.get_setting("telegram_chat_id", "")
        if chat_id:
            self.chat_entry.insert(0, chat_id)

        flags = ctk.CTkFrame(tb, fg_color="transparent")
        flags.pack(fill="x", pady=(0, 8))
        ctk.CTkCheckBox(
            flags, text="Telegram activado",
            variable=self.app.telegram_enabled,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            flags, text="Enviar combinada",
            variable=self.app.send_combo_enabled,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            flags, text="Auto-enviar tras análisis",
            variable=self.app.auto_send_after_analysis,
            text_color=TEXT, fg_color=ACCENT,
        ).pack(anchor="w", pady=2)

        btn_row = ctk.CTkFrame(tb, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(
            btn_row, text="Test Telegram",
            command=self._test_telegram,
            fg_color="#1f3357",
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="Guardar",
            command=self.app.save_settings,
            fg_color=ACCENT,
        ).pack(side="left", padx=8)

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
        card = make_card(self, "Información del sistema")
        card.pack(fill="x")

        info = make_textbox(card, height=120)
        info.pack(fill="x", padx=12, pady=(0, 12))
        info.insert(
            "end",
            "Football Analyzer Quant Pro v10.0\n"
            "• Walk-forward OOS validation (sin data-leakage)\n"
            "• Modelo serializado con joblib (no reentrena innecesariamente)\n"
            "• Kelly fraccionado 0.20, cap 1.5%\n"
            "• Filtros: overround, CLV, muestra mínima\n"
            "• Módulos separados: core/, ui/"
        )

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

    def _test_telegram(self):
        try:
            self.app.send_telegram_text(
                "Prueba correcta desde Football Analyzer Quant Pro v10.0"
            )
            messagebox.showinfo("Telegram", "Mensaje de prueba enviado correctamente.")
        except Exception as exc:
            messagebox.showerror("Telegram", f"Error: {exc}")
