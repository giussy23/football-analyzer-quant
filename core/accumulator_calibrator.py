# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/accumulator_calibrator.py — Calibración de pesos de _deep_score.

Usa sklearn LogisticRegression sobre picks históricos liquidados
(tabla model_picks con status='WON'/'LOST') para aprender los pesos
óptimos de cada señal en la función de puntuación.

Flujo:
  1. DeepScoreCalibrator.fit(db_path) carga picks liquidados, entrena modelo.
  2. .get_weights() devuelve dict compatible con DEEP_SCORE_WEIGHTS.
  3. .save(path) / .load(path) persiste los pesos calibrados en JSON.
  4. Si n_samples < MIN_SAMPLES → devuelve DEEP_SCORE_WEIGHTS (defaults).

Los pesos calibrados se pasan a build_smart_accumulators(weights=...) y
build_safe_accumulators(weights=...) para que _deep_score los use.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from .accumulator import DEEP_SCORE_WEIGHTS

logger = logging.getLogger(__name__)

MIN_SAMPLES    = 50    # mínimo de picks liquidados para calibrar
WEIGHTS_FILE   = Path(__file__).parent.parent / "data" / "deep_score_weights.json"


class DeepScoreCalibrator:
    """
    Calibra los pesos de _deep_score a partir de picks históricos liquidados.

    Uso:
        cal = DeepScoreCalibrator()
        result = cal.fit(db_path)   # → {"ok": True/False, "n": int, "msg": str}
        weights = cal.get_weights()
        cal.save()
    """

    def __init__(self) -> None:
        self._weights: dict = dict(DEEP_SCORE_WEIGHTS)   # copia de los defaults
        self._n_samples: int = 0
        self._calibrated: bool = False

        # Intentar cargar pesos guardados anteriormente
        if WEIGHTS_FILE.exists():
            self._load_from_file(WEIGHTS_FILE)

    # ── API pública ────────────────────────────────────────────────────────────

    def fit(self, db_path: str) -> dict:
        """
        Entrena la calibración con los picks liquidados de la DB.

        Returns: {"ok": bool, "n": int, "msg": str}
        """
        try:
            X, y = self._load_training_data(db_path)
        except Exception as exc:
            return {"ok": False, "n": 0, "msg": f"Error leyendo DB: {exc}"}

        if len(y) < MIN_SAMPLES:
            return {
                "ok": False,
                "n":  len(y),
                "msg": (
                    f"Solo {len(y)} picks liquidados — se necesitan ≥{MIN_SAMPLES}. "
                    "Usando pesos por defecto (literatura de apuestas)."
                ),
            }

        try:
            weights = self._fit_logistic(X, y)
        except Exception as exc:
            return {"ok": False, "n": len(y), "msg": f"Error en regresión: {exc}"}

        self._weights    = weights
        self._n_samples  = len(y)
        self._calibrated = True
        self.save()

        return {
            "ok":  True,
            "n":   len(y),
            "msg": f"Calibrado con {len(y)} picks. Pesos guardados.",
        }

    def get_weights(self) -> dict:
        """Devuelve los pesos actuales (calibrados si fue entrenado, defaults si no)."""
        return dict(self._weights)

    @property
    def n_samples(self) -> int:
        return self._n_samples

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def save(self, path: Path | None = None) -> None:
        """Guarda los pesos actuales en JSON."""
        target = Path(path) if path else WEIGHTS_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "weights":    self._weights,
            "n_samples":  self._n_samples,
            "calibrated": self._calibrated,
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        logger.info("Pesos guardados en %s", target)

    # ── Internos ───────────────────────────────────────────────────────────────

    def _load_from_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text())
            w = data.get("weights", {})
            if w and isinstance(w, dict):
                merged = dict(DEEP_SCORE_WEIGHTS)
                merged.update({k: float(v) for k, v in w.items() if k in merged})
                self._weights    = merged
                self._n_samples  = int(data.get("n_samples", 0))
                self._calibrated = bool(data.get("calibrated", False))
                logger.info("Pesos cargados desde %s (n=%d)", path, self._n_samples)
        except Exception as exc:
            logger.warning("No se pudieron cargar pesos guardados: %s", exc)

    def _load_training_data(self, db_path: str):
        """
        Carga picks liquidados de model_picks.

        Features: [edge, model_prob, log_odds, is_dc, is_goals, has_clv]
        Target:   win (1=WON, 0=LOST)
        """
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("""
                SELECT edge, model_prob, odds, pick, clv, status
                FROM model_picks
                WHERE status IN ('WON', 'LOST')
                  AND edge IS NOT NULL
                  AND model_prob IS NOT NULL
                  AND odds IS NOT NULL
            """).fetchall()
        finally:
            conn.close()

        if not rows:
            return np.empty((0, 6)), np.empty(0)

        X_list, y_list = [], []
        for edge, prob, odds, pick, clv, status in rows:
            try:
                edge  = float(edge)
                prob  = float(prob)
                odds  = max(1.01, float(odds))
                clv_v = float(clv) if clv is not None else 0.0
                pick  = str(pick or "")
                is_dc    = 1.0 if pick in ("1X", "X2", "12") else 0.0
                is_goals = 1.0 if "OVER" in pick or "UNDER" in pick else 0.0
                has_clv  = 1.0 if clv_v > 0 else 0.0
                win      = 1 if status == "WON" else 0

                X_list.append([edge, prob, np.log(odds), is_dc, is_goals, has_clv])
                y_list.append(win)
            except (TypeError, ValueError):
                continue

        return np.array(X_list), np.array(y_list)

    def _fit_logistic(self, X: np.ndarray, y: np.ndarray) -> dict:
        """
        Ajusta LogisticRegression y mapea coeficientes a DEEP_SCORE_WEIGHTS.

        Los coeficientes de la regresión logística nos dicen el peso relativo
        de cada señal para predecir si un pick gana. Los mapeamos a la escala
        de DEEP_SCORE_WEIGHTS usando los defaults como referencia.
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X)

        # C alto = poca regularización (más fiel a los datos)
        lr = LogisticRegression(C=1.0, max_iter=500, random_state=42)
        lr.fit(X_sc, y)

        coef = lr.coef_[0]   # [edge, prob, log_odds, is_dc, is_goals, has_clv]
        std  = scaler.scale_  # desviaciones típicas para interpretar los coef

        # Los coeficientes de la regresión logística son en escala estandarizada.
        # Los convertimos a escala natural: importancia_natural = coef / std
        imp = coef / (std + 1e-9)

        # Normalizar: el mayor de |imp| = 1.0, luego escalar con los defaults
        max_abs = max(abs(imp)) if max(abs(imp)) > 0 else 1.0
        imp_norm = imp / max_abs

        # Edge (imp_norm[0]) escala edge_sqrt_scale
        # Prob (imp_norm[1]) escala prob_scale
        # DC (imp_norm[3])   escala dc_bonus
        # Goals (imp_norm[4]) escala goals_bonus
        # CLV (imp_norm[5])  escala clv_scale
        defaults = DEEP_SCORE_WEIGHTS
        calibrated = dict(defaults)

        def _scale(default_val: float, factor: float, lo: float = 0.3, hi: float = 2.5) -> float:
            """Ajusta el default por el factor empírico, dentro de [lo, hi] × default."""
            ratio = float(np.clip(1.0 + factor, lo, hi))
            return round(default_val * ratio, 1)

        if imp_norm[0] > 0:   # edge positivo → subir su peso
            calibrated["edge_sqrt_scale"] = _scale(defaults["edge_sqrt_scale"],  imp_norm[0] * 0.5)
        if imp_norm[1] > 0:
            calibrated["prob_scale"]      = _scale(defaults["prob_scale"],        imp_norm[1] * 0.5)
        if imp_norm[5] > 0:
            calibrated["clv_scale"]       = _scale(defaults["clv_scale"],         imp_norm[5] * 0.5)
        if imp_norm[3] != 0:
            calibrated["dc_bonus"]        = _scale(defaults["dc_bonus"],           imp_norm[3] * 0.5)
        if imp_norm[4] != 0:
            calibrated["goals_bonus"]     = _scale(defaults["goals_bonus"],        imp_norm[4] * 0.5)

        logger.info(
            "Calibración completada: edge_scale=%.0f prob_scale=%.0f clv_scale=%.0f",
            calibrated["edge_sqrt_scale"],
            calibrated["prob_scale"],
            calibrated["clv_scale"],
        )
        return calibrated


# ── Singleton global (se carga al importar el módulo) ─────────────────────────
_calibrator: Optional[DeepScoreCalibrator] = None


def get_calibrator() -> DeepScoreCalibrator:
    """Devuelve el singleton del calibrador (carga pesos guardados si existen)."""
    global _calibrator
    if _calibrator is None:
        _calibrator = DeepScoreCalibrator()
    return _calibrator


def get_active_weights() -> dict:
    """Atajo: devuelve los pesos activos (calibrados o defaults)."""
    return get_calibrator().get_weights()
