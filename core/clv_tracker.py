# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/clv_tracker.py — Captura automática del Closing Line Value (CLV).

El CLV mide cuánto batiste al mercado: comparar la cuota a la que apostaste
con la cuota de CIERRE (justo antes del kickoff). Si apostaste a 2.10 y cerró
a 1.95, tu CLV = 2.10/1.95 − 1 = +7.7% → conseguiste un precio mejor que el
mercado. Un CLV medio positivo es la mejor señal de que tienes edge real,
independiente de la suerte a corto plazo.

Hasta ahora el CLV se introducía a mano. Este módulo lo captura solo: cada vez
que se descargan cuotas frescas (The Odds API), actualiza la cuota de cierre de
los picks PENDIENTES cuyo partido sigue por jugarse. Como se sobrescribe en cada
pasada, el último valor antes del kickoff queda como la cuota de cierre real.

Funciones puras (closing_odds_for_pick, compute_clv) → testeables sin red ni BD.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)


# Mapa selección del pick → columna de cuota en el DataFrame de The Odds API
_PICK_TO_COL: dict[str, str] = {
    "1": "B365H", "H": "B365H", "HOME": "B365H",
    "X": "B365D", "D": "B365D", "DRAW": "B365D",
    "2": "B365A", "A": "B365A", "AWAY": "B365A",
    "OVER 2.5": "B365O25", "OVER2.5": "B365O25", "OVER": "B365O25",
    "UNDER 2.5": "B365U25", "UNDER2.5": "B365U25", "UNDER": "B365U25",
}


def closing_odds_for_pick(pick: str, row: dict) -> Optional[float]:
    """
    Cuota de cierre para la selección del pick dentro de una fila de fixtures.

    Devuelve None si el mercado no es soportado (p.ej. dobles oportunidad) o la
    cuota falta / es inválida (≤ 1.0).
    """
    col = _PICK_TO_COL.get(str(pick).upper().strip())
    if col is None:
        return None
    val = row.get(col)
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or v <= 1.0:
        return None
    return v


def compute_clv(pick_odds: float, closing_odds: float) -> Optional[float]:
    """CLV = cuota_apostada / cuota_cierre − 1. None si alguna cuota es inválida."""
    try:
        po, co = float(pick_odds), float(closing_odds)
    except (TypeError, ValueError):
        return None
    if po <= 1.0 or co <= 1.0:
        return None
    return po / co - 1.0


def _row_team(row: dict, *keys: str) -> str:
    """Lee el nombre de equipo probando varias claves (HomeTeam / home_team)."""
    for k in keys:
        v = row.get(k)
        if v:
            return str(v)
    return ""


def capture_closing_lines(storage, fixtures_df) -> dict:
    """
    Actualiza la cuota de cierre y el CLV de los picks PENDIENTES que aparezcan
    en las cuotas frescas (partido aún por jugarse).

    Parámetros
    ----------
    storage      : instancia de Storage (usa update_pick_clv).
    fixtures_df  : DataFrame de fetch_odds_fixtures (HomeTeam/AwayTeam + B365*).

    Returns {"updated": n, "checked": m}
    """
    if fixtures_df is None or getattr(fixtures_df, "empty", True):
        return {"updated": 0, "checked": 0}

    # Reutiliza el emparejamiento por tokens del settler (robusto a abreviaturas)
    from .auto_settler import _team_match

    rows = fixtures_df.to_dict("records")
    try:
        pending = storage.load_model_picks(status="PENDING", limit=200)
    except Exception as exc:
        logger.debug("CLV: no se pudieron cargar picks pendientes: %s", exc)
        return {"updated": 0, "checked": 0}

    updated = 0
    for pick in pending:
        home = str(pick.get("home_team", "") or "")
        away = str(pick.get("away_team", "") or "")
        try:
            pick_odds = float(pick.get("odds") or 0)
        except (TypeError, ValueError):
            continue
        if not home or not away or pick_odds <= 1.0:
            continue

        match_row = next(
            (r for r in rows
             if _team_match(home, _row_team(r, "HomeTeam", "home_team"))
             and _team_match(away, _row_team(r, "AwayTeam", "away_team"))),
            None,
        )
        if match_row is None:
            continue

        closing = closing_odds_for_pick(pick.get("pick", ""), match_row)
        if closing is None:
            continue
        clv = compute_clv(pick_odds, closing)
        if clv is None:
            continue

        try:
            storage.update_pick_clv(int(pick["id"]), round(closing, 3), round(clv, 4))
            updated += 1
        except Exception as exc:
            logger.debug("CLV: error actualizando pick %s: %s", pick.get("id"), exc)

    if updated:
        logger.info("CLV automático: %d pick(s) actualizados con cuota de cierre", updated)
    return {"updated": updated, "checked": len(pending)}
