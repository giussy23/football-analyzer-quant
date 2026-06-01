"""
ui/widgets.py — Componentes reutilizables de CustomTkinter.
"""

from __future__ import annotations

import customtkinter as ctk

from ..core.config import ACCENT, BORDER, CARD, MUTED, TEXT


def make_card(parent, title: str, subtitle: str | None = None) -> ctk.CTkFrame:
    """Tarjeta con título y subtítulo opcionales."""
    frame = ctk.CTkFrame(
        parent,
        fg_color=CARD,
        border_color=BORDER,
        border_width=1,
        corner_radius=16,
    )
    ctk.CTkLabel(
        frame, text=title, text_color=TEXT,
        font=ctk.CTkFont(size=16, weight="bold"),
    ).pack(anchor="w", padx=14, pady=(12, 2))

    if subtitle:
        ctk.CTkLabel(
            frame, text=subtitle, text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=14, pady=(0, 10))

    return frame


def make_textbox(
    parent,
    height: int = 130,
    **kwargs,
) -> ctk.CTkTextbox:
    defaults = dict(
        fg_color="#0b1627",
        text_color=TEXT,
        border_color=BORDER,
        border_width=1,
        corner_radius=12,
    )
    defaults.update(kwargs)
    return ctk.CTkTextbox(parent, height=height, **defaults)


def textbox_set(widget: ctk.CTkTextbox, text: str) -> None:
    """Reemplaza el contenido de un CTkTextbox."""
    widget.delete("1.0", "end")
    widget.insert("end", text)


def make_metric_box(parent, title: str) -> ctk.CTkLabel:
    """Caja de métrica con título + valor grande. Devuelve el label del valor."""
    box = ctk.CTkFrame(parent, fg_color="#0f1b31", corner_radius=12)
    box.pack_propagate(False)
    ctk.CTkLabel(
        box, text=title, text_color=MUTED,
        font=ctk.CTkFont(size=11),
    ).pack(anchor="w", padx=12, pady=(10, 2))
    val = ctk.CTkLabel(
        box, text="0", text_color=TEXT,
        font=ctk.CTkFont(size=22, weight="bold"),
    )
    val.pack(anchor="w", padx=12, pady=(0, 10))
    return val
