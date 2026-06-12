# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/prob_calibrator.py — Corrección de calibración de las probabilidades.

El módulo de calibration.py *mide* si el modelo está bien calibrado (cuando dice
60%, ¿gana el 60%?). Este módulo da el siguiente paso: *corrige* las
probabilidades para que lo estén, usando regresión isotónica sobre el historial
de picks liquidados.

La regresión isotónica aprende un mapeo monótono prob_predicha → prob_real a
partir de los resultados pasados. Si el modelo es sistemáticamente optimista
(dice 0.70 pero gana 0.60), la corrección baja sus probabilidades; esto mejora
directamente el edge, el EV y el sizing de Kelly aguas abajo.

Salvaguardas (es código que afecta a decisiones con dinero):
  · MIN_SAMPLES   — no corrige hasta tener suficientes picks liquidados.
  · blend         — mezcla conservadora con la prob. cruda (no sobre-corrige).
  · fallback      — si no está ajustado o la entrada es inválida → identidad.
"""

from __future__ import annotations

from typing import Optional

MIN_SAMPLES = 50      # picks liquidados mínimos antes de fiarse de la corrección
DEFAULT_BLEND = 0.5   # 0 = sin corrección (identidad) · 1 = corrección plena


class ProbCalibrator:
    """Calibrador isotónico de probabilidades con salvaguardas."""

    def __init__(self) -> None:
        self._iso = None          # sklearn IsotonicRegression ajustado, o None
        self._n: int = 0          # nº de muestras usadas

    @property
    def is_fitted(self) -> bool:
        return self._iso is not None

    @property
    def n_samples(self) -> int:
        return self._n

    def fit(self, probs, outcomes, min_samples: int = MIN_SAMPLES) -> "ProbCalibrator":
        """
        Ajusta el mapeo prob_predicha → prob_real.

        probs    : iterable de probabilidades predichas (0–1)
        outcomes : iterable de resultados (1 = acierto, 0 = fallo)
        """
        pairs = []
        for p, o in zip(probs, outcomes):
            try:
                pf = float(p)
            except (TypeError, ValueError):
                continue
            if 0.0 <= pf <= 1.0 and o in (0, 1, True, False):
                pairs.append((pf, int(o)))

        self._n = len(pairs)
        if len(pairs) < min_samples:
            self._iso = None          # datos insuficientes → identidad
            return self

        try:
            from sklearn.isotonic import IsotonicRegression
            xs = [p for p, _ in pairs]
            ys = [o for _, o in pairs]
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(xs, ys)
            self._iso = iso
        except Exception:
            self._iso = None          # sklearn no disponible / fallo → identidad
        return self

    def transform(self, prob: float, blend: float = DEFAULT_BLEND) -> float:
        """
        Devuelve la probabilidad corregida. Identidad si no está ajustado o la
        entrada es inválida. El resultado se mezcla con la prob. cruda según
        `blend` y se acota a [0.01, 0.99].
        """
        try:
            p = float(prob)
        except (TypeError, ValueError):
            return prob
        if self._iso is None or not (0.0 <= p <= 1.0):
            return p
        try:
            cal = float(self._iso.predict([p])[0])
        except Exception:
            return p
        out = blend * cal + (1.0 - blend) * p
        return min(0.99, max(0.01, out))


# ── Helper ────────────────────────────────────────────────────────────────────

def fit_from_picks(picks: list[dict], min_samples: int = MIN_SAMPLES) -> ProbCalibrator:
    """Construye y ajusta un ProbCalibrator desde picks liquidados (model_prob + status)."""
    probs, outs = [], []
    for p in picks:
        mp = p.get("model_prob")
        st = p.get("status")
        if mp is None or st not in ("WIN", "LOSS"):
            continue
        try:
            probs.append(float(mp))
            outs.append(1 if st == "WIN" else 0)
        except (TypeError, ValueError):
            continue
    return ProbCalibrator().fit(probs, outs, min_samples=min_samples)
