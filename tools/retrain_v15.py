# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
"""
retrain_v15.py — Re-entrena el modelo global + modelos por liga con el
histórico multi-temporada (HIST_SEASONS) y muestra las métricas OOS.

Replica el pipeline de entrenamiento de Analyzer.run() (club ELO, xG
histórico de Understat, build_training_frame, alias de targets para
fit_all) pero sin la parte de análisis/picks.

Uso:
    set PYTHONPATH=D:\\ && venv\\Scripts\\python tools\\retrain_v15.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("retrain")

import pandas as pd

from football_analyzer.core.config import LEAGUE_MAP, MODEL_FILE
from football_analyzer.core.data import fetch_historic_multi, prepare_historic
from football_analyzer.core.analyzer import build_training_frame
from football_analyzer.core.model import FootballModel, FootballModelCollection


def main() -> None:
    # ── 1. Histórico 3 temporadas ─────────────────────────────────────────────
    hist_by_div: dict[str, pd.DataFrame] = {}
    for name, (div, csv_url, _color) in LEAGUE_MAP.items():
        if not csv_url:
            continue
        logger.info("Histórico %s (%s)…", name, div)
        raw = fetch_historic_multi(csv_url)
        hist_by_div[div] = prepare_historic(raw)
        logger.info("  %s: %d partidos", div, len(hist_by_div[div]))

    # ── 2. Club ELO + xG histórico Understat (igual que Analyzer.run) ────────
    club_elo = None
    try:
        from football_analyzer.core.club_elo import ClubEloModel
        club_elo = ClubEloModel()
        club_elo.load()
        logger.info("Club ELO cargado")
    except Exception as exc:
        logger.warning("Club ELO no disponible: %s", exc)

    xg_hist_by_div: dict = {}
    try:
        from football_analyzer.core.understat import fetch_league_xg, current_season
        prev = current_season() - 1
        for div in hist_by_div:
            try:
                xg = fetch_league_xg(div, prev)
                if xg:
                    xg_hist_by_div[div] = xg
            except Exception:
                pass
        logger.info("xG histórico Understat: %d ligas", len(xg_hist_by_div))
    except Exception as exc:
        logger.warning("Understat no disponible: %s", exc)

    # ── 3. Dataset ────────────────────────────────────────────────────────────
    logger.info("Construyendo dataset de entrenamiento…")
    train_all = build_training_frame(hist_by_div, club_elo=club_elo, xg_hist_by_div=xg_hist_by_div)
    if train_all.empty:
        raise SystemExit("Dataset vacío — abortando.")
    logger.info("Dataset: %d filas, %d columnas", *train_all.shape)

    # ── 4. Modelo global ──────────────────────────────────────────────────────
    model = FootballModel()
    model.fit(train_all, progress_cb=lambda m: logger.info("  %s", m))
    model.save(MODEL_FILE)
    logger.info("Modelo global guardado en %s", MODEL_FILE)

    # ── 5. Modelos por liga (alias de targets como en Analyzer.run) ──────────
    feature_cols = [
        c for c in train_all.columns
        if c.startswith("f_") and pd.api.types.is_numeric_dtype(train_all[c])
    ]
    data_by_div_for_fit: dict[str, pd.DataFrame] = {}
    for d, grp in train_all.groupby("div"):
        g = grp.copy()
        g["target_1x2"]    = g["result"]
        g["target_over25"] = g["over25"]
        g["target_goals"]  = g["total_goals"]
        data_by_div_for_fit[d] = g

    col = FootballModelCollection()
    col.fit_all(data_by_div_for_fit, feature_cols, progress_cb=lambda m: logger.info("  %s", m))
    model_dir = os.path.dirname(os.path.abspath(MODEL_FILE)) or "."
    col.save_all(model_dir)
    logger.info("Modelos por liga guardados: %s", list(col.models.keys()))

    # ── 6. Métricas (ASCII: la consola Windows usa cp1252) ────────────────────
    print("\n========== METRICAS (logloss OOS: < 1.0986 = mejor que el azar) ==========")
    mt = model.metrics or {}
    print(f"GLOBAL   logloss={mt.get('oos_match_logloss')}  brier_ou={mt.get('oos_over_brier')}  "
          f"n={mt.get('train_samples')}  learners={mt.get('base_learners')}")
    for d, m in sorted(col.models.items()):
        lm = getattr(m, "metrics", {}) or {}
        print(f"{d:8} logloss={lm.get('oos_match_logloss')}  brier_ou={lm.get('oos_over_brier')}  "
              f"n={lm.get('train_samples')}  learners={lm.get('base_learners')}")


if __name__ == "__main__":
    main()
