"""
model.py — Modelo predictivo con walk-forward validation y serialización joblib.

Mejoras respecto a la versión original:
  - Walk-forward temporal (sin data-leakage / look-ahead bias)
  - Serialización con joblib (no reentrena en cada análisis)
  - Métricas out-of-sample reales (log-loss, Brier)
  - Ensemble mejorado: calibración isotónica + GradientBoosting como alternativa
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import MODEL_FILE, OUTCOME_LABELS, WF_MIN_TRAIN_RATIO, WF_SPLITS

logger = logging.getLogger(__name__)


def _build_match_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("clf",     LogisticRegression(max_iter=600, C=0.8, random_state=42)),
    ])


def _build_over_pipeline() -> Pipeline:
    base = GradientBoostingClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, random_state=42,
    )
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf",     CalibratedClassifierCV(base, method="isotonic", cv=3)),
    ])


def _build_goals_pipeline() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("reg",     RandomForestRegressor(
            n_estimators=240, max_depth=9,
            min_samples_leaf=3, random_state=42,
        )),
    ])


class FootballModel:
    """
    Entrena tres modelos (1X2, Over2.5, goles esperados) con walk-forward
    temporal para obtener métricas out-of-sample sin data-leakage.
    """

    def __init__(self) -> None:
        self.match_model = _build_match_pipeline()
        self.over_model  = _build_over_pipeline()
        self.goal_model  = _build_goals_pipeline()
        self.feature_cols: list[str] = []
        self.metrics: dict = {}
        self._fitted = False

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> None:
        """
        Entrena con TODOS los datos disponibles y calcula métricas OOS via
        walk-forward (time-series split).
        """
        self.feature_cols = [
            c for c in df.columns
            if c.startswith("f_") and pd.api.types.is_numeric_dtype(df[c])
        ]
        train = df.dropna(subset=["result", "over25", "total_goals"]).copy()
        train = train.sort_index()  # el índice ya debe ser temporal (se garantiza en analyzer)

        X_all = train[self.feature_cols]
        y_res = train["result"]
        y_ov  = train["over25"].astype(int)
        y_gl  = train["total_goals"].astype(float)

        # ── Walk-forward OOS metrics ───────────────────────────────────────────
        n = len(train)
        min_train = max(50, int(n * WF_MIN_TRAIN_RATIO))
        step      = max(1, (n - min_train) // WF_SPLITS)

        oos_res_true, oos_res_prob = [], []
        oos_ov_true,  oos_ov_prob  = [], []

        for split_end in range(min_train, n, step):
            X_tr = X_all.iloc[:split_end]
            X_val = X_all.iloc[split_end: split_end + step]
            if X_val.empty:
                continue

            m = _build_match_pipeline().fit(X_tr, y_res.iloc[:split_end])
            o = _build_over_pipeline().fit(X_tr, y_ov.iloc[:split_end])

            oos_res_prob.extend(m.predict_proba(X_val).tolist())
            oos_res_true.extend(y_res.iloc[split_end: split_end + step].tolist())
            oos_ov_prob.extend(o.predict_proba(X_val)[:, 1].tolist())
            oos_ov_true.extend(y_ov.iloc[split_end: split_end + step].tolist())

        # Entrenar modelos finales con todos los datos
        self.match_model.fit(X_all, y_res)
        self.over_model.fit(X_all, y_ov)
        self.goal_model.fit(X_all, y_gl)
        self._fitted = True

        # Métricas OOS (robustas)
        oos_logloss = (
            log_loss(oos_res_true, oos_res_prob, labels=OUTCOME_LABELS)
            if oos_res_true else float("nan")
        )
        oos_brier = (
            brier_score_loss(oos_ov_true, oos_ov_prob)
            if oos_ov_true else float("nan")
        )

        self.metrics = {
            "train_samples":    int(len(train)),
            "oos_match_logloss": round(float(oos_logloss), 4),
            "oos_over_brier":    round(float(oos_brier),   4),
            "wf_splits":        WF_SPLITS,
        }
        logger.info(
            "Modelo entrenado | muestras=%d | logloss_OOS=%.4f | brier_OOS=%.4f",
            self.metrics["train_samples"],
            self.metrics["oos_match_logloss"],
            self.metrics["oos_over_brier"],
        )

    # ── Predicción ────────────────────────────────────────────────────────────

    def predict_row(
        self, row: pd.Series
    ) -> tuple[float, float, float, float, float]:
        """Devuelve (p_home, p_draw, p_away, expected_goals, p_over25)."""
        if not self._fitted:
            raise RuntimeError("El modelo no ha sido entrenado. Llama a fit() primero.")

        X = pd.DataFrame([row[self.feature_cols]])
        p = self.match_model.predict_proba(X)[0]
        classes = self.match_model.named_steps["clf"].classes_
        mp = dict(zip(classes, p))

        return (
            float(mp.get("H", 0.0)),
            float(mp.get("D", 0.0)),
            float(mp.get("A", 0.0)),
            float(self.goal_model.predict(X)[0]),
            float(self.over_model.predict_proba(X)[0][1]),
        )

    # ── Serialización ─────────────────────────────────────────────────────────

    def save(self, path: str = MODEL_FILE) -> None:
        joblib.dump(self, path)
        logger.info("Modelo guardado en %s", path)

    @classmethod
    def load(cls, path: str = MODEL_FILE) -> "FootballModel":
        if not os.path.exists(path):
            raise FileNotFoundError(f"No se encontró el modelo en {path}")
        model = joblib.load(path)
        logger.info("Modelo cargado desde %s", path)
        return model

    @classmethod
    def load_or_none(cls, path: str = MODEL_FILE) -> Optional["FootballModel"]:
        try:
            return cls.load(path)
        except FileNotFoundError:
            return None
