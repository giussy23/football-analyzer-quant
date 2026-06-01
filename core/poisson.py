"""
core/poisson.py — Modelo de Poisson Dixon-Coles para predicción de fútbol.

El modelo estima parámetros de ataque/defensa por equipo + ventaja local.
La corrección Dixon-Coles ajusta la probabilidad de los marcadores bajos
(0-0, 1-0, 0-1, 1-1) que el Poisson puro infraestima.

Referencia: Dixon & Coles (1997) "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market"
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

logger = logging.getLogger(__name__)

MAX_GOALS   = 8      # goles máximos a considerar en la matriz
RHO_INIT    = -0.10  # correlación Dixon-Coles inicial (negativa = baja anotación correlada)
HOME_ADV_INIT = 0.25 # ventaja local inicial (en log-escala)


# ── Corrección Dixon-Coles ────────────────────────────────────────────────────

def _tau(gh: int, ga: int, lh: float, la: float, rho: float) -> float:
    """Factor de corrección para marcadores bajos (Dixon-Coles 1997)."""
    if   gh == 0 and ga == 0: return 1.0 - lh * la * rho
    elif gh == 1 and ga == 0: return 1.0 + la * rho
    elif gh == 0 and ga == 1: return 1.0 + lh * rho
    elif gh == 1 and ga == 1: return 1.0 - rho
    return 1.0


# ── Matriz de marcadores ──────────────────────────────────────────────────────

def score_matrix(lh: float, la: float, rho: float = RHO_INIT) -> np.ndarray:
    """
    Matriz MAX_GOALS × MAX_GOALS donde [i,j] = P(home=i, away=j).
    Incluye corrección Dixon-Coles y normalización final.
    """
    mat = np.zeros((MAX_GOALS, MAX_GOALS))
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            mat[i, j] = (
                poisson.pmf(i, lh)
                * poisson.pmf(j, la)
                * _tau(i, j, lh, la, rho)
            )
    total = mat.sum()
    return mat / total if total > 0 else mat


def probs_from_matrix(mat: np.ndarray) -> tuple[float, float, float]:
    """P(victoria local), P(empate), P(victoria visitante)."""
    n = mat.shape[0]
    p_h = float(sum(mat[i, j] for i in range(n) for j in range(i)))
    p_d = float(sum(mat[i, i] for i in range(n)))
    p_a = float(max(0.0, 1.0 - p_h - p_d))
    return round(p_h, 4), round(p_d, 4), round(p_a, 4)


# ── Modelo ────────────────────────────────────────────────────────────────────

class DixonColesModel:
    """
    Modelo de Poisson con corrección Dixon-Coles.

    Ajusta por máxima verosimilitud los parámetros de ataque y defensa
    de cada equipo más la ventaja local global.
    """

    def __init__(self) -> None:
        self.attack_:        dict[str, float] = {}
        self.defense_:       dict[str, float] = {}
        self.home_advantage_: float = HOME_ADV_INIT
        self.rho_:            float = RHO_INIT
        self._fitted:         bool  = False
        self.teams_:          list[str] = []
        self.metrics_:        dict = {}

    # ── Entrenamiento ─────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame, max_matches: int = 400) -> "DixonColesModel":
        """
        Entrena el modelo con datos históricos.

        df debe tener columnas: home_team, away_team, home_goals, away_goals.
        max_matches: limita a los N partidos más recientes para mantener
        el entrenamiento rápido (≤ 10 s) con varias ligas seleccionadas.
        """
        data = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"]).copy()
        data = data[data["home_goals"] >= 0]

        if len(data) < 30:
            logger.warning("Pocos datos para Dixon-Coles (%d partidos), modelo no entrenado.", len(data))
            return self

        # Usar solo los partidos más recientes para mantener velocidad
        if len(data) > max_matches:
            data = data.tail(max_matches).copy()
            logger.info("Dixon-Coles: datos recortados a %d partidos más recientes.", max_matches)

        teams = sorted(set(data["home_team"]) | set(data["away_team"]))
        self.teams_ = teams
        n_teams = len(teams)
        idx = {t: i for i, t in enumerate(teams)}

        logger.info("Entrenando Dixon-Coles: %d partidos, %d equipos", len(data), n_teams)

        # Pre-convertir a arrays para velocidad
        home_arr  = data["home_team"].values
        away_arr  = data["away_team"].values
        gh_arr    = data["home_goals"].astype(int).values
        ga_arr    = data["away_goals"].astype(int).values

        def neg_log_likelihood(params: np.ndarray) -> float:
            att  = params[:n_teams]
            defe = params[n_teams:2 * n_teams]
            ha   = params[2 * n_teams]
            rho  = params[2 * n_teams + 1]

            ll = 0.0
            for k in range(len(data)):
                h_i = idx.get(home_arr[k])
                a_i = idx.get(away_arr[k])
                if h_i is None or a_i is None:
                    continue

                lh = np.exp(att[h_i] + defe[a_i] + ha)
                la = np.exp(att[a_i] + defe[h_i])
                gh = gh_arr[k]
                ga = ga_arr[k]

                tau_v = _tau(gh, ga, lh, la, rho)
                if tau_v <= 0:
                    continue

                ll += (
                    poisson.logpmf(gh, max(lh, 1e-6))
                    + poisson.logpmf(ga, max(la, 1e-6))
                    + np.log(tau_v + 1e-10)
                )
            return -ll

        # Inicialización
        x0    = np.zeros(2 * n_teams + 2)
        x0[2 * n_teams]     = HOME_ADV_INIT
        x0[2 * n_teams + 1] = RHO_INIT

        bounds  = (
            [(-3.0, 3.0)] * n_teams       # attack
            + [(-3.0, 3.0)] * n_teams     # defense
            + [(0.0,  0.8)]               # home advantage
            + [(-0.5, 0.0)]               # rho (siempre negativo o cero)
        )
        constraints = [{"type": "eq", "fun": lambda x: x[:n_teams].sum()}]  # sum(attack) = 0

        try:
            result = minimize(
                neg_log_likelihood, x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 80, "ftol": 1e-5},  # rápido: 80 iter suficientes
            )
            params = result.x
            logger.info("Dixon-Coles convergió. fun=%.4f success=%s", result.fun, result.success)
        except Exception as exc:
            logger.warning("Optimización Dixon-Coles falló: %s. Usando inicialización.", exc)
            params = x0

        self.attack_          = {t: float(params[idx[t]])           for t in teams}
        self.defense_         = {t: float(params[n_teams + idx[t]]) for t in teams}
        self.home_advantage_  = float(params[2 * n_teams])
        self.rho_             = float(np.clip(params[2 * n_teams + 1], -0.5, 0.0))
        self._fitted          = True

        # Métricas básicas
        avg_att = float(np.mean(list(self.attack_.values())))
        avg_def = float(np.mean(list(self.defense_.values())))
        self.metrics_ = {
            "n_teams":      n_teams,
            "n_matches":    len(data),
            "home_advantage": round(self.home_advantage_, 4),
            "rho":           round(self.rho_, 4),
            "avg_attack":    round(avg_att, 4),
            "avg_defense":   round(avg_def, 4),
        }
        logger.info(
            "Dixon-Coles: home_adv=%.3f  rho=%.3f  equipos=%d",
            self.home_advantage_, self.rho_, n_teams,
        )
        return self

    # ── Predicción ────────────────────────────────────────────────────────────

    def predict(
        self, home_team: str, away_team: str
    ) -> Optional[tuple[float, float, float, float, float]]:
        """
        Devuelve (p_home, p_draw, p_away, lambda_home, lambda_away).
        Devuelve None si el modelo no está entrenado.
        Equipos desconocidos usan el parámetro medio de la liga.
        """
        if not self._fitted:
            return None

        # Equipos nuevos → usar media de los conocidos
        avg_att = float(np.mean(list(self.attack_.values())))  if self.attack_  else 0.0
        avg_def = float(np.mean(list(self.defense_.values()))) if self.defense_ else 0.0

        att_h = self.attack_.get(home_team,  avg_att)
        def_h = self.defense_.get(home_team, avg_def)
        att_a = self.attack_.get(away_team,  avg_att)
        def_a = self.defense_.get(away_team, avg_def)

        lh = float(np.exp(att_h + def_a + self.home_advantage_))
        la = float(np.exp(att_a + def_h))

        mat          = score_matrix(lh, la, self.rho_)
        p_h, p_d, p_a = probs_from_matrix(mat)

        return p_h, p_d, p_a, round(lh, 3), round(la, 3)

    def is_fitted(self) -> bool:
        return self._fitted
