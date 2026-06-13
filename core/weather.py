# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
weather.py — Cliente Open-Meteo para features meteorológicas del modelo ML.

API gratuita, sin clave. Documentación: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import requests

# ── Coordenadas de ciudades ────────────────────────────────────────────────────

CITY_COORDS: dict[str, tuple[float, float]] = {
    # England (E0)
    "London":     (51.5074,  -0.1278),
    "Manchester": (53.4808,  -2.2426),
    "Liverpool":  (53.4084,  -2.9916),
    "Birmingham": (52.4862,  -1.8904),
    "Leeds":      (53.8008,  -1.5491),
    "Newcastle":  (54.9783,  -1.6178),
    # Spain (SP1)
    "Madrid":     (40.4168,  -3.7038),
    "Barcelona":  (41.3851,   2.1734),
    "Seville":    (37.3891,  -5.9845),
    "Valencia":   (39.4699,  -0.3763),
    "Bilbao":     (43.2627,  -2.9253),
    # Italy (I1)
    "Milan":      (45.4654,   9.1859),
    "Rome":       (41.9028,  12.4964),
    "Turin":      (45.0703,   7.6869),
    "Naples":     (40.8518,  14.2681),
    "Florence":   (43.7696,  11.2558),
    # Germany (D1)
    "Munich":     (48.1351,  11.5820),
    "Berlin":     (52.5200,  13.4050),
    "Hamburg":    (53.5753,  10.0153),
    "Dortmund":   (51.5136,   7.4653),
    "Frankfurt":  (50.1109,   8.6821),
    # France (F1)
    "Paris":      (48.8566,   2.3522),
    "Lyon":       (45.7640,   4.8357),
    "Marseille":  (43.2965,   5.3698),
    "Lille":      (50.6292,   3.0573),
    "Bordeaux":   (44.8378,  -0.5792),
}

# ── Mapeo equipo → ciudad ─────────────────────────────────────────────────────

TEAM_TO_CITY: dict[str, str] = {
    # England
    "Arsenal":        "London",
    "Chelsea":        "London",
    "Tottenham":      "London",
    "West Ham":       "London",
    "Crystal Palace": "London",
    "Fulham":         "London",
    "Brentford":      "London",
    "Wimbledon":      "London",
    "Man United":     "Manchester",
    "Man City":       "Manchester",
    "Liverpool":      "Liverpool",
    "Everton":        "Liverpool",
    "Aston Villa":    "Birmingham",
    "Birmingham":     "Birmingham",
    "Leeds":          "Leeds",
    "Newcastle":      "Newcastle",
    "Sunderland":     "Newcastle",
    # Spain
    "Real Madrid":    "Madrid",
    "Atletico Madrid":"Madrid",
    "Getafe":         "Madrid",
    "Barcelona":      "Barcelona",
    "Espanyol":       "Barcelona",
    "Sevilla":        "Seville",
    "Betis":          "Seville",
    "Valencia":       "Valencia",
    "Villarreal":     "Valencia",
    "Athletic Club":  "Bilbao",
    "Ath Bilbao":     "Bilbao",
    # Italy
    "AC Milan":       "Milan",
    "Inter":          "Milan",
    "Roma":           "Rome",
    "Lazio":          "Rome",
    "Juventus":       "Turin",
    "Torino":         "Turin",
    "Napoli":         "Naples",
    "Fiorentina":     "Florence",
    # Germany
    "Bayern Munich":  "Munich",
    "1860 Munich":    "Munich",
    "Hertha":         "Berlin",
    "Union Berlin":   "Berlin",
    "Hamburg":        "Hamburg",
    "Dortmund":       "Dortmund",
    "Schalke":        "Dortmund",
    "Frankfurt":      "Frankfurt",
    # France
    "Paris SG":       "Paris",
    "PSG":            "Paris",
    "Lyon":           "Lyon",
    "Marseille":      "Marseille",
    "Lille":          "Lille",
    "Bordeaux":       "Bordeaux",
}

# ── Caché en memoria ──────────────────────────────────────────────────────────

_WEATHER_CACHE: dict[tuple, dict] = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_city(home_team: str) -> str | None:
    """
    Resuelve el nombre del equipo a ciudad.
    Primero intenta coincidencia exacta; si no, busca el primer equipo
    cuyo nombre contenga la cadena recibida (fuzzy parcial, case-insensitive).
    """
    # Exacto
    if home_team in TEAM_TO_CITY:
        return TEAM_TO_CITY[home_team]

    # Fuzzy: substring bidireccional
    team_lower = home_team.lower()
    for key, city in TEAM_TO_CITY.items():
        if key.lower() in team_lower or team_lower in key.lower():
            return city

    return None


# ── Función principal ─────────────────────────────────────────────────────────

def get_match_weather(home_team: str, match_date: str) -> dict:
    """
    Obtiene el pronóstico meteorológico para la ubicación del partido.

    Parameters
    ----------
    home_team  : nombre del equipo local (se resuelve a ciudad internamente)
    match_date : fecha del partido en formato 'YYYY-MM-DD'

    Returns
    -------
    dict con claves: rain_mm, wind_kmh, temp_c, is_bad_weather (bool)
    Devuelve {} ante cualquier error (degradación graceful).
    """
    city = _resolve_city(home_team)
    if city is None:
        return {}

    cache_key = (city, match_date)
    if cache_key in _WEATHER_CACHE:
        return _WEATHER_CACHE[cache_key]

    coords = CITY_COORDS.get(city)
    if coords is None:
        return {}

    lat, lon = coords
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":   lat,
        "longitude":  lon,
        "daily":      "precipitation_sum,wind_speed_10m_max,temperature_2m_mean",
        "timezone":   "auto",
        "start_date": match_date,
        "end_date":   match_date,
    }

    try:
        resp = requests.get(url, params=params, timeout=3)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        rain_list = daily.get("precipitation_sum", [None])
        wind_list = daily.get("wind_speed_10m_max", [None])
        temp_list = daily.get("temperature_2m_mean", [None])

        rain_mm  = float(rain_list[0]) if rain_list and rain_list[0] is not None else 0.0
        wind_kmh = float(wind_list[0]) if wind_list and wind_list[0] is not None else 0.0
        temp_c   = float(temp_list[0]) if temp_list and temp_list[0] is not None else 15.0

        result: dict = {
            "rain_mm":       rain_mm,
            "wind_kmh":      wind_kmh,
            "temp_c":        temp_c,
            "is_bad_weather": rain_mm > 5.0 or wind_kmh > 40.0,
        }

        _WEATHER_CACHE[cache_key] = result
        return result

    except Exception:
        return {}
