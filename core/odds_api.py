"""
core/odds_api.py — Integración con The Odds API.

Cuotas en tiempo real desde múltiples casas de apuestas.
Plan gratuito: 500 peticiones/mes · Sin tarjeta · https://the-odds-api.com

Uso:
    from .odds_api import fetch_odds_fixtures, validate_api_key
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

# ── Mapeo div-code → sport_key de The Odds API ────────────────────────────────

DIV_TO_SPORT_KEY: dict[str, str] = {
    "E0":  "soccer_epl",
    "E1":  "soccer_efl_champ",
    "SP1": "soccer_spain_la_liga",
    "SP2": "soccer_spain_segunda_division",
    "I1":  "soccer_italy_serie_a",
    "D1":  "soccer_germany_bundesliga",
    "F1":  "soccer_france_ligue_one",
    "P1":  "soccer_portugal_primeira_liga",
    "N1":  "soccer_netherlands_eredivisie",
}


# ── API pública ───────────────────────────────────────────────────────────────

def fetch_odds_fixtures(
    api_key: str,
    div_codes: list[str],
    bookmaker: str = "bet365",
    regions: str = "eu",
) -> pd.DataFrame:
    """
    Descarga próximos partidos con cuotas en tiempo real de The Odds API.

    Devuelve un DataFrame con las mismas columnas que football-data.co.uk
    (Date, Time, HomeTeam, AwayTeam, Div, B365H, B365D, B365A, B365O25, B365U25)
    para que prepare_fixtures() lo procese sin cambios.

    Parámetros
    ----------
    api_key   : API key gratuita de the-odds-api.com
    div_codes : Códigos de liga usados en el proyecto (E0, SP1, I1…)
    bookmaker : Casa preferida para cuotas (bet365, unibet, betfair…)
    regions   : Región de cuotas ('eu' para Europa)
    """
    all_rows: list[dict] = []
    requests_remaining: Optional[str] = None

    for div in div_codes:
        sport_key = DIV_TO_SPORT_KEY.get(div.upper())
        if not sport_key:
            logger.warning("Sin sport_key para div=%s, se omite.", div)
            continue

        url = f"{BASE_URL}/sports/{sport_key}/odds"
        params = {
            "apiKey":     api_key,
            "regions":    regions,
            "markets":    "h2h,totals",
            "bookmakers": bookmaker,
            "oddsFormat": "decimal",
        }

        logger.info("The Odds API → %s (%s)", div, sport_key)

        try:
            resp = requests.get(url, params=params, timeout=15,
                                headers={"User-Agent": "FootballAnalyzerPro/10"})
            resp.raise_for_status()
            requests_remaining = resp.headers.get("x-requests-remaining")
            data = resp.json()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code == 401:
                raise ValueError(
                    "API key inválida. Verifica tu clave en https://the-odds-api.com"
                ) from exc
            if code == 422:
                logger.warning("Liga %s no disponible en The Odds API (%s).", div, sport_key)
                continue
            logger.error("HTTP %s al descargar %s: %s", code, div, exc)
            continue
        except Exception as exc:
            logger.error("Error de conexión para %s: %s", div, exc)
            continue

        for match in data:
            row = _parse_match(match, div, bookmaker)
            if row:
                all_rows.append(row)

    if requests_remaining:
        logger.info("Peticiones restantes este mes: %s", requests_remaining)

    if not all_rows:
        logger.warning("The Odds API no devolvió partidos. Revisa la API key y las ligas.")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    logger.info("The Odds API: %d fixtures descargados.", len(df))
    return df


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Verifica si una API key es válida haciendo una petición mínima al endpoint /sports.
    Devuelve (True, mensaje_ok) o (False, mensaje_error).
    """
    if not api_key or len(api_key.strip()) < 8:
        return False, "La API key está vacía o es demasiado corta."

    try:
        resp = requests.get(
            f"{BASE_URL}/sports",
            params={"apiKey": api_key.strip()},
            timeout=10,
            headers={"User-Agent": "FootballAnalyzerPro/10"},
        )
        if resp.status_code == 401:
            return False, "❌  API key inválida. Comprueba tu clave en the-odds-api.com"
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used",      "?")
        return True, (
            f"✓  Conexión correcta\n"
            f"Peticiones usadas este mes: {used}\n"
            f"Peticiones restantes:       {remaining}"
        )
    except requests.HTTPError as exc:
        return False, f"Error HTTP {exc.response.status_code if exc.response else '?'}"
    except Exception as exc:
        return False, f"Sin conexión: {exc}"


# ── Parser interno ────────────────────────────────────────────────────────────

def _parse_match(match: dict, div: str, preferred_bk: str) -> Optional[dict]:
    """Convierte un partido de The Odds API al formato football-data.co.uk."""
    home = match.get("home_team", "").strip()
    away = match.get("away_team", "").strip()
    if not home or not away:
        return None

    # Fecha/hora en zona horaria de Madrid
    commence = match.get("commence_time", "")
    try:
        ts = pd.to_datetime(commence, utc=True).tz_convert("Europe/Madrid")
        date_str = ts.strftime("%d/%m/%Y")
        time_str = ts.strftime("%H:%M")
    except Exception:
        date_str = commence[:10] if len(commence) >= 10 else ""
        time_str = ""

    row: dict = {
        "Date":     date_str,
        "Time":     time_str,
        "HomeTeam": home,
        "AwayTeam": away,
        "Div":      div,
        "B365H":    None,
        "B365D":    None,
        "B365A":    None,
        "B365O25":  None,
        "B365U25":  None,
    }

    # Seleccionar bookmaker: preferido → primero disponible
    bookmakers = match.get("bookmakers", [])
    bk = next((b for b in bookmakers if b.get("key") == preferred_bk), None)
    if not bk and bookmakers:
        bk = bookmakers[0]
    if not bk:
        return row  # partido sin cuotas pero lo incluimos igual

    for market in bk.get("markets", []):
        mkey     = market.get("key")
        outcomes = market.get("outcomes", [])

        if mkey == "h2h":
            for o in outcomes:
                name  = o.get("name", "")
                price = float(o.get("price", 0) or 0)
                if name == home:
                    row["B365H"] = price
                elif name == "Draw":
                    row["B365D"] = price
                elif name == away:
                    row["B365A"] = price

        elif mkey == "totals":
            for o in outcomes:
                try:
                    point = float(o.get("point", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if abs(point - 2.5) < 0.01:
                    name  = o.get("name", "")
                    price = float(o.get("price", 0) or 0)
                    if name == "Over":
                        row["B365O25"] = price
                    elif name == "Under":
                        row["B365U25"] = price

    return row
