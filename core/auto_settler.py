# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/auto_settler.py — Auto-liquidacion de picks usando la ESPN Scores API.

No requiere API key ni registro. Cubre las 5 ligas europeas top + Segunda,
Championship y Eredivisie. Para picks mas antiguos de ~2 semanas, ESPN
puede no devolver datos; esos picks quedan como PENDING.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Mapa de nuestros div codes → liga ESPN
_DIV_TO_ESPN: dict[str, str] = {
    "E0":  "eng.1",   # Premier League
    "E1":  "eng.2",   # Championship
    "SP1": "esp.1",   # La Liga
    "SP2": "esp.2",   # Segunda Division
    "I1":  "ita.1",   # Serie A
    "D1":  "ger.1",   # Bundesliga
    "D2":  "ger.2",   # 2. Bundesliga
    "F1":  "fra.1",   # Ligue 1
    "P1":  "por.1",   # Primeira Liga
    "N1":  "ned.1",   # Eredivisie
}

# Cuando no conocemos la liga, probamos las mas habituales primero
_FALLBACK_ORDER = ["eng.1", "esp.1", "ita.1", "ger.1", "fra.1",
                   "esp.2", "eng.2", "por.1", "ned.1", "ger.2"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None) -> dict:
    """GET con timeout 8 s. Nunca lanza excepciones."""
    try:
        resp = requests.get(url, params=params or {}, timeout=8)
        if resp.ok:
            return resp.json()
    except Exception as exc:
        logger.debug("ESPN auto_settler: %s", exc)
    return {}


# Sufijos/prefijos genéricos que no distinguen al equipo (FC, CF, AS Roma…)
_GENERIC_TOKENS = {
    "fc", "cf", "afc", "sc", "ssc", "ac", "as", "cd", "ud", "rcd", "rc",
    "club", "de", "the", "calcio", "ssd", "us", "ss", "1", "il",
}


def _normalize(name: str) -> str:
    """Minúsculas, sin acentos ni espacios sobrantes."""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def _tokens(name: str) -> list[str]:
    """Tokens significativos del nombre (sin genéricos como FC/CF/AS)."""
    norm = _normalize(name)
    return [t for t in re.split(r"[\s.\-_]+", norm)
            if t and t not in _GENERIC_TOKENS]


def _team_match(query: str, candidate: str) -> bool:
    """
    Coincidencia por TOKENS entre nombres de equipo.

    Tolera abreviaturas reales ("Man United" ↔ "Manchester United") porque
    permite que un token sea prefijo del otro (≥3 chars), pero NO confunde
    equipos que solo comparten un prefijo: "Real Madrid" vs "Real Sociedad"
    o "Manchester United" vs "Manchester City" quedan distinguidos por el
    token restante. (El emparejamiento anterior — prefijo de 5 chars sobre la
    cadena completa — los daba como iguales y liquidaba el pick equivocado.)
    """
    q = _normalize(query)
    c = _normalize(candidate)
    if not q or not c:
        return False
    if q == c:
        return True

    qt, ct = _tokens(query), _tokens(candidate)
    if not qt or not ct:
        return False

    def _tok_match(a: str, b: str) -> bool:
        if a == b:
            return True
        # Prefijo común de ≥3 chars: "man"→"manchester", "tottenham"→"tottenham…"
        return min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a))

    # Cada token del nombre con MENOS tokens debe casar con alguno del otro.
    short, long_ = (qt, ct) if len(qt) <= len(ct) else (ct, qt)
    return all(any(_tok_match(s, l) for l in long_) for s in short)


# ── Core lookup ────────────────────────────────────────────────────────────────

def get_match_result(
    home: str,
    away: str,
    match_date: str,
    league: str = "",
) -> Optional[dict]:
    """
    Busca el resultado de un partido en la ESPN Scores API.

    Parameters
    ----------
    home, away   : Nombres de los equipos (ingles o español)
    match_date   : Fecha en formato YYYY-MM-DD
    league       : Codigo de liga (E0, SP1, ...) — opcional, acelera la busqueda

    Returns
    -------
    {"home_goals": int, "away_goals": int, "result": "H"|"D"|"A"} o None
    """
    # Convertir a formato ESPN (YYYYMMDD)
    try:
        espn_date = match_date.replace("-", "")[:8]
        if len(espn_date) < 8:
            return None
    except Exception:
        return None

    # Ligas a probar. Si conocemos la liga del pick, buscamos SOLO ahí: un
    # pick de La Liga no debe liquidarse con un partido de otra competición
    # (antes se probaban todas y un falso positivo de nombre liquidaba mal).
    if league and league in _DIV_TO_ESPN:
        leagues = [_DIV_TO_ESPN[league]]
    else:
        leagues = _FALLBACK_ORDER

    for espn_league in leagues:
        url  = f"{_ESPN_BASE}/{espn_league}/scoreboard"
        data = _get(url, {"dates": espn_date})

        for event in data.get("events", []):
            comps = event.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]

            # Verificar que el partido esta completado
            if not comp.get("status", {}).get("type", {}).get("completed", False):
                continue

            competitors = comp.get("competitors", [])
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home_c or not away_c:
                continue

            h_name = home_c.get("team", {}).get("displayName", "")
            a_name = away_c.get("team", {}).get("displayName", "")

            if _team_match(home, h_name) and _team_match(away, a_name):
                try:
                    hg = int(home_c.get("score", ""))
                    ag = int(away_c.get("score", ""))
                except (ValueError, TypeError):
                    continue

                result = "H" if hg > ag else ("D" if hg == ag else "A")
                logger.info(
                    "Auto-settler: %s vs %s -> %d-%d (%s)",
                    home, away, hg, ag, result,
                )
                return {"home_goals": hg, "away_goals": ag, "result": result}

    return None


