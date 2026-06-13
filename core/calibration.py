# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/calibration.py — Calibración del modelo (reliability diagram + Brier).

Un modelo está bien calibrado si, cuando dice "60% de probabilidad", gana
realmente el ~60% de las veces. Esta es una propiedad distinta del acierto:
puedes acertar mucho y estar mal calibrado (exceso de confianza), o al revés.

  · compute_calibration  → agrupa las probabilidades predichas en intervalos y
    compara la probabilidad media predicha con la frecuencia real de acierto.
  · Brier score          → error cuadrático medio entre prob. predicha y
    resultado (0 = perfecto, 0.25 = una moneda, peor cuanto más alto).

Funciones puras → testeables sin tkinter ni base de datos.
"""

from __future__ import annotations

from typing import Optional


def compute_calibration(picks: list[dict], n_bins: int = 10) -> dict:
    """
    Calcula la curva de fiabilidad y el Brier score de una lista de picks.

    Cada pick debe tener:
      · model_prob : probabilidad predicha de que el pick gane (0–1)
      · status     : "WIN" | "LOSS"

    Returns
    -------
    {
      "bins":  [ {pred, obs, count, lo, hi}, ... ],  # solo intervalos con datos
      "brier": float | None,                         # None si no hay datos
      "n":     int,                                  # picks usados
    }
    """
    pairs: list[tuple[float, int]] = []
    for p in picks:
        mp = p.get("model_prob")
        st = p.get("status")
        if mp is None or st not in ("WIN", "LOSS"):
            continue
        try:
            prob = float(mp)
        except (TypeError, ValueError):
            continue
        if not (0.0 <= prob <= 1.0):
            continue
        pairs.append((prob, 1 if st == "WIN" else 0))

    if not pairs:
        return {"bins": [], "brier": None, "n": 0}

    brier = sum((prob - out) ** 2 for prob, out in pairs) / len(pairs)

    bins: list[dict] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        last = (i == n_bins - 1)
        members = [
            (prob, out) for prob, out in pairs
            if (lo <= prob < hi) or (last and prob == hi)   # borde derecho en el último
        ]
        if not members:
            continue
        mean_pred = sum(prob for prob, _ in members) / len(members)
        obs_rate  = sum(out for _, out in members) / len(members)
        bins.append({
            "pred":  mean_pred,
            "obs":   obs_rate,
            "count": len(members),
            "lo":    lo,
            "hi":    hi,
        })

    return {"bins": bins, "brier": brier, "n": len(pairs)}


def calibration_grade(brier: Optional[float]) -> str:
    """Etiqueta cualitativa del Brier score para la UI."""
    if brier is None:
        return "—"
    if brier <= 0.18:
        return "Excelente"
    if brier <= 0.22:
        return "Buena"
    if brier <= 0.25:
        return "Aceptable"
    return "Pobre"
