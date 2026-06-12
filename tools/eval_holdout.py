# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
"""
eval_holdout.py — Evaluación honesta del modelo con holdout CRONOLÓGICO.

Entrena el stack completo (base learners + meta-learner) con el primer 85%
de los partidos (ordenados por fecha) y evalúa el 15% más reciente, que el
modelo nunca ha visto. Compara contra:

  - azar uniforme (logloss 1.0986)
  - tasas base de la liga (siempre predecir frecuencias H/D/A del train)
  - el MERCADO (probabilidades justas de B365, sin margen)

El veredicto que importa: si logloss(modelo) >= logloss(mercado), el modelo
no aporta señal sobre las cuotas y el "edge" 1X2 es ruido.

Uso:  PYTHONPATH=D:\\ venv\\Scripts\\python -X utf8 tools\\eval_holdout.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("eval")

import numpy as np
import pandas as pd

from football_analyzer.core.config import LEAGUE_MAP
from football_analyzer.core.data import fetch_historic_multi, prepare_historic
from football_analyzer.core.analyzer import build_training_frame
from football_analyzer.core.features import fair_probs
from football_analyzer.core.model import FootballModel

EPS = 1e-12


def _logloss_rows(probs: np.ndarray, y: list[str]) -> float:
    """probs: array (n,3) en orden H,D,A; y: lista de 'H'/'D'/'A'."""
    idx = {"H": 0, "D": 1, "A": 2}
    p = np.clip(probs, EPS, 1.0)
    p = p / p.sum(axis=1, keepdims=True)
    return float(-np.mean([np.log(p[i, idx[t]]) for i, t in enumerate(y)]))


def main() -> None:
    print("1/4 Descargando/cargando historico (3 temporadas, cache)...")
    hist_by_div = {}
    for name, (div, csv_url, _c) in LEAGUE_MAP.items():
        if csv_url:
            hist_by_div[div] = prepare_historic(fetch_historic_multi(csv_url))

    club_elo = None
    try:
        from football_analyzer.core.club_elo import ClubEloModel
        club_elo = ClubEloModel()
        club_elo.load()
    except Exception as exc:
        print("   (Club ELO no disponible:", exc, ")")

    print("2/4 Construyendo dataset de features...")
    df = build_training_frame(hist_by_div, club_elo=club_elo)
    df = df.dropna(subset=["result", "over25", "total_goals", "date"])
    df = df.sort_values("date").reset_index(drop=True)

    cutoff = int(len(df) * 0.85)
    train, test = df.iloc[:cutoff], df.iloc[cutoff:]
    print(f"   train={len(train)}  test={len(test)}  "
          f"(test desde {test['date'].min():%d/%m/%Y} hasta {test['date'].max():%d/%m/%Y})")

    print("3/4 Entrenando stack completo con el 85% inicial...")
    model = FootballModel()
    model.fit(train)

    print("4/4 Prediciendo el 15% mas reciente (modelo nunca vio estos partidos)...")
    # Solo filas con cuotas de mercado validas, para comparar contra B365
    has_mkt = test[["B365H", "B365D", "B365A"]].notna().all(axis=1)
    t = test[has_mkt]

    stack_probs, mkt_probs, y_true = [], [], []
    ou_model, ou_mkt, ou_true = [], [], []
    for _, row in t.iterrows():
        ph, pd_, pa, _eg, p_over = model.predict_row(row)
        stack_probs.append([ph, pd_, pa])
        mkt_probs.append(list(fair_probs(row["B365H"], row["B365D"], row["B365A"])))
        y_true.append(row["result"])
        if pd.notna(row.get("B365O25")) and pd.notna(row.get("B365U25")):
            oi, ui = 1 / row["B365O25"], 1 / row["B365U25"]
            ou_model.append(p_over)
            ou_mkt.append(oi / (oi + ui))
            ou_true.append(int(row["over25"]))

    stack_probs = np.array(stack_probs)
    mkt_probs   = np.array(mkt_probs)

    # Baselines
    base = train["result"].value_counts(normalize=True)
    base_probs = np.tile([base.get("H", .33), base.get("D", .33), base.get("A", .33)], (len(y_true), 1))
    unif_probs = np.full((len(y_true), 3), 1 / 3)

    ll_stack = _logloss_rows(stack_probs, y_true)
    ll_mkt   = _logloss_rows(mkt_probs, y_true)
    ll_base  = _logloss_rows(base_probs, y_true)
    ll_unif  = _logloss_rows(unif_probs, y_true)

    print()
    print("=" * 64)
    print(f"1X2 sobre {len(y_true)} partidos recientes (logloss, menor=mejor)")
    print("=" * 64)
    print(f"  Mercado (B365 sin margen)   : {ll_mkt:.4f}   <- el rival a batir")
    print(f"  MODELO (stack+meta-learner) : {ll_stack:.4f}")
    print(f"  Tasas base del train        : {ll_base:.4f}")
    print(f"  Azar uniforme               : {ll_unif:.4f}")
    verdict = ("APORTA senal (mejor que tasas base)" if ll_stack < ll_base else
               "NO aporta senal (peor que apostar tasas base)")
    vs_mkt = "BATE al mercado" if ll_stack < ll_mkt else "NO bate al mercado"
    print(f"  Veredicto 1X2: {verdict}; {vs_mkt}")

    if ou_true:
        bm = float(np.mean((np.array(ou_model) - np.array(ou_true)) ** 2))
        bk = float(np.mean((np.array(ou_mkt) - np.array(ou_true)) ** 2))
        b5 = float(np.mean((0.5 - np.array(ou_true)) ** 2))
        print()
        print(f"OVER/UNDER 2.5 sobre {len(ou_true)} partidos (Brier, menor=mejor)")
        print(f"  Mercado : {bk:.4f}   MODELO : {bm:.4f}   p=0.5 fijo : {b5:.4f}")
        print(f"  Veredicto O/U: {'BATE al mercado' if bm < bk else 'no bate al mercado'}"
              f"{' pero supera al azar' if bm < b5 <= bk or (bm < b5) else ''}")


if __name__ == "__main__":
    main()