# ── Pick evaluation ────────────────────────────────────────────────────────────

def pick_is_win(pick: str, match_result: dict) -> Optional[bool]:
    """
    Determina si un pick fue ganador.

    Returns True (WIN), False (LOSS) o None (tipo de pick desconocido).
    """
    p   = str(pick).upper().strip()
    r   = match_result["result"]
    hg  = match_result["home_goals"]
    ag  = match_result["away_goals"]
    tot = hg + ag

    table: dict[str, bool] = {
        "H":         r == "H",
        "HOME":      r == "H",
        "D":         r == "D",
        "DRAW":      r == "D",
        "X":         r == "D",
        "A":         r == "A",
        "AWAY":      r == "A",
        "OVER 2.5":  tot > 2.5,
        "OVER2.5":   tot > 2.5,
        "OVER":      tot > 2.5,
        "UNDER 2.5": tot < 2.5,
        "UNDER2.5":  tot < 2.5,
        "UNDER":     tot < 2.5,
        "BTTS":      hg > 0 and ag > 0,
        "NO BTTS":   not (hg > 0 and ag > 0),
    }
    return table.get(p)


# ── Main entry point ───────────────────────────────────────────────────────────

def auto_settle(
    pending_picks: list[dict],
    bankroll_eur: float,
    storage,
) -> dict:
    """
    Intenta liquidar automaticamente todos los picks con status PENDING.

    Solo procesa picks cuya fecha ya haya pasado. Para picks de hoy
    o futuro, los ignora (quedan como PENDING hasta mañana).

    Parameters
    ----------
    pending_picks : Lista de dicts con los picks (formato de load_model_picks)
    bankroll_eur  : Banca actual en euros (para calcular P&L)
    storage       : Instancia de Storage (para update_pick_result)

    Returns
    -------
    {
      "settled"    : int   — picks liquidados correctamente
      "not_found"  : int   — resultado no encontrado en ESPN
      "skipped"    : int   — partidos futuros / pick desconocido
      "results"    : list  — detalle de cada liquidacion
    }
    """
    today = datetime.now().date()
    settled_n = not_found_n = skipped_n = 0
    detail: list[dict] = []

    for pick in pending_picks:
        if pick.get("status") != "PENDING":
            skipped_n += 1
            continue

        home     = str(pick.get("home_team", "")).strip()
        away     = str(pick.get("away_team", "")).strip()
        date_raw = str(pick.get("date", "")).strip()
        league   = str(pick.get("league", "")).strip()
        pick_val = str(pick.get("pick", "")).strip()

        if not home or not away or not date_raw:
            skipped_n += 1
            continue

        # Solo liquidar partidos pasados
        try:
            match_date = date_raw[:10]  # "YYYY-MM-DD"
            if datetime.strptime(match_date, "%Y-%m-%d").date() >= today:
                skipped_n += 1
                continue
        except Exception:
            skipped_n += 1
            continue

        result = get_match_result(home, away, match_date, league)

        if result is None:
            not_found_n += 1
            continue

        win = pick_is_win(pick_val, result)
        if win is None:
            # Tipo de pick no soportado (mercado exotico)
            skipped_n += 1
            continue

        # Calcular P&L
        try:
            odds  = float(pick.get("odds")        or 1.0)
            bp    = float(pick.get("bankroll_pct") or 0.02)
            stake = bankroll_eur * bp
            pnl   = round(stake * (odds - 1) if win else -stake, 2)
        except Exception:
            pnl = 0.0

        status = "WIN" if win else "LOSS"
        try:
            storage.update_pick_result(int(pick["id"]), status, pnl)
            settled_n += 1
            detail.append({
                "match":  f"{home} vs {away}",
                "pick":   pick_val,
                "score":  f"{result['home_goals']}-{result['away_goals']}",
                "status": status,
                "pnl":    pnl,
            })
        except Exception as exc:
            logger.warning("Auto-settler: error guardando pick %s: %s", pick.get("id"), exc)
            not_found_n += 1

    return {
        "settled":   settled_n,
        "not_found": not_found_n,
        "skipped":   skipped_n,
        "results":   detail,
    }
