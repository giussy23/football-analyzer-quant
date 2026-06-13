# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/themes.py — Sistema de temas de color para la UI.

6 temas incluidos. Cada tema define la paleta completa:
  bg / card / card2       — fondos
  accent / accent2        — colores de énfasis (brillante / oscuro)
  border / muted          — bordes y texto apagado
  nav_active_bg           — fondo del botón de nav activo
  nav_inactive_text       — texto de botones inactivos
  nav_inactive_bg         — fondo de botones inactivos
  nav_hover_bg            — hover de botones inactivos
  run_btn / run_btn_hover — botón Run Analysis
  swatch                  — color del swatch en el selector
"""

from __future__ import annotations

THEMES: dict[str, dict] = {

    "Navy": {
        "label":            "Navy",
        "bg":               "#020810",
        "card":             "#040c18",
        "card2":            "#060f1f",
        "accent":           "#22d3ee",
        "accent2":          "#0891b2",
        "border":           "#0d9488",
        "muted":            "#4d7a94",
        "text":             "#e0f2fe",
        "nav_active_bg":    "#0e3a50",
        "nav_inactive_text":"#7eb8cc",
        "nav_inactive_bg":  "#060f1e",
        "nav_hover_bg":     "#0a1830",
        "run_btn":          "#0e7490",
        "run_btn_hover":    "#0891b2",
        "swatch":           "#0d9488",
        "sidebar_bg":       "#040c18",
        "sidebar_border":   "#0d9488",
    },

    "Púrpura": {
        "label":            "Púrpura",
        "bg":               "#0a0812",
        "card":             "#130d1e",
        "card2":            "#180f25",
        "accent":           "#a78bfa",
        "accent2":          "#7c3aed",
        "border":           "#6d28d9",
        "muted":            "#6b5a8a",
        "text":             "#ede9fe",
        "nav_active_bg":    "#2e1065",
        "nav_inactive_text":"#9b7fd4",
        "nav_inactive_bg":  "#100a1e",
        "nav_hover_bg":     "#1a1030",
        "run_btn":          "#5b21b6",
        "run_btn_hover":    "#7c3aed",
        "swatch":           "#7c3aed",
        "sidebar_bg":       "#0c0a14",
        "sidebar_border":   "#6d28d9",
    },

    "Esmeralda": {
        "label":            "Esmeralda",
        "bg":               "#010f08",
        "card":             "#031a0e",
        "card2":            "#042210",
        "accent":           "#34d399",
        "accent2":          "#059669",
        "border":           "#047857",
        "muted":            "#3a7a5a",
        "text":             "#d1fae5",
        "nav_active_bg":    "#052e16",
        "nav_inactive_text":"#6aaa88",
        "nav_inactive_bg":  "#031408",
        "nav_hover_bg":     "#052010",
        "run_btn":          "#065f46",
        "run_btn_hover":    "#059669",
        "swatch":           "#059669",
        "sidebar_bg":       "#031408",
        "sidebar_border":   "#047857",
    },

    "Carmesí": {
        "label":            "Carmesí",
        "bg":               "#0f0808",
        "card":             "#1a0c0c",
        "card2":            "#200e0e",
        "accent":           "#f87171",
        "accent2":          "#dc2626",
        "border":           "#b91c1c",
        "muted":            "#8a4a4a",
        "text":             "#fee2e2",
        "nav_active_bg":    "#450a0a",
        "nav_inactive_text":"#c47a7a",
        "nav_inactive_bg":  "#180808",
        "nav_hover_bg":     "#220c0c",
        "run_btn":          "#991b1b",
        "run_btn_hover":    "#b91c1c",
        "swatch":           "#dc2626",
        "sidebar_bg":       "#130808",
        "sidebar_border":   "#b91c1c",
    },

    "Dorado": {
        "label":            "Dorado",
        "bg":               "#0d0b02",
        "card":             "#1a1404",
        "card2":            "#211904",
        "accent":           "#fbbf24",
        "accent2":          "#d97706",
        "border":           "#b45309",
        "muted":            "#8a6a2a",
        "text":             "#fef3c7",
        "nav_active_bg":    "#451a03",
        "nav_inactive_text":"#c49a4a",
        "nav_inactive_bg":  "#110f03",
        "nav_hover_bg":     "#1c1604",
        "run_btn":          "#92400e",
        "run_btn_hover":    "#b45309",
        "swatch":           "#d97706",
        "sidebar_bg":       "#110f03",
        "sidebar_border":   "#b45309",
    },

    # Tema especial fútbol: césped de estadio nocturno + balones flotando en
    # el fondo (decor="balls" — lo dibuja app._update_bg_decor).
    # OJO: los hexes son deliberadamente distintos de los verdes semánticos
    # de los picks (#22c55e, #16a34a, #4ade80) para que el remapeo de tema
    # no los toque al cambiar a otro tema.
    "⚽ Estadio": {
        "label":            "⚽ Estadio",
        "bg":               "#03150b",
        "card":             "#062313",
        "card2":            "#082b18",
        "accent":           "#3fe07c",
        "accent2":          "#1eb259",
        "border":           "#188c49",
        "muted":            "#67a87f",
        "text":             "#f0fdf4",
        "nav_active_bg":    "#0b3d20",
        "nav_inactive_text":"#7fbf95",
        "nav_inactive_bg":  "#05200f",
        "nav_hover_bg":     "#0a3019",
        "run_btn":          "#157a40",
        "run_btn_hover":    "#1eb259",
        "swatch":           "#1eb259",
        "sidebar_bg":       "#05200f",
        "sidebar_border":   "#188c49",
        "decor":            "balls",
    },

    # Tema premium: aurora boreal sobre cielo de medianoche. Doble acento
    # aqua + violeta eléctrico; el fondo de los márgenes lleva un resplandor
    # de aurora generado por imagen (decor="aurora") + polvo estelar a la
    # deriva. Paleta cohesiva pensada para impacto visual de alta gama.
    "🌌 Aurora": {
        "label":            "🌌 Aurora",
        "bg":               "#070514",
        "card":             "#0e0a22",
        "card2":            "#141029",
        "accent":           "#4de3c8",   # aqua-aurora luminoso
        "accent2":          "#7c5cff",   # violeta-índigo eléctrico
        "border":           "#3b3a7a",
        "muted":            "#8a86c0",
        "text":             "#eef0ff",
        "nav_active_bg":    "#1c1745",
        "nav_inactive_text":"#9d9bc8",
        "nav_inactive_bg":  "#0c0820",
        "nav_hover_bg":     "#15102e",
        "run_btn":          "#5b46c9",
        "run_btn_hover":    "#7c5cff",
        "swatch":           "#7c5cff",
        "sidebar_bg":       "#0a0720",
        "sidebar_border":   "#7c5cff",
        "decor":            "aurora",
        "banner_intensity": 1.85,   # cortinas con gama propia (suave) → más brillo
    },

    # Tema premium "glassmorphism": paneles claros translúcidos sobre índigo
    # profundo + bordes violeta luminosos → efecto cristal (sin blur real, que
    # tkinter no soporta; se logra con la paleta). card/card2 deliberadamente
    # MÁS CLAROS que el fondo, border luminoso para que los paneles "floten".
    "🪟 Aurora Glass": {
        "label":            "🪟 Aurora Glass",
        "bg":               "#0b0a18",
        "card":             "#1b1930",   # panel cristal (claro sobre el índigo)
        "card2":            "#232139",
        "accent":           "#b9a5ff",   # violeta brillante
        "accent2":          "#5ee6cf",   # cyan
        "border":           "#4f4685",   # borde luminoso del cristal
        "muted":            "#928cbe",
        "text":             "#f2f0ff",
        "nav_active_bg":    "#272252",
        "nav_inactive_text":"#a8a3d0",
        "nav_inactive_bg":  "#131127",
        "nav_hover_bg":     "#1d1a38",
        "run_btn":          "#6b54d8",
        "run_btn_hover":    "#8a6dff",
        "swatch":           "#8a6dff",
        "sidebar_bg":       "#141127",
        "sidebar_border":   "#6b5cc9",
        "decor":            "aurora",
        "banner_intensity": 1.7,
    },

    "Océano": {
        "label":            "Océano",
        "bg":               "#020a14",
        "card":             "#041020",
        "card2":            "#051428",
        "accent":           "#60a5fa",
        "accent2":          "#2563eb",
        "border":           "#1d4ed8",
        "muted":            "#3a5a8a",
        "text":             "#dbeafe",
        "nav_active_bg":    "#1e3a5f",
        "nav_inactive_text":"#5a88b0",
        "nav_inactive_bg":  "#030c18",
        "nav_hover_bg":     "#081828",
        "run_btn":          "#1d4ed8",
        "run_btn_hover":    "#2563eb",
        "swatch":           "#2563eb",
        "sidebar_bg":       "#030c18",
        "sidebar_border":   "#1d4ed8",
    },
}

DEFAULT_THEME = "Navy"

# Estado global del tema activo (mutable, modificado por apply_theme)
_active_theme_name: str = DEFAULT_THEME


def get_theme(name: str) -> dict:
    """Devuelve el dict del tema por nombre (fallback: Navy)."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def get_current_theme() -> dict:
    """Devuelve el tema actualmente activo."""
    return THEMES.get(_active_theme_name, THEMES[DEFAULT_THEME])


def set_active_theme(name: str) -> None:
    """Actualiza el tema activo en memoria."""
    global _active_theme_name
    _active_theme_name = name if name in THEMES else DEFAULT_THEME


def theme_names() -> list[str]:
    return list(THEMES.keys())
