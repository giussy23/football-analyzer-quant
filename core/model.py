# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
model.py — Stacking ensemble con walk-forward validation y serialización joblib.

Arquitectura v15:
  Level-0  base learners (fast, sin calibración — para walk-forward OOS y producción):
    · HistGradientBoostingClassifier  (siempre)
    · XGBClassifier                   (si xgboost instalado)
    · RandomForestClassifier          (siempre)
  Level-1  meta-learner:
    · LogisticRegression entrenada sobre predicciones OOS de los base learners
    · Aprende el peso óptimo de cada modelo por tipo de partido
    · Actúa simultáneamente como calibración de probabilidades
  Fallback:
    · Si el meta-learner no puede construirse (< 30 muestras OOS), se usa
      HistGBM calibrado (comportamiento idéntico a v14).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

from .config import MODEL_FILE, OUTCOME_LABELS, WF_MIN_TRAIN_RATIO, WF_SPLITS

logger = logging.getLogger(__name__)

# ── Disponibilidad de XGBoost ─────────────────────────────────────────────────

def _xgb_available() -> bool:
    """True si xgboost está instalado en el entorno."""
    try:
        import xgboost  # noqa: F401
        return True
    except ImportError:
        return False


# ── XGBoost wrapper: maneja string labels via LabelEncoder ───────────────────

class _XGBClassifierLabelSafe(BaseEstimator, ClassifierMixin):
    """
    Wrapper de XGBClassifier compatible con sklearn Pipeline (hereda BaseEstimator).
    Codifica labels de string → int internamente (necesario en XGBoost >= 2.x).
    El atributo classes_ expone los valores originales ('H', 'D', 'A').
    """

    def __init__(
        self,
        n_estimators: int   = 100,
        max_depth: int      = 6,
        learning_rate: float = 0.1,
        subsample: float    = 1.0,
        colsample_bytree: float = 1.0,
        verbosity: int      = 0,
        random_state: Optional[int] = None,
        n_jobs: int         = 1,
    ) -> None:
        self.n_estimators    = n_estimators
        self.max_depth       = max_depth
        self.learning_rate   = learning_rate
        self.subsample       = subsample
        self.colsample_bytree = colsample_bytree
        self.verbosity       = verbosity
        self.random_state    = random_state
        self.n_jobs          = n_jobs

    def fit(self, X: Any, y: Any) -> "_XGBClassifierLabelSafe":
        from xgboost import XGBClassifier
        self._le  = LabelEncoder()
        y_enc     = self._le.fit_transform(y)
        self._est = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            verbosity=self.verbosity,
            random_state=self.random_state,
            n_jobs=self.n_jobs,
        )
        self._est.fit(X, y_enc)
        self.classes_ = self._le.classes_
        return self

    def predict_proba(self, X: Any) -> np.ndarray:
        return self._est.predict_proba(X)

    def predict(self, X: Any) -> np.ndarray:
        return self._le.inverse_transform(self._est.predict(X))


# ── Builders rápidos (sin calibración) ───────────────────────────────────────
# Usados en el walk-forward OOS Y como base learners de producción.
# Sin CalibratedClassifierCV → más rápidos; el meta-learner actúa como calibración.

_FIXED_CLASSES = ["H", "D", "A"]   # orden fijo para stacking features


def _build_hist_match_fast() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_depth=5,
            l2_regularization=0.1, min_samples_leaf=20,
            random_state=42,
        )),
    ])


def _build_rf_match_fast() -> Pipeline:
    # n_jobs=1: evita multiprocessing de joblib/loky desde un daemon thread en Windows
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", RandomForestClassifier(
            n_estimators=150, max_depth=9,
            min_samples_leaf=5, n_jobs=1, random_state=42,
        )),
    ])


def _build_xgb_match_fast() -> Pipeline:
    """Solo llamar si _xgb_available(). Usa wrapper con LabelEncoder para string labels."""
    # n_jobs=1: XGBoost usa OpenMP internamente; -1 desde daemon thread puede causar freeze
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", _XGBClassifierLabelSafe(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            verbosity=0, random_state=42, n_jobs=1,
        )),
    ])


def _build_hist_over_fast() -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_depth=4,
            l2_regularization=0.1, min_samples_leaf=20,
            random_state=43,
        )),
    ])


