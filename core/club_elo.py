# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/club_elo.py — Ratings ELO de clubes desde clubelo.com

clubelo.com mantiene ELO actualizado para ~700 clubes europeos.
Se usa en la Quiniela como fallback cuando el modelo ML no tiene datos
de un partido (p. ej. Copa del Rey, equipos de Segunda que no aparecen
en los fixtures de La Liga).

Por qué es mejor que eloratings.net para clubes:
  - eloratings.net es para SELECCIONES NACIONALES (Mundiales, Euros)
  - clubelo.com tiene ratings específicos de clubes, actualizados semanalmente

API pública: http://api.clubelo.com/YYYY-MM-DD
Devuelve CSV: Rank, Club, Country, Level, Elo, From, To
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

_API_BASE = "http://api.clubelo.com"
_HOME_ADV  = 65    # ventaja local en puntos ELO (calibrado para ligas europeas)
_TIMEOUT   = 10


class ClubEloModel:
    """
    Ratings ELO para equipos de clubes de fútbol.

    Fórmula de predicción 1X2 con corrección de empates calibrada para
    fútbol de clubes europeos (~28% draw rate histórico).

    Uso:
        model = ClubEloModel()
        if model.load():
            result = model.predict("Real Madrid", "FC Barcelona")
            # → (p_home, p_draw, p_away, elo_home, elo_away)
    """

    def __init__(self) -> None:
        self._ratings: dict[str, float] = {}
        self._loaded  = False

    # ── Carga ──────────────────────────────────────────────────────────────────

    def load(self, timeout: int = _TIMEOUT) -> bool:
        """Descarga los ratings actuales desde clubelo.com."""
        today = date.today().isoformat()
        url   = f"{_API_BASE}/{today}"
        try:
            resp = requests.get(
                url, timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 Football-Analyzer/1.0"},
            )
            resp.raise_for_status()

            df = pd.read_csv(pd.io.common.StringIO(resp.text))
            df.columns = [c.strip() for c in df.columns]

            if "Club" not in df.columns or "Elo" not in df.columns:
                logger.warning("ClubElo: formato inesperado %s", df.columns.tolist())
                return False

            self._ratings = {
                str(row["Club"]).strip(): float(row["Elo"])
                for _, row in df.iterrows()
                if pd.notna(row.get("Elo")) and float(row["Elo"]) > 0
            }
            self._loaded = True
            logger.info("ClubElo cargado: %d equipos (%s)", len(self._ratings), today)
            return True

        except Exception as exc:
            logger.warning("ClubElo no disponible (%s) — usando fallback ELO nacional.", exc)
            return False

    def is_ready(self) -> bool:
        return self._loaded and bool(self._ratings)

    # ── Búsqueda de equipo ─────────────────────────────────────────────────────

    def get_elo(self, team: str) -> Optional[float]:
        """
        Busca el ELO de un equipo con múltiples estrategias de normalización.

        1. Búsqueda exacta
        2. Insensible a mayúsculas
        3. Parcial: el nombre buscado está contenido en el de la DB (o viceversa)
        """
        if not self._ratings:
            return None

        # 1. Exacta
        if team in self._ratings:
            return self._ratings[team]

        tl = team.lower().strip()

        # 2. Case-insensitive exacta
        for name, elo in self._ratings.items():
            if name.lower().strip() == tl:
                return elo

        # 3. Coincidencia parcial (para nombres acortados: "Man City" ↔ "Manchester City")
        for name, elo in self._ratings.items():
            nl = name.lower().strip()
            if tl and nl and (tl in nl or nl in tl):
                return elo

        return None

    # ── Predicción ─────────────────────────────────────────────────────────────

    def predict(
        self,
        home_team: str,
        away_team: str,
        home_advantage: int = _HOME_ADV,
    ) -> Optional[tuple[float, float, float, float, float]]:
        """
        Predice probabilidades 1X2 para un partido de clubes.

        Devuelve (p_home, p_draw, p_away, elo_home, elo_away) o None si
        alguno de los equipos no tiene rating en la base de datos.
        """
        elo_h = self.get_elo(home_team)
        elo_a = self.get_elo(away_team)

        if elo_h is None or elo_a is None:
            logger.debug(
                "ClubElo: sin rating para '%s' o '%s'", home_team, away_team
            )
            return None

        return _elo_to_1x2(elo_h, elo_a, home_advantage)


# ── Fórmula ELO → 1X2 ──────────────────────────────────────────────────────────

def _elo_to_1x2(
    elo_home: float,
    elo_away: float,
    home_adv: int = _HOME_ADV,
) -> tuple[float, float, float, float, float]:
    """
    Convierte ratings ELO de clubes en probabilidades 1X2.

    Modelo calibrado contra resultados históricos de ligas europeas:

    1. P(victoria local) = función logística de la diferencia ELO ajustada
       por ventaja de campo (+65 puntos en clubes europeos como media).

    2. P(empate) sigue una distribución en campana invertida:
       - Máxima (~30%) cuando ambos equipos están muy igualados (diff ≈ 0)
       - Mínima (~10%) cuando el favorito es muy claro (diff > 300 pts)
       - Fórmula: 0.30 × exp(-2.5 × (p_win - 0.45)²)

    3. P(victoria visitante) = 1 - P(local) - P(empate)
    """
    diff  = float(elo_home) + home_adv - float(elo_away)
    p_win = 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

    # Corrección de empates (curva de Gauss alrededor de p_win ≈ 0.45)
    p_draw = 0.30 * float(np.exp(-2.5 * (p_win - 0.45) ** 2))
    p_draw = float(np.clip(p_draw, 0.10, 0.32))

    p_home = p_win * (1.0 - p_draw)
    p_away = (1.0 - p_win) * (1.0 - p_draw)

    # Normalizar para que sumen exactamente 1.0
    total  = p_home + p_draw + p_away
    p_home /= total
    p_draw /= total
    p_away /= total

    return (
        round(float(p_home), 4),
        round(float(p_draw), 4),
        round(float(p_away), 4),
        round(float(elo_home), 1),
        round(float(elo_away), 1),
    )
