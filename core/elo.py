# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/elo.py — Modelo Elo para selecciones nacionales.

El sistema Elo estima la fuerza relativa de cada selección y predice
probabilidades de victoria/empate/derrota sin necesitar datos históricos
de goles. Es el mismo sistema que usa la FIFA para los seedings mundiales.

Fuente de ratings: eloratings.net (con fallback a valores conocidos).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_ELO_URL = "https://www.eloratings.net/World"

# ── Ratings Elo de referencia (junio 2026, estimados) ────────────────────────
# Fuente: eloratings.net / FIFA Rankings combinados
_FALLBACK_ELO: dict[str, float] = {
    # Top selecciones
    "Argentina":            2141, "France":               2087,
    "England":              2082, "Brazil":                2075,
    "Spain":                2074, "Portugal":              2063,
    "Germany":              2055, "Netherlands":           2048,
    "Belgium":              2012, "Italy":                 1993,
    "Croatia":              1991, "Uruguay":               1985,
    "Colombia":             1963, "Mexico":                1951,
    "Denmark":              1945, "Switzerland":           1938,
    "USA":                  1936, "Japan":                 1920,
    "Senegal":              1908, "Morocco":               1900,
    "Ecuador":              1875, "Canada":                1868,
    "Australia":            1857, "South Korea":           1853,
    "Poland":               1842, "Serbia":                1838,
    "Austria":              1830, "Wales":                 1822,
    "Chile":                1815, "Peru":                  1812,
    "Venezuela":            1800, "Paraguay":              1795,
    "Bolivia":              1782, "Romania":               1775,
    "Czech Republic":       1770, "Slovakia":              1765,
    "Turkey":               1762, "Hungary":               1755,
    "Ukraine":              1750, "Scotland":              1748,
    "Norway":               1745, "Sweden":                1742,
    "Ireland":              1730, "Greece":                1728,
    "Slovenia":             1720, "Albania":               1710,
    "Iceland":              1705, "Tunisia":               1700,
    "Egypt":                1698, "Algeria":               1690,
    "Cameroon":             1685, "Ghana":                 1680,
    "Nigeria":              1675, "South Africa":          1665,
    "Qatar":                1620, "Saudi Arabia":          1615,
    "Iran":                 1610, "New Zealand":           1590,
    "Haiti":                1560, "Jamaica":               1550,
    "El Salvador":          1540, "Honduras":              1535,
    "Costa Rica":           1530, "Panama":                1525,
    "Cuba":                 1480, "Estonia":               1460,
    "Latvia":               1455, "Lithuania":             1448,
    "Faroe Islands":        1380, "Liechtenstein":         1320,
    "Cyprus":               1400, "Curacao":               1520,
    "Cape Verde":           1580, "Bosnia & Herzegovina":  1710,
    "Bosnia":               1710, "Kosovo":                1610,
    "Finland":              1680, "Georgia":               1640,
    "North Macedonia":      1620, "Montenegro":            1590,
    "Belarus":              1570, "Luxembourg":            1490,
    "Armenia":              1540, "Azerbaijan":            1510,
    "Kazakhstan":           1480, "Moldova":               1450,
    "Gibraltar":            1200, "San Marino":            1100,
    "Ivory Coast":          1710, "Burkina Faso":          1630,
    "Mali":                 1640, "Guinea":                1590,
    "Zimbabwe":             1520, "Uganda":                1530,
    "Tanzania":             1510, "Zambia":                1510,
    "Congo DR":             1580, "Angola":                1520,
    "Mozambique":           1490, "Cape Verde":            1580,
    "Comoros":              1410, "Malawi":                1430,
    "Jordan":               1560, "Iraq":                  1580,
    "Syria":                1520, "Kuwait":                1490,
    "Bahrain":              1480, "UAE":                   1530,
    "Oman":                 1530, "Yemen":                 1360,
    "Lebanon":              1490, "Palestine":             1480,
    "Panama":               1525, "Honduras":              1535,
    "Nicaragua":            1420, "Guatemala":             1490,
    "Trinidad and Tobago":  1520, "Guyana":                1380,
    "Suriname":             1400, "Belize":                1300,
}

# Alias para nombres usados en The Odds API vs Elo
_ALIASES: dict[str, str] = {
    "usa":                           "USA",
    "united states":                 "USA",
    "south korea":                   "South Korea",
    "korea republic":                "South Korea",
    "republic of ireland":           "Ireland",
    "ivory coast":                   "Ivory Coast",
    "cote d'ivoire":                 "Ivory Coast",
    "czech republic":                "Czech Republic",
    "bosnia & herzegovina":          "Bosnia & Herzegovina",
    "trinidad & tobago":             "Trinidad and Tobago",
    "new zealand":                   "New Zealand",
    "cape verde":                    "Cape Verde",
    "north macedonia":               "North Macedonia",
    "saudi arabia":                  "Saudi Arabia",
    "democratic republic of congo":  "Congo DR",
    "dr congo":                      "Congo DR",
    "uae":                           "UAE",
}


