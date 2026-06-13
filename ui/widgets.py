# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ui/widgets.py — Componentes reutilizables de CustomTkinter.
"""

from __future__ import annotations

import customtkinter as ctk

from ..core.config import ACCENT, BORDER, CARD, CARD_2, MUTED, TEXT


def make_card(parent, title: str, subtitle: str | None = None) -> ctk.CTkFrame:
    """Tarjeta de sección con cabecera: barra de acento + título (+ subtítulo).

    Lenguaje de diseño "Aurora Glass": el título lleva una barra de acento a
    la izquierda y la tarjeta usa el panel del tema. El contenido se sigue
    empaquetando con .pack()/.grid() debajo, como antes (firma sin cambios)."""
    frame = ctk.CTkFrame(
        parent,
        fg_color=CARD,
        border_color=BORDER,
        border_width=1,
        corner_radius=16,
    )
    if title:
        hdr = ctk.CTkFrame(frame, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 2 if subtitle else 12))
        ctk.CTkFrame(hdr, fg_color=ACCENT, width=3, height=18,
                     corner_radius=2).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            hdr, text=title, text_color=TEXT,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")
        if subtitle:
            ctk.CTkLabel(
                frame, text=subtitle, text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(anchor="w", padx=29, pady=(0, 10))

    return frame


def hero_card(parent, label: str, value: str = "—", subtitle: str = ""):
    """Tarjeta KPI tipo hero: acento lateral + valor grande, alineada a la
    izquierda. Devuelve (frame, value_label, accent_strip) para actualizar
    valor/color desde la vista."""
    card = ctk.CTkFrame(parent, fg_color=CARD_2, corner_radius=16,
                        border_color=BORDER, border_width=1)
    strip = ctk.CTkFrame(card, fg_color=ACCENT, width=4, corner_radius=2)
    strip.pack(side="left", fill="y", padx=(8, 0), pady=14)
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(side="left", fill="both", expand=True, padx=(14, 12), pady=14)
    ctk.CTkLabel(body, text=label, text_color=MUTED,
                 font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
    val = ctk.CTkLabel(body, text=value, text_color=ACCENT,
                       font=ctk.CTkFont(size=28, weight="bold"), anchor="w")
    val.pack(anchor="w", pady=(6, 2))
    if subtitle:
        ctk.CTkLabel(body, text=subtitle, text_color=MUTED,
                     font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w")
    return card, val, strip


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
