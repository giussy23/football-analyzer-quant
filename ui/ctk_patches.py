# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
ctk_patches.py — Parches de rendimiento para CustomTkinter.

Diagnóstico (ui_stalls.log, 13/06/2026): al restaurar la ventana tras un rato
en segundo plano, la UI se quedaba "No responde" 4-5 s. El stack mostró una
cascada reentrante en CTkScrollbar:

    scrollbar.set() → _draw() → canvas.update_idletasks()
        → procesa los idle events de TODA la app
        → _update_dimensions_event de otros widgets → más _draw()
        → más update_idletasks() → ...

Con las muchas vistas con scroll de la app, esa bola de nieve tarda segundos.
El mismo camino se dispara desde el chequeo de DPI de CustomTkinter.

Dos parches quirúrgicos sobre CTkScrollbar:
1. set(): no redibujar si (start, end) no cambió de forma visible — durante
   las cascadas se llama repetidamente con los mismos valores.
2. _draw(): ejecutar el dibujado original suprimiendo SOLO el
   update_idletasks reentrante del canvas (Tk repinta igualmente en el
   siguiente ciclo idle; no hay diferencia visual).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_performance_patches() -> None:
    """Aplica los parches (idempotente — segura de llamar varias veces)."""
    from customtkinter import CTkScrollbar

    if getattr(CTkScrollbar, "_alphabet_patched", False):
        return

    _orig_set  = CTkScrollbar.set
    _orig_draw = CTkScrollbar._draw

    def _set(self, start_value: float, end_value: float):
        s, e = float(start_value), float(end_value)
        prev = getattr(self, "_alphabet_prev_set", None)
        if prev is not None and abs(prev[0] - s) < 1e-4 and abs(prev[1] - e) < 1e-4:
            # Sin cambio visible → actualizar estado y NO redibujar
            self._start_value = s
            self._end_value   = e
            return
        self._alphabet_prev_set = (s, e)
        _orig_set(self, s, e)

    def _draw(self, no_color_updates: bool = False):
        canvas = getattr(self, "_canvas", None)
        if canvas is None:
            return _orig_draw(self, no_color_updates)
        real_uit = canvas.update_idletasks
        canvas.update_idletasks = lambda: None   # suprime la reentrada
        try:
            return _orig_draw(self, no_color_updates)
        finally:
            canvas.update_idletasks = real_uit

    CTkScrollbar.set   = _set
    CTkScrollbar._draw = _draw
    CTkScrollbar._alphabet_patched = True
    logger.info("Parches de rendimiento CTkScrollbar aplicados")