# ── Utilidades ────────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    """Normaliza nombre sin acentos, minúsculas."""
    nfkd = unicodedata.normalize("NFKD", name)
    return re.sub(r"\s+", " ",
                  "".join(c for c in nfkd if not unicodedata.combining(c))
                  .lower()).strip()


# ── Probabilidades desde Elo ─────────────────────────────────────────────────

def _draw_prob(elo_diff: float) -> float:
    """La probabilidad de empate disminuye con diferencias grandes."""
    return max(0.08, 0.27 - min(0.12, abs(elo_diff) / 1500))


def elo_probs(
    elo_home: float,
    elo_away: float,
    home_adv: float = 0.0,
) -> tuple[float, float, float]:
    """
    P(local gana), P(empate), P(visitante gana) usando el modelo Elo estándar.

    home_adv = 0 en partidos en campo neutral (Mundial).
    """
    diff = elo_home - elo_away + home_adv
    p_win_home = 1.0 / (1.0 + 10 ** (-diff / 400))
    draw = _draw_prob(diff)
    p_h = round(p_win_home * (1.0 - draw), 4)
    p_d = round(draw, 4)
    p_a = round(max(0.0, 1.0 - p_h - p_d), 4)
    return p_h, p_d, p_a


# ── Modelo Elo ────────────────────────────────────────────────────────────────

class EloModel:
    """
    Predicciones Elo para selecciones nacionales.

    Intenta cargar ratings frescos de eloratings.net;
    si falla, usa tabla interna de fallback.
    """

    def __init__(self) -> None:
        self.ratings: dict[str, float] = dict(_FALLBACK_ELO)
        self.fresh = False

    def load_ratings(self, timeout: int = 8) -> bool:
        """
        Descarga ratings actualizados de eloratings.net.
        Retorna True si tuvo éxito.
        """
        try:
            resp = requests.get(
                _ELO_URL,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            )
            resp.raise_for_status()
            parsed = self._parse_html(resp.text)
            if parsed:
                self.ratings.update(parsed)
                self.fresh = True
                logger.info("EloModel: %d ratings actualizados desde eloratings.net", len(parsed))
                return True
        except Exception as exc:
            logger.info("EloModel: usando ratings internos (%s)", exc)
        return False

    @staticmethod
    def _parse_html(html: str) -> dict[str, float]:
        """Extrae nombre→rating de la tabla de eloratings.net."""
        found: dict[str, float] = {}
        # Patrón adaptado a la estructura de eloratings.net
        for m in re.finditer(
            r'<td[^>]*class="[^"]*country[^"]*"[^>]*>([^<]+)</td>\s*'
            r'<td[^>]*>(\d{3,4})</td>',
            html, re.DOTALL | re.IGNORECASE,
        ):
            name   = m.group(1).strip()
            rating = float(m.group(2))
            if 900 <= rating <= 2500 and len(name) > 2:
                found[name] = rating
        # Fallback: cualquier par nombre + 4 dígitos razonables
        if not found:
            for m in re.finditer(r'>([A-Z][a-zA-Z ]{2,24})</td>\s*<td[^>]*>(\d{4})<', html):
                name   = m.group(1).strip()
                rating = float(m.group(2))
                if 900 <= rating <= 2500:
                    found[name] = rating
        return found

    def get_rating(self, team: str, default: float = 1500.0) -> float:
        """Busca el rating Elo, probando alias y búsqueda parcial."""
        # Alias conocidos
        norm = _norm(team)
        resolved = _ALIASES.get(norm, team)

        # Búsqueda exacta
        if resolved in self.ratings:
            return self.ratings[resolved]

        # Búsqueda case-insensitive
        for k, v in self.ratings.items():
            if _norm(k) == norm:
                return v

        # Búsqueda parcial (uno contiene al otro)
        for k, v in self.ratings.items():
            kn = _norm(k)
            if norm in kn or kn in norm:
                return v

        logger.debug("EloModel: '%s' sin rating, usando default %.0f", team, default)
        return default

    def predict(
        self,
        home_team: str,
        away_team: str,
        home_adv: float = 0.0,
    ) -> tuple[float, float, float, float, float]:
        """
        Retorna (p_home, p_draw, p_away, elo_home, elo_away).
        home_adv=0 en el Mundial (campo neutral).
        """
        elo_h = self.get_rating(home_team)
        elo_a = self.get_rating(away_team)
        p_h, p_d, p_a = elo_probs(elo_h, elo_a, home_adv)
        return p_h, p_d, p_a, elo_h, elo_a

    def is_ready(self) -> bool:
        return len(self.ratings) > 10
