# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/toast.py — Notificaciones toast de escritorio sin dependencias externas.

Muestra una ventana pequeña en la esquina inferior-derecha de la pantalla
que se cierra automáticamente tras N segundos.

Uso (siempre en el hilo principal de tkinter):
    from .toast import show_toast
    show_toast(app, "✅ Pick WIN", "Man City vs Arsenal  1-0", kind="success")
"""

from __future__ import annotations

import tkinter as tk
from typing import Literal

import customtkinter as ctk

# Paleta
import logging

logger = logging.getLogger(__name__)


_BG     = "#0a1e0c"
_BORDER = "#2dd45b"
_TEXT   = "#f0fff4"
_MUTED  = "#98d4aa"

_KIND_COLORS: dict[str, tuple[str, str]] = {
    "success": ("#166534", "#22c55e"),   # (bg_icon, color_icon)
    "loss":    ("#7f1d1d", "#ef4444"),
    "info":    ("#1e3a5f", "#60a5fa"),
    "warning": ("#78350f", "#fbbf24"),
}

_ACTIVE_TOASTS: list["_Toast"] = []
_TOAST_H      = 72    # alto de cada toast en px
_TOAST_W      = 320
_MARGIN_RIGHT = 20
_MARGIN_BOT   = 48


class _Toast:
    """Una notificación individual."""

    def __init__(
        self,
        root: tk.Misc,
        title: str,
        message: str,
        kind: str,
        duration_ms: int,
    ) -> None:
        self._root    = root
        self._kind    = kind
        self._alive   = True

        accent_bg, accent_fg = _KIND_COLORS.get(kind, _KIND_COLORS["info"])

        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#1a2e1c")

        # Borde de color
        border = tk.Frame(win, bg=accent_fg, width=4)
        border.pack(side="left", fill="y")

        body = tk.Frame(win, bg=_BG)
        body.pack(side="left", fill="both", expand=True)

        # Título
        tk.Label(
            body,
            text=title,
            bg=_BG, fg=accent_fg,
            font=("Segoe UI Semibold", 11),
            anchor="w",
        ).pack(anchor="w", padx=(10, 8), pady=(8, 0))

        # Mensaje
        if message:
            tk.Label(
                body,
                text=message,
                bg=_BG, fg=_MUTED,
                font=("Segoe UI", 9),
                anchor="w",
                wraplength=_TOAST_W - 40,
                justify="left",
            ).pack(anchor="w", padx=(10, 8), pady=(0, 8))

        # Botón cerrar
        tk.Label(
            win, text="✕",
            bg=_BG, fg=_MUTED,
            font=("Segoe UI", 9),
            cursor="hand2",
        ).place(relx=1.0, rely=0.0, x=-6, y=4, anchor="ne")
        win.bind("<Button-1>", lambda _e: self._close())

        self._win = win
        self._reposition()

        # Auto-cerrar
        self._after_id = root.after(duration_ms, self._close)

        _ACTIVE_TOASTS.append(self)

    # ── posición ──────────────────────────────────────────────────────────────

    def _reposition(self) -> None:
        """Coloca el toast en la esquina inferior-derecha sobre los otros activos."""
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()

        idx   = _ACTIVE_TOASTS.index(self) if self in _ACTIVE_TOASTS else 0
        x     = sw - _TOAST_W - _MARGIN_RIGHT
        y     = sh - _MARGIN_BOT - (_TOAST_H + 8) * (idx + 1)

        self._win.geometry(f"{_TOAST_W}x{_TOAST_H}+{x}+{y}")

    def _close(self) -> None:
        if not self._alive:
            return
        self._alive = False
        try:
            self._root.after_cancel(self._after_id)
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)
        try:
            self._win.destroy()
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)
        if self in _ACTIVE_TOASTS:
            _ACTIVE_TOASTS.remove(self)
        # Reposicionar los restantes
        for i, t in enumerate(_ACTIVE_TOASTS):
            t._reposition()


# ── API pública ───────────────────────────────────────────────────────────────

def show_toast(
    root: tk.Misc,
    title: str,
    message: str = "",
    kind: Literal["success", "loss", "info", "warning"] = "info",
    duration_ms: int = 5000,
) -> None:
    """
    Muestra una notificación toast en la esquina inferior-derecha.

    Parámetros
    ----------
    root        : ventana raíz (app) — debe estar en el hilo principal
    title       : texto principal (negrita, coloreado)
    message     : texto secundario (opcional)
    kind        : "success" | "loss" | "info" | "warning"
    duration_ms : milisegundos antes de cerrarse (default 5 s)
    """
    _Toast(root, title, message, kind, duration_ms)