def _build_xgb_over_fast() -> Pipeline:
    """Solo llamar si _xgb_available()."""
    from xgboost import XGBClassifier
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", XGBClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.05,
            subsample=0.8, verbosity=0, random_state=43, n_jobs=1,
        )),
    ])


# ── Builders calibrados — fallback y SHAP ────────────────────────────────────

def _build_match_pipeline() -> Pipeline:
    """HistGBM directo — fallback del ensemble y base para SHAP.
    Sin CalibratedClassifierCV: el meta-learner LogisticRegression actúa como
    calibración OOS. Entrenamiento ~10× más rápido que la versión con cv=3."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, max_depth=5,
            l2_regularization=0.1, min_samples_leaf=20,
            random_state=42,
        )),
    ])


def _build_over_pipeline() -> Pipeline:
    """HistGBM directo para Over/Under.
    Reemplaza GradientBoostingClassifier+CalibratedCV(cv=3) que era ~100× más lento."""
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.05, max_depth=4,
            l2_regularization=0.1, min_samples_leaf=20,
            random_state=42,
        )),
    ])


def _build_goals_pipeline() -> Pipeline:
    # n_jobs=1: evita multiprocessing de joblib/loky desde daemon thread en Windows
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("reg",     RandomForestRegressor(
            n_estimators=240, max_depth=9,
            min_samples_leaf=3, n_jobs=1, random_state=42,
        )),
    ])


# ── Helpers de probabilidades ─────────────────────────────────────────────────

def _proba_ordered(model: Any, X: pd.DataFrame) -> list[float]:
    """Devuelve [pH, pD, pA] en orden _FIXED_CLASSES para UNA fila."""
    p   = model.predict_proba(X)[0]
    clf = model.named_steps.get("clf") if hasattr(model, "named_steps") else model
    classes = list(getattr(clf, "classes_", _FIXED_CLASSES))
    c_map = dict(zip(classes, p))
    return [float(c_map.get(c, 1.0 / 3)) for c in _FIXED_CLASSES]


def _proba_ordered_batch(model: Any, X: pd.DataFrame) -> list[list[float]]:
    """Devuelve [[pH, pD, pA], ...] en orden _FIXED_CLASSES para TODAS las filas."""
    proba = model.predict_proba(X)
    clf   = model.named_steps.get("clf") if hasattr(model, "named_steps") else model
    classes = list(getattr(clf, "classes_", _FIXED_CLASSES))

    if classes == _FIXED_CLASSES:
        return proba.tolist()

    # Reordenar columnas a orden fijo
    col_order = [classes.index(c) if c in classes else 0 for c in _FIXED_CLASSES]
    return proba[:, col_order].tolist()


# ── FootballModel ─────────────────────────────────────────────────────────────

class FootballModel:
    """
    Stacking ensemble (HistGBM + XGBoost + RF) con walk-forward temporal.

    Level-0 : HistGBM (siempre) + XGBoost (si instalado) + RF (siempre)
    Level-1 : LogisticRegression meta-learner sobre predicciones OOS
    Fallback : HistGBM calibrado si el ensemble no puede construirse
    """

    def __init__(self) -> None:
        # Modelo calibrado de referencia (fallback + SHAP)
        self.match_model = _build_match_pipeline()
        self.over_model  = _build_over_pipeline()
        self.goal_model  = _build_goals_pipeline()

        # Stacking ensemble (rellenado en fit())
        self._base_match: list[tuple[str, Any]] = []   # [(name, pipeline), ...]
        self._base_over:  list[tuple[str, Any]] = []
        self.match_meta:  Optional[LogisticRegression] = None
        self.over_meta:   Optional[LogisticRegression] = None

        self.feature_cols: list[str] = []
        self.metrics:      dict      = {}
        self._fitted:      bool      = False

    # ── Entrenamiento ──────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame, progress_cb=None) -> None:
        """
        1. Walk-forward OOS: recoge predicciones de base learners rápidos.
        2. Entrena meta-learner (LogisticRegression) sobre predicciones OOS.
        3. Entrena base learners finales + fallback en datos completos.
        4. Calcula métricas OOS honestas (promedio de base learners, sin meta-learner).

        progress_cb: callable(str) opcional para actualizar la UI durante el entrenamiento.
        """
        def _pcb(msg: str) -> None:
            if progress_cb:
                try:
                    progress_cb(msg)
                except Exception:
                    logger.debug("Excepción ignorada", exc_info=True)
        self.feature_cols = [
            c for c in df.columns
            if c.startswith("f_") and pd.api.types.is_numeric_dtype(df[c])
        ]
        train = df.dropna(subset=["result", "over25", "total_goals"]).copy()
        train = train.sort_index()

        X_all = train[self.feature_cols]
        y_res = train["result"]
        y_ov  = train["over25"].astype(int)
        y_gl  = train["total_goals"].astype(float)

        n         = len(train)
        min_train = max(50, int(n * WF_MIN_TRAIN_RATIO))
        step      = max(1, (n - min_train) // WF_SPLITS)
        use_xgb   = _xgb_available()

        logger.info(
            "Walk-forward OOS | n=%d | min_train=%d | step=%d | XGBoost=%s",
            n, min_train, step, use_xgb,
        )

        # ── Acumuladores OOS ───────────────────────────────────────────────────
        oos_res_true: list              = []
        oos_ov_true:  list              = []
        oos_hist_res: list[list[float]] = []
        oos_xgb_res:  list[list[float]] = []
        oos_rf_res:   list[list[float]] = []
        oos_hist_ov:  list[float]       = []
        oos_xgb_ov:   list[float]       = []

        total_splits = max(1, (n - min_train) // step)
        split_num    = 0
        for split_end in range(min_train, n, step):
            split_num += 1
            X_tr  = X_all.iloc[:split_end]
            X_val = X_all.iloc[split_end: split_end + step]
            if X_val.empty:
                continue
            y_res_tr = y_res.iloc[:split_end]
            y_ov_tr  = y_ov.iloc[:split_end]

            _pcb(f"⏱ WF OOS split {split_num}/{total_splits} ({split_end} muestras)…")

            # HistGBM fast
            m_hist = _build_hist_match_fast().fit(X_tr, y_res_tr)
            o_hist = _build_hist_over_fast().fit(X_tr, y_ov_tr)
            oos_hist_res.extend(_proba_ordered_batch(m_hist, X_val))
            oos_hist_ov.extend(o_hist.predict_proba(X_val)[:, 1].tolist())

            # XGBoost fast (opcional)
            if use_xgb:
                try:
                    m_xgb = _build_xgb_match_fast().fit(X_tr, y_res_tr)
                    o_xgb = _build_xgb_over_fast().fit(X_tr, y_ov_tr)
                    oos_xgb_res.extend(_proba_ordered_batch(m_xgb, X_val))
                    oos_xgb_ov.extend(o_xgb.predict_proba(X_val)[:, 1].tolist())
                except Exception as exc:
                    logger.warning("XGBoost OOS split=%d error: %s", split_end, exc)

            # RandomForest fast — en try/except para no bloquear si n_jobs causa problemas
            try:
                m_rf = _build_rf_match_fast().fit(X_tr, y_res_tr)
                oos_rf_res.extend(_proba_ordered_batch(m_rf, X_val))
            except Exception as exc:
                logger.warning("RandomForest OOS split=%d error: %s — omitiendo RF", split_end, exc)

            idx_val = slice(split_end, split_end + step)
            oos_res_true.extend(y_res.iloc[idx_val].tolist())
            oos_ov_true.extend(y_ov.iloc[idx_val].tolist())

        n_oos = len(oos_res_true)

        # Flags de consistencia: solo incluir XGB en stack si OOS fue completo
        _xgb_res_ok = (len(oos_xgb_res) == n_oos) and n_oos > 0
        _xgb_ov_ok  = (len(oos_xgb_ov)  == n_oos) and n_oos > 0
        _rf_ok      = (len(oos_rf_res)   == n_oos) and n_oos > 0

        # ── Entrenar meta-learners sobre predicciones OOS ─────────────────────
        stk_res = np.empty((0, 3))
        stk_ov  = np.empty((0, 1))

        if n_oos >= 30:
            stk_res = np.array(oos_hist_res, dtype=float)      # (n_oos, 3)
            if _xgb_res_ok:
                stk_res = np.hstack([stk_res, np.array(oos_xgb_res, dtype=float)])
            if _rf_ok:
                stk_res = np.hstack([stk_res, np.array(oos_rf_res, dtype=float)])

            try:
                self.match_meta = LogisticRegression(
                    C=1.0, max_iter=1000, random_state=42,
                )
                self.match_meta.fit(stk_res, oos_res_true)
                logger.info(
                    "Meta-learner 1X2 entrenado | n_oos=%d | features=%d",
                    n_oos, stk_res.shape[1],
                )
            except Exception as exc:
                logger.warning("Meta-learner 1X2 fit error: %s", exc)
                self.match_meta = None

            stk_ov = np.array(oos_hist_ov, dtype=float).reshape(-1, 1)
            if _xgb_ov_ok:
                stk_ov = np.hstack([stk_ov, np.array(oos_xgb_ov, dtype=float).reshape(-1, 1)])

            try:
                self.over_meta = LogisticRegression(
                    C=1.0, max_iter=1000, random_state=42,
                )
                self.over_meta.fit(stk_ov, oos_ov_true)
                logger.info(
                    "Meta-learner Over entrenado | n_oos=%d | features=%d",
                    n_oos, stk_ov.shape[1],
                )
            except Exception as exc:
                logger.warning("Meta-learner Over fit error: %s", exc)
                self.over_meta = None

        # ── Métricas OOS honestas (promedio de base learners, no meta-learner) ─
        if n_oos >= 30:
            avg_res = np.array(oos_hist_res, dtype=float)
            n_avg = 1
            if _xgb_res_ok:
                avg_res += np.array(oos_xgb_res, dtype=float)
                n_avg += 1
            if _rf_ok:
                avg_res += np.array(oos_rf_res, dtype=float)
                n_avg += 1
            oos_final_probs = (avg_res / n_avg).tolist()

            avg_ov = np.array(oos_hist_ov, dtype=float)
            n_avg_ov = 1
            if _xgb_ov_ok:
                avg_ov += np.array(oos_xgb_ov, dtype=float)
                n_avg_ov += 1
            oos_avg_ov = (avg_ov / n_avg_ov).tolist()
        else:
            oos_final_probs = []
            oos_avg_ov      = []

        oos_logloss = (
            log_loss(oos_res_true, oos_final_probs, labels=OUTCOME_LABELS)
            if oos_final_probs else float("nan")
        )
        oos_brier = (
            brier_score_loss(oos_ov_true, oos_avg_ov)
            if oos_avg_ov else float("nan")
        )

        # ── Modelos finales en dataset completo ───────────────────────────────
        logger.info("Entrenando modelos finales | n=%d muestras…", n)
        _pcb(f"🏋 Entrenando modelos finales ({n} muestras)…")

        # Fallback (también usado para SHAP) — HistGBM directo, muy rápido
        _pcb("Entrenando HistGBM fallback (1X2)…")
        self.match_model.fit(X_all, y_res)
        _pcb("Entrenando HistGBM fallback (Over/Under)…")
        self.over_model.fit(X_all, y_ov)
        _pcb("Entrenando RandomForest goles…")
        self.goal_model.fit(X_all, y_gl)

        # Base learners del ensemble de producción
        # Importante: solo incluir XGB si estuvo en el meta-learner (consistencia de features)
        _pcb("Entrenando base learners de producción (HistGBM)…")
        self._base_match = []
        self._base_over  = []

        self._base_match.append(("hist", _build_hist_match_fast().fit(X_all, y_res)))
        self._base_over.append(("hist",  _build_hist_over_fast().fit(X_all, y_ov)))

        if use_xgb and _xgb_res_ok:
            _pcb("Entrenando XGBoost (1X2)…")
            try:
                self._base_match.append(("xgb", _build_xgb_match_fast().fit(X_all, y_res)))
                logger.info("XGBoost base learner (1X2) añadido al ensemble de producción")
            except Exception as exc:
                logger.warning("XGBoost producción 1X2 error: %s — eliminando meta-learner", exc)
                self.match_meta = None   # meta-learner entrenado con XGB features → inconsistente

        if use_xgb and _xgb_ov_ok:
            try:
                self._base_over.append(("xgb", _build_xgb_over_fast().fit(X_all, y_ov)))
            except Exception as exc:
                logger.warning("XGBoost producción Over error: %s — eliminando meta-learner", exc)
                self.over_meta = None

        if _rf_ok:
            _pcb("Entrenando RandomForest (1X2)…")
            try:
                self._base_match.append(("rf", _build_rf_match_fast().fit(X_all, y_res)))
            except Exception as _rf_exc:
                logger.warning("RandomForest producción error: %s — omitido", _rf_exc)

        self._fitted = True
        _pcb("✓ Modelo entrenado correctamente")

        # ── model_type ────────────────────────────────────────────────────────
        base_names = [nm for nm, _ in self._base_match]
        if "xgb" in base_names and self.match_meta is not None:
            model_type = "XGB_Stack"
        elif self.match_meta is not None:
            model_type = "HistGB_Stack"
        else:
            model_type = "HistGB"

        self.metrics = {
            "train_samples":     int(n),
            "oos_match_logloss": round(float(oos_logloss), 4),
            "oos_over_brier":    round(float(oos_brier),   4),
            "wf_splits":         WF_SPLITS,
            "model_type":        model_type,
            "base_learners":     base_names,
            "n_stack_features":  int(stk_res.shape[1]) if stk_res.size else 3,
        }
        logger.info(
            "Modelo entrenado | tipo=%s | bases=%s | n=%d | logloss_OOS=%.4f | brier_OOS=%.4f",
            model_type, base_names, n,
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

        # ── 1X2: stacking ensemble ────────────────────────────────────────────
        if self.match_meta is not None and self._base_match:
            stk: list[float] = []
            for _nm, m in self._base_match:
                stk.extend(_proba_ordered(m, X))
            stk_arr  = np.array(stk).reshape(1, -1)
            expected = getattr(self.match_meta, "n_features_in_", stk_arr.shape[1])
            if stk_arr.shape[1] == expected:
                try:
                    p_meta = self.match_meta.predict_proba(stk_arr)[0]
                    c_map  = dict(zip(self.match_meta.classes_, p_meta))
                    ph  = float(c_map.get("H", 0.33))
                    pd_ = float(c_map.get("D", 0.33))
                    pa  = float(c_map.get("A", 0.33))
                except Exception as exc:
                    logger.debug("Meta 1X2 predict error: %s — fallback", exc)
                    ph, pd_, pa = self._fallback_1x2(X)
            else:
                ph, pd_, pa = self._fallback_1x2(X)
        else:
            ph, pd_, pa = self._fallback_1x2(X)

        # ── Over/Under: stacking ensemble ─────────────────────────────────────
        if self.over_meta is not None and self._base_over:
            ov_feats = [float(m.predict_proba(X)[0][1]) for _nm, m in self._base_over]
            ov_arr   = np.array(ov_feats).reshape(1, -1)
            expected = getattr(self.over_meta, "n_features_in_", ov_arr.shape[1])
            if ov_arr.shape[1] == expected:
                try:
                    p_over = float(self.over_meta.predict_proba(ov_arr)[0][1])
                except Exception:
                    p_over = float(self.over_model.predict_proba(X)[0][1])
            else:
                p_over = float(self.over_model.predict_proba(X)[0][1])
        else:
            p_over = float(self.over_model.predict_proba(X)[0][1])

        return (
            ph, pd_, pa,
            float(self.goal_model.predict(X)[0]),
            p_over,
        )

    def _fallback_1x2(self, X: pd.DataFrame) -> tuple[float, float, float]:
        """HistGBM calibrado como fallback para 1X2."""
        p     = self.match_model.predict_proba(X)[0]
        c_map = dict(zip(self.match_model.named_steps["clf"].classes_, p))
        return (
            float(c_map.get("H", 0.33)),
            float(c_map.get("D", 0.33)),
            float(c_map.get("A", 0.33)),
        )

    # ── SHAP ──────────────────────────────────────────────────────────────────

    def compute_shap_top(self, X: pd.DataFrame, n_top: int = 5) -> list:
        """
        Calcula SHAP values para el modelo de referencia (HistGBM calibrado)
        y devuelve los top-N features más influyentes por fila.
        """
        try:
            import shap
            clf_step = self.match_model.named_steps.get("clf")
            imputer  = self.match_model.named_steps.get("imputer")
            if clf_step is None or imputer is None:
                return []

            X_imp = imputer.transform(X)

            base_models = getattr(clf_step, "calibrated_classifiers_", None)
            if base_models:
                base_est = base_models[0].estimator
            else:
                base_est = clf_step

            explainer = shap.TreeExplainer(base_est)
            shap_vals = explainer.shap_values(X_imp)
            if isinstance(shap_vals, list):
                sv = shap_vals[0]
            else:
                sv = shap_vals

            feat_names = (
                list(self.feature_cols) if self.feature_cols
                else [f"f{i}" for i in range(sv.shape[1])]
            )

            result = []
            for row_shap in sv:
                pairs = sorted(
                    zip(feat_names, row_shap),
                    key=lambda t: abs(t[1]),
                    reverse=True,
                )
                result.append(list(pairs[:n_top]))
            return result
        except Exception as exc:
            logger.debug("SHAP error: %s", exc)
            return []

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
        _VALID_TYPES = {"HistGB", "HistGB_Stack", "XGB_Stack"}
        try:
            model = cls.load(path)
            mt = model.metrics.get("model_type")
            if mt not in _VALID_TYPES:
                logger.info(
                    "Modelo tipo=%r no soportado — forzando reentrenamiento.", mt
                )
                return None
            return model
        except FileNotFoundError:
            return None


# ── FootballModelCollection ────────────────────────────────────────────────────

class FootballModelCollection:
    """
    Colección de FootballModel: uno por liga + modelo global de respaldo.
    """

    def __init__(self) -> None:
        self.models:       dict[str, FootballModel] = {}
        self.global_model: Optional[FootballModel]  = None
        self.trained_divs: list[str]                = []

    def fit_all(
        self,
        data_by_div: dict[str, pd.DataFrame],
        feature_cols: list[str],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        from .config import MIN_ROWS_PER_LEAGUE

        _ALIAS_MAP = {
            "target_1x2":    "result",
            "target_over25": "over25",
            "target_goals":  "total_goals",
        }

        def _prepare(df: pd.DataFrame) -> pd.DataFrame:
            rename = {k: v for k, v in _ALIAS_MAP.items() if k in df.columns and v not in df.columns}
            return df.rename(columns=rename) if rename else df

        all_frames = []
        for div, df in data_by_div.items():
            all_frames.append(df)
            n = len(df)
            if n >= MIN_ROWS_PER_LEAGUE:
                if progress_cb:
                    progress_cb(f"Entrenando modelo {div} ({n} partidos)…")
                m = FootballModel()
                try:
                    m.fit(_prepare(df))
                    self.models[div] = m
                    self.trained_divs.append(div)
                    logger.info("Modelo %s entrenado (%d rows)", div, n)
                except Exception as exc:
                    logger.warning("Error entrenando modelo %s: %s", div, exc)
            else:
                logger.info("Liga %s: %d rows < %d, usando modelo global",
                            div, n, MIN_ROWS_PER_LEAGUE)

        if all_frames:
            if progress_cb:
                progress_cb("Entrenando modelo global (todas las ligas)…")
            combined = pd.concat(all_frames, ignore_index=True)
            self.global_model = FootballModel()
            try:
                self.global_model.fit(_prepare(combined))
                logger.info("Modelo global entrenado (%d rows)", len(combined))
            except Exception as exc:
                logger.error("Error entrenando modelo global: %s", exc)
                self.global_model = None

    def predict_div(self, X: pd.DataFrame, div: str) -> dict:
        model = self.models.get(div) or self.global_model
        if model is None:
            return {}
        try:
            return model.predict(X)
        except Exception as exc:
            logger.warning("predict_div %s error: %s", div, exc)
            return {}

    def save_all(self, model_dir: Path) -> None:
        from .config import MODEL_FILE_TEMPLATE
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        for div, m in self.models.items():
            path = model_dir / MODEL_FILE_TEMPLATE.format(div=div)
            joblib.dump(m, path)
            logger.info("Guardado modelo %s → %s", div, path)
        if self.global_model:
            path = model_dir / "football_model_global_v15.joblib"
            joblib.dump(self.global_model, path)

    def load_all(self, model_dir: Path, divs: list[str]) -> bool:
        from .config import MODEL_FILE_TEMPLATE
        model_dir = Path(model_dir)
        loaded_any = False

        for div in divs:
            path = model_dir / MODEL_FILE_TEMPLATE.format(div=div)
            if path.exists():
                try:
                    self.models[div] = joblib.load(path)
                    self.trained_divs.append(div)
                    loaded_any = True
                    logger.info("Cargado modelo %s", div)
                except Exception as exc:
                    logger.warning("Error cargando modelo %s: %s", div, exc)

        global_path = model_dir / "football_model_global_v15.joblib"
        if global_path.exists():
            try:
                self.global_model = joblib.load(global_path)
                loaded_any = True
            except Exception:
                logger.debug("Excepción ignorada", exc_info=True)

        return loaded_any

    @property
    def metrics_by_div(self) -> dict[str, dict]:
        result = {}
        for div, m in self.models.items():
            result[div] = getattr(m, "metrics", {})
        return result
