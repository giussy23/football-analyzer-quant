# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
lineups.py — Alineaciones via ESPN public API (sin registro, sin API key).

ESPN API: site.api.espn.com/apis/site/v2/sports/soccer
Cobertura: Premier League, LaLiga, Serie A, Bundesliga, Ligue 1.
Las alineaciones se publican ~1h antes del partido. Fuera de ese rango
todas las funciones retornan {} sin lanzar excepciones.
"""

from __future__ import annotations

import logging
from datetime import date as _date

import requests

logger = logging.getLogger(__name__)

# ── ESPN API ───────────────────────────────────────────────────────────────────

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Nuestros códigos de división → código ESPN de liga
_DIV_TO_ESPN: dict[str, str] = {
    "E0":  "eng.1",
    "SP1": "esp.1",
    "I1":  "ita.1",
    "D1":  "ger.1",
    "F1":  "fra.1",
}

# Caché en memoria: (home6, away6, date) → lineup_dict
_LINEUP_CACHE: dict[tuple, dict] = {}


# ── Helpers internos ───────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> dict:
    """GET con timeout 5 s. Retorna {} en cualquier error."""
    try:
        resp = requests.get(url, params=params or {}, timeout=5)
        if resp.ok:
            return resp.json()
    except Exception as exc:
        logger.debug("ESPN API error: %s", exc)
    return {}


def _match_team(query: str, candidate: str) -> bool:
    """Coincidencia flexible: substring de 5 chars en cualquier dirección."""
    q = query.lower().strip()
    c = candidate.lower().strip()
    if not q or not c:
        return False
    if q == c:
        return True
    q5, c5 = q[:5], c[:5]
    return q5 in c or c5 in q


def _find_event(
    home_team: str, away_team: str, match_date: str
) -> tuple[str, str] | None:
    """
    Busca el evento ESPN para el partido dado.
    match_date: 'YYYY-MM-DD'
    Returns (espn_league, event_id) o None si no encuentra.
    """
    espn_date = match_date.replace("-", "")   # → YYYYMMDD

    for espn_league in _DIV_TO_ESPN.values():
        url  = f"{_ESPN_BASE}/{espn_league}/scoreboard"
        data = _get(url, {"dates": espn_date})

        for event in data.get("events", []):
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            competitors = competitions[0].get("competitors", [])
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home_c or not away_c:
                continue

            h_name = home_c.get("team", {}).get("displayName", "")
            a_name = away_c.get("team", {}).get("displayName", "")

            if _match_team(home_team, h_name) and _match_team(away_team, a_name):
                return espn_league, str(event.get("id", ""))

    return None


def _parse_lineup(summary: dict) -> dict:
    """
    Extrae alineaciones del summary ESPN.
    Returns dict con home_starting, away_starting, home_formation, away_formation.
    """
    rosters = summary.get("rosters", [])
    if not rosters:
        return {}

    result: dict = {
        "home_starting":  [],
        "away_starting":  [],
        "home_formation": "?",
        "away_formation": "?",
        "home_missing":   0,
        "away_missing":   0,
    }

    for i, team_data in enumerate(rosters[:2]):
        # Determinar local/visitante: homeAway en team_data o posición (0=local)
        home_away = team_data.get("homeAway") or team_data.get("team", {}).get("homeAway")
        is_home   = (home_away == "home") if home_away else (i == 0)
        prefix    = "home" if is_home else "away"

        formation = team_data.get("formation") or "?"
        result[f"{prefix}_formation"] = formation

        starters = [
            p.get("athlete", {}).get("displayName", "")
            for p in team_data.get("roster", [])
            if p.get("starter") and p.get("athlete", {}).get("displayName")
        ]
        result[f"{prefix}_starting"] = starters

    # Solo devolvemos si hay datos útiles
    if result["home_starting"] or result["away_starting"]:
        return result
    return {}


# ── API pública ────────────────────────────────────────────────────────────────

def get_lineup_for_match(
    home_team: str,
    away_team: str,
    match_date: str = "",
) -> dict:
    """
    Obtiene la alineación de un partido via ESPN (gratis, sin registro).

    Returns dict con:
        home_starting  : list[str]  — titulares locales
        away_starting  : list[str]  — titulares visitantes
        home_formation : str        — "4-3-3" etc.
        away_formation : str
        home_missing   : int        — 0 (ESPN no informa bajas explícitas)
        away_missing   : int

    Retorna {} si no hay datos disponibles.
    Nunca lanza excepciones.
    """
    if not match_date:
        match_date = str(_date.today())

    cache_key = (home_team.lower()[:6], away_team.lower()[:6], match_date)
    if cache_key in _LINEUP_CACHE:
        return _LINEUP_CACHE[cache_key]

    try:
        found = _find_event(home_team, away_team, match_date)
        if not found:
            logger.debug("ESPN: no encontrado — %s vs %s (%s)", home_team, away_team, match_date)
            return {}

        espn_league, event_id = found
        summary = _get(f"{_ESPN_BASE}/{espn_league}/summary", {"event": event_id})
        lineup  = _parse_lineup(summary)

        if lineup:
            _LINEUP_CACHE[cache_key] = lineup
        return lineup

    except Exception as exc:
        logger.debug("get_lineup_for_match error: %s", exc)
        return {}


def clear_cache() -> None:
    """Limpia la caché de alineaciones (llamar al inicio de nuevo análisis)."""
    _LINEUP_CACHE.clear()
