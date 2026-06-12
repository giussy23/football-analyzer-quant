# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
understat.py — xG real desde Understat.com (gratis, sin API key).

Cubre: Premier League, La Liga, Serie A, Bundesliga, Ligue 1.
Los datos se extraen del JSON embebido en el HTML de cada página de liga.
Usa los últimos 10 partidos por equipo para capturar la forma reciente.
"""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import get_close_matches
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DIV_TO_UNDERSTAT: dict[str, str] = {
    "E0":  "EPL",
    "SP1": "La_liga",
    "I1":  "Serie_A",
    "D1":  "Bundesliga",
    "F1":  "Ligue_1",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Nombres de football-data.co.uk → nombres de Understat. Imprescindible donde
# el fuzzy matching falla o, peor, casa con el equipo EQUIVOCADO
# (ej.: "Paris SG" casaba con "Paris FC" en vez de "Paris Saint Germain").
_FD_ALIASES: dict[str, str] = {
    "Wolves":        "Wolverhampton Wanderers",
    "Ath Bilbao":    "Athletic Club",
    "Ath Madrid":    "Atletico Madrid",
    "Parma":         "Parma Calcio 1913",
    "M'gladbach":    "Borussia M.Gladbach",
    "Paris SG":      "Paris Saint Germain",
    "FC Koln":       "FC Cologne",
    "Hamburg":       "Hamburger SV",
    "Leverkusen":    "Bayer Leverkusen",
    "RB Leipzig":    "RasenBallsport Leipzig",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "Milan":         "AC Milan",
    "Newcastle":     "Newcastle United",
    "St Etienne":    "Saint-Etienne",
}
_CACHE_TTL = 6 * 3600  # refrescar cada 6 horas

_memory_cache: dict[tuple, dict] = {}
_cache_ts:     dict[tuple, float] = {}


def current_season() -> int:
    """Año de inicio de la temporada en curso (ej. 2024 para 2024/25)."""
    from datetime import date
    d = date.today()
    return d.year if d.month >= 7 else d.year - 1


def fetch_league_xg(div: str, season: Optional[int] = None) -> dict[str, dict]:
    """
    Descarga y cachea (6h) las stats de xG por equipo para una liga.

    Retorna {team_name: {"xg": float, "xga": float, "npxg": float, "matches": int}}
    o {} si Understat no está disponible o no cubre esa liga.
    """
    if season is None:
        season = current_season()

    league = _DIV_TO_UNDERSTAT.get(div.upper())
    if not league:
        return {}

    key = (league, season)
    now = time.time()
    if key in _memory_cache and (now - _cache_ts.get(key, 0)) < _CACHE_TTL:
        return _memory_cache[key]

    teams_data = _fetch_teams_json(league, season)
    if teams_data is None:
        # Fallback: formato antiguo con teamsData embebido en el HTML
        teams_data = _fetch_teams_html(league, season)
    if teams_data is None:
        logger.warning("Understat no disponible para %s/%d", div, season)
        return {}

    result: dict[str, dict] = {}
    for team_key, info in teams_data.items():
        if not isinstance(info, dict):
            continue
        # Las claves son IDs numéricos; el nombre real viene en "title"
        team_name = str(info.get("title") or team_key)
        history = info.get("history", [])
        if not history:
            continue
        recent = history[-10:]

        def _mean(key_name: str) -> float:
            vals = [float(g.get(key_name) or 0) for g in recent]
            return round(sum(vals) / len(vals), 3) if vals else 0.0

        result[team_name] = {
            "xg":    _mean("xG"),
            "xga":   _mean("xGA"),
            "npxg":  _mean("npxG"),
            "matches": len(recent),
        }

    _memory_cache[key] = result
    _cache_ts[key]     = now
    logger.info("Understat %s/%d: %d equipos cargados.", league, season, len(result))
    return result


def _fetch_teams_json(league: str, season: int) -> Optional[dict]:
    """Endpoint JSON de Understat (formato desde dic 2025).

    GET /getLeagueData/{league}/{season} → {"teams": {...}, "players": ..., "dates": ...}
    (es el mismo endpoint que usa su propio frontend en js/league.min.js).
    """
    url = f"https://understat.com/getLeagueData/{league}/{season}"
    try:
        resp = requests.get(
            url,
            headers={**_HEADERS, "X-Requested-With": "XMLHttpRequest"},
            timeout=25,
        )
        resp.raise_for_status()
        teams = (resp.json() or {}).get("teams")
        return teams if isinstance(teams, dict) and teams else None
    except Exception as exc:
        logger.debug("Understat getLeagueData %s/%d falló: %s", league, season, exc)
        return None


def _fetch_teams_html(league: str, season: int) -> Optional[dict]:
    """Formato antiguo: teamsData embebido como JSON.parse('...') en el HTML."""
    url = f"https://understat.com/league/{league}/{season}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=25)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug("Understat HTML %s/%d falló: %s", league, season, exc)
        return None

    m = re.search(r"teamsData\s*=\s*JSON\.parse\('(.+?)'\)", resp.text, re.DOTALL)
    if not m:
        logger.debug("teamsData no encontrado en HTML de Understat %s/%d", league, season)
        return None
    return _decode_understat_json(m.group(1))


def get_team_xg(team: str, league_xg: dict[str, dict], cutoff: float = 0.6) -> Optional[dict]:
    """
    Busca las stats de xG de un equipo con fuzzy matching.
    Retorna None si no hay match suficientemente cercano.
    """
    if not league_xg:
        return None
    if team in league_xg:
        return league_xg[team]

    # Alias explícito (evita matches erróneos del fuzzy: Paris SG ≠ Paris FC)
    alias = _FD_ALIASES.get(team)
    if alias and alias in league_xg:
        return league_xg[alias]

    candidates = list(league_xg.keys())
    hits = get_close_matches(team, candidates, n=1, cutoff=cutoff)
    if hits:
        return league_xg[hits[0]]

    # Primer token: "Arsenal FC" → "Arsenal"
    first = team.split()[0] if team else ""
    if first:
        hits2 = get_close_matches(first, candidates, n=1, cutoff=0.85)
        if hits2:
            return league_xg[hits2[0]]

    return None


# ── Decodificación robusta de JSON de Understat ───────────────────────────────

def _decode_understat_json(raw: str) -> Optional[dict]:
    r"""
    Intenta tres estrategias para decodificar el JSON embebido de Understat,
    que puede usar \x## o \u#### como secuencias de escape.
    """
    # Estrategia 1: JSON directo (Understat moderno)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Estrategia 2: decodificar escapes \x## y luego parsear
    try:
        decoded = re.sub(
            r'\\x([0-9a-fA-F]{2})',
            lambda m: chr(int(m.group(1), 16)),
            raw,
        )
        return json.loads(decoded)
    except (json.JSONDecodeError, ValueError):
        pass

    # Estrategia 3 ELIMINADA: encode('raw_unicode_escape').decode('unicode_escape')
    # corrompe nombres de equipo con caracteres multi-byte (ej. Atlético → mojibake).
    # Las estrategias 1 y 2 cubren todos los formatos conocidos de Understat.

    logger.warning("No se pudo decodificar el JSON de Understat.")
    return None
