# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/views/chat.py — Panel de chat interactivo con Claude IA.

Claude recibe contexto completo de la app (picks VERDE, historial CLV,
bankroll) y responde como analista cuantitativo personal.
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...core.config import ACCENT, ACCENT_2, BORDER, CARD, CARD_2, MUTED, TEXT

if TYPE_CHECKING:
    from ...app import PremiumApp


class ChatView(ctk.CTkFrame):
    """Panel de chat interactivo con Claude IA como analista cuantitativo."""

    def __init__(self, parent, app: "PremiumApp", **kwargs) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._chat = None          # FootballChat instance (lazy init)
        self._busy = False         # True mientras Claude responde
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_chat_area()
        self._build_input_area()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(header, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w", padx=14, pady=10)

        ctk.CTkLabel(
            left, text="🧠 Chat IA · Analista cuantitativo",
            text_color=ACCENT, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        self._model_lbl = ctk.CTkLabel(
            left, text="", text_color=MUTED,
            font=ctk.CTkFont(size=10),
        )
        self._model_lbl.pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=14, pady=10)

        self._context_lbl = ctk.CTkLabel(
            right, text="Sin contexto cargado",
            text_color=MUTED, font=ctk.CTkFont(size=10),
        )
        self._context_lbl.pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            right, text="🔄 Actualizar contexto",
            command=self.refresh_context,
            fg_color=CARD_2, hover_color="#0d1f10",
            border_color=BORDER, border_width=1,
            text_color=TEXT, height=28, corner_radius=8,
            font=ctk.CTkFont(size=11),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            right, text="🗑 Limpiar chat",
            command=self._clear_chat,
            fg_color=CARD_2, hover_color="#0d1f10",
            border_color=BORDER, border_width=1,
            text_color=MUTED, height=28, corner_radius=8,
            font=ctk.CTkFont(size=11),
        ).pack(side="left")

    def _build_chat_area(self) -> None:
        shell = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        shell.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        shell.grid_rowconfigure(0, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        # Área de mensajes — tk.Text con tags de color
        self._chat_box = tk.Text(
            shell,
            bg=CARD, fg=TEXT,
            font=("Segoe UI", 12),
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
            padx=18, pady=14,
            spacing1=2,   # espacio antes de cada párrafo
            spacing3=8,   # espacio después de cada párrafo
        )
        self._chat_box.grid(row=0, column=0, sticky="nsew")

        vsb = ctk.CTkScrollbar(shell, command=self._chat_box.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self._chat_box.configure(yscrollcommand=vsb.set)

        # Tags de texto
        self._chat_box.tag_config(
            "user_name", foreground=ACCENT,
            font=("Segoe UI Semibold", 10),
        )
        self._chat_box.tag_config(
            "user_msg", foreground="#d4f0dc",
            font=("Segoe UI", 12),
            lmargin1=22, lmargin2=22,
            spacing3=4,
        )
        self._chat_box.tag_config(
            "claude_name", foreground="#a78bfa",
            font=("Segoe UI Semibold", 10),
        )
        self._chat_box.tag_config(
            "claude_msg", foreground="#e8d5ff",
            font=("Segoe UI", 12),
            lmargin1=22, lmargin2=22,
            spacing3=4,
        )
        self._chat_box.tag_config(
            "system_msg", foreground=MUTED,
            font=("Segoe UI", 10, "italic"),
            lmargin1=22, lmargin2=22,
        )
        self._chat_box.tag_config(
            "separator", foreground="#1a3020",
            spacing1=6, spacing3=2,
        )
        self._chat_box.tag_config(
            "thinking", foreground="#fbbf24",
            font=("Segoe UI", 12, "italic"),
            lmargin1=22, lmargin2=22,
        )

        # Mensaje de bienvenida
        self._append_system(
            "Hola 👋 Soy tu analista cuantitativo de fútbol. "
            "Pulsa 'Actualizar contexto' para que tenga acceso a tus picks y bankroll actuales, "
            "y luego hazme cualquier pregunta sobre los partidos, estrategia o gestión de banca."
        )

    def _build_input_area(self) -> None:
        bar = ctk.CTkFrame(
            self, fg_color=CARD, corner_radius=12,
            border_color=BORDER, border_width=1,
        )
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        inner.grid_columnconfigure(0, weight=1)

        self._entry = ctk.CTkEntry(
            inner,
            placeholder_text="Escribe tu pregunta... (Enter para enviar)",
            fg_color=CARD_2, border_color=BORDER, text_color=TEXT,
            height=38, corner_radius=10,
            font=ctk.CTkFont(size=12),
        )
        self._entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._entry.bind("<Return>", lambda e: self._send_message())

        self._send_btn = ctk.CTkButton(
            inner, text="Enviar ➤",
            command=self._send_message,
            fg_color=ACCENT, hover_color=ACCENT_2,
            height=38, width=110, corner_radius=10,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._send_btn.grid(row=0, column=1)

    # ── Context ───────────────────────────────────────────────────────────────

    def refresh_context(self, active_view: str = "") -> None:
        """Recarga el contexto completo de la app y lo inyecta en el chat."""
        api_key = self.app.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            self._append_system(
                "⚠ Configura la API key de Anthropic en ⚙️ Strategy para usar el chat."
            )
            return

        from ...core.ai_chat import FootballChat
        if self._chat is None or self._chat.api_key != api_key:
            self._chat = FootballChat(api_key=api_key)

        # ── Picks actuales (Trading Desk) ──────────────────────────────────────
        picks: list[dict] = []
        if hasattr(self.app, "results") and not self.app.results.empty:
            picks = self.app.results.to_dict("records")

        # ── Bankroll ──────────────────────────────────────────────────────────
        try:
            bankroll = float(self.app.bankroll_eur.get() or "0")
        except (ValueError, AttributeError):
            bankroll = 0.0

        # ── Edge threshold ────────────────────────────────────────────────────
        try:
            edge_thresh = float(self.app.edge1.get() or "0.03")
        except (ValueError, AttributeError):
            edge_thresh = 0.03

        # ── Historial de picks liquidados ─────────────────────────────────────
        recent: list[dict] = []
        try:
            recent = self.app.storage.load_model_picks()
        except Exception:
            pass

        # ── CLV stats ─────────────────────────────────────────────────────────
        clv_stats: dict = {}
        try:
            settled = [p for p in recent if p.get("status") in ("WIN", "LOSS")]
            if settled:
                clv_vals = [float(p["clv"]) for p in settled if p.get("clv") is not None]
                clv_stats["avg_clv"]      = sum(clv_vals) / len(clv_vals) if clv_vals else 0.0
                clv_stats["pct_positive"] = sum(1 for v in clv_vals if v > 0) / len(clv_vals) if clv_vals else 0.0
                clv_stats["win_rate"]     = sum(1 for p in settled if p["status"] == "WIN") / len(settled)
                total_pnl = sum(float(p.get("pnl") or 0) for p in settled)
                total_stk = sum(float(p.get("bankroll_pct") or 0.01) for p in settled)
                clv_stats["roi"] = total_pnl / total_stk if total_stk > 0 else 0.0
        except Exception:
            pass

        # ── Quiniela actual ───────────────────────────────────────────────────
        quiniela_picks: list[dict] = []
        try:
            qv = self.app.quiniela_view
            if hasattr(qv, "_rows") and qv._rows:
                for row in qv._rows:
                    if hasattr(row, "data") and row.data:
                        quiniela_picks.append(dict(row.data))
        except Exception:
            pass

        # ── Combinadas actuales ───────────────────────────────────────────────
        combinadas: list[dict] = []
        try:
            av = self.app.accumulator_view
            if hasattr(av, "_combos") and av._combos:
                combinadas = list(av._combos[:5])
        except Exception:
            pass

        # ── Backtest summary y diagnósticos ───────────────────────────────────
        backtest_summary: dict = {}
        diagnostics: list[str] = []
        try:
            backtest_summary = dict(self.app.backtest_summary or {})
            diagnostics = list(self.app.diagnostics or [])
        except Exception:
            pass

        # ── Inyectar en el chat ───────────────────────────────────────────────
        self._chat.update_context(
            picks=picks,
            bankroll=bankroll,
            recent_results=recent,
            clv_stats=clv_stats,
            edge_threshold=edge_thresh,
            quiniela_picks=quiniela_picks,
            combinadas=combinadas,
            backtest_summary=backtest_summary,
            diagnostics=diagnostics,
            active_view=active_view or "",
        )

        # ── Actualizar UI del contexto ────────────────────────────────────────
        n_verde    = sum(1 for p in picks if p.get("risk_light") == "VERDE")
        n_hist     = len([p for p in recent if p.get("status") in ("WIN", "LOSS")])
        n_quiniela = len(quiniela_picks)
        n_combos   = len(combinadas)

        ctx_parts = [f"{n_verde} picks VERDE"]
        if n_quiniela:
            ctx_parts.append(f"quiniela ({n_quiniela})")
        if n_combos:
            ctx_parts.append(f"{n_combos} combinadas")
        if n_hist:
            ctx_parts.append(f"{n_hist} liquidados")
        if bankroll > 0:
            ctx_parts.append(f"{bankroll:,.0f}€")

        ctx_text = " · ".join(ctx_parts)
        self._context_lbl.configure(text=f"📊 {ctx_text}", text_color=ACCENT)

        # Mensaje de sistema con resumen
        view_labels = {
            "quiniela":    "Quiniela IA",
            "analysis":    "Trading Desk",
            "accumulator": "Combinadas IA",
            "results":     "Resultados",
            "portfolio":   "Portfolio",
            "alerts":      "Alertas",
        }
        view_label = view_labels.get(active_view, "")
        ctx_msg = f"✓ Contexto actualizado — {ctx_text}"
        if view_label:
            ctx_msg += f" · Desde: {view_label}"
        self._append_system(ctx_msg)

    # ── Chat helpers ──────────────────────────────────────────────────────────

    def _append_user(self, text: str) -> None:
        """Mensaje del usuario — scroll al final (mensaje corto)."""
        self._chat_box.configure(state="normal")
        ts = datetime.now().strftime("%H:%M")
        self._chat_box.insert("end", "\n", "separator")
        self._chat_box.insert("end", f"Tú · {ts}\n", "user_name")
        self._chat_box.insert("end", text + "\n", "user_msg")
        self._chat_box.configure(state="disabled")
        self._chat_box.see("end")

    def _append_claude(self, text: str) -> None:
        """
        Respuesta de Claude — scroll al INICIO del mensaje, no al final.

        Claude puede responder 30-50 líneas. Con see("end") el usuario ve
        sólo el final y tiene que scrollear manualmente. Aquí marcamos el
        inicio de la respuesta y hacemos scroll hasta ahí.
        """
        self._chat_box.configure(state="normal")
        ts = datetime.now().strftime("%H:%M")
        self._chat_box.insert("end", "\n", "separator")
        # Marca de inicio — gravedad "left" para que no se desplace al insertar
        self._chat_box.mark_set("_claude_start", "end-1c")
        self._chat_box.mark_gravity("_claude_start", "left")
        self._chat_box.insert("end", f"🧠 Claude · {ts}\n", "claude_name")
        self._chat_box.insert("end", text + "\n", "claude_msg")
        self._chat_box.configure(state="disabled")
        # Scroll al inicio de esta respuesta → el usuario lee desde arriba
        self._chat_box.see("_claude_start")

    def _append_system(self, text: str) -> None:
        self._chat_box.configure(state="normal")
        self._chat_box.insert("end", f"\n{text}\n", "system_msg")
        self._chat_box.configure(state="disabled")
        self._chat_box.see("end")

    def _set_thinking(self, on: bool) -> None:
        """Muestra u oculta el indicador 'Claude está pensando...'"""
        self._chat_box.configure(state="normal")
        if on:
            self._thinking_mark = self._chat_box.index("end-1c")
            self._chat_box.insert("end", "\n🧠 Claude está pensando...\n", "thinking")
        else:
            # Borrar el indicador de pensamiento
            if hasattr(self, "_thinking_mark"):
                try:
                    end = self._chat_box.index("end")
                    self._chat_box.delete(self._thinking_mark, end)
                except Exception:
                    pass
        self._chat_box.configure(state="disabled")
        self._chat_box.see("end")

    def _clear_chat(self) -> None:
        self._chat_box.configure(state="normal")
        self._chat_box.delete("1.0", "end")
        self._chat_box.configure(state="disabled")
        if self._chat:
            self._chat.clear()
        self._append_system("🗑 Chat limpiado. El contexto se mantiene.")

    # ── Send / Worker ─────────────────────────────────────────────────────────

    def _send_message(self) -> None:
        if self._busy:
            return

        text = self._entry.get().strip()
        if not text:
            return

        # Verificar API key
        api_key = self.app.storage.get_setting("anthropic_api_key", "")
        if not api_key:
            self._append_system(
                "⚠ Configura la API key de Anthropic en ⚙️ Strategy."
            )
            return

        # Lazy init
        from ...core.ai_chat import FootballChat
        if self._chat is None:
            self._chat = FootballChat(api_key=api_key)
        elif self._chat.api_key != api_key:
            self._chat = FootballChat(api_key=api_key)

        self._entry.delete(0, "end")
        self._append_user(text)

        self._busy = True
        self._send_btn.configure(state="disabled", text="...")
        self._set_thinking(True)

        threading.Thread(
            target=self._send_worker,
            args=(text,),
            daemon=True,
        ).start()

    def _send_worker(self, message: str) -> None:
        response = self._chat.send(message)
        model = self._chat.model
        self.app.after(0, lambda r=response, m=model: self._on_response(r, m))

    def _on_response(self, response: str, model: str) -> None:
        self._set_thinking(False)
        self._append_claude(response)
        self._busy = False
        self._send_btn.configure(state="normal", text="Enviar ➤")
        # Actualizar contador Claude en sidebar
        self.app._update_claude_counter()
        # Mostrar modelo: extraer familia (haiku / sonnet / opus)
        m = model.lower()
        if "haiku"  in m: short_model = "haiku"
        elif "sonnet" in m: short_model = "sonnet"
        elif "opus"   in m: short_model = "opus"
        else: short_model = model.split("-")[-1] if "-" in model else model
        self._model_lbl.configure(
            text=f"· {short_model} · {self._chat.turn_count} turnos"
        )

    def open_with_context(self, source_view: str, prefill: str = "") -> None:
        """
        Abre el chat desde otro panel con contexto específico y pregunta pre-cargada.
        Llamado desde show_chat_view(source_view=..., prefill=...) en app.py.
        """
        self.refresh_context(active_view=source_view)
        if prefill:
            self._entry.delete(0, "end")
            self._entry.insert(0, prefill)
            self._entry.focus()
