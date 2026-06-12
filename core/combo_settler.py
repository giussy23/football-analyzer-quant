# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/combo_settler.py — Auto-liquidación de combinadas.

Una combinada gana SOLO si todas sus patas ganan; pierde en cuanto una falla.
Cada pata se resuelve con la ESPN Scores API (reutilizando core.auto_settler),
soportando 1X2, doble oportunidad (1X/X2/12) y goles (Over/Under 2.5).

  · settle_combo        → "WIN" | "LOSS" | None (pendiente)  [puro/testeable]
  · auto_settle_combos  → liquida los combos PENDING del historial

Limitación (igual que el resto): solo resuelve partidos en ligas que cubre ESPN
(_DIV_TO_ESPN). Si falta el resultado de alguna pata, el combo queda PENDIENTE.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from .auto_settler import get_match_result, pick_is_win

logger = logging.getLogger(__name__)


def _split_match(match: str) -> tuple[str, str]:
    """'Home vs Away' → (Home, Away). ('', '') si no se puede partir."""
    parts = str(match or "").split(" vs ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "", ""


# Mapa de pick → resultados ('H'/'D'/'A') que lo hacen ganador (1X2 + doble op.)
_PICK_TO_RESULTS: dict[str, set[str]] = {
    "1": {"H"}, "H": {"H"}, "HOME": {"H"},
    "X": {"D"}, "D": {"D"}, "DRAW": {"D"},
    "2": {"A"}, "A": {"A"}, "AWAY": {"A"},
    "1X": {"H", "D"}, "X1": {"H", "D"},
    "X2": {"D", "A"}, "2X": {"D", "A"},
    "12": {"H", "A"}, "21": {"H", "A"},
}


def _leg_wins(pick: str, match_result: dict) -> Optional[bool]:
    """
    True/False si la pata gana; None si el mercado no es soportado.
    Maneja 1X2 y doble oportunidad aquí; delega goles/BTTS a pick_is_win.
    """
    p = str(pick).upper().strip()
    if p in _PICK_TO_RESULTS:
        return match_result.get("result") in _PICK_TO_RESULTS[p]
    return pick_is_win(p, match_result)   # OVER/UNDER 2.5, BTTS, etc.


def settle_combo(
    combo: dict,
    get_result: Optional[Callable] = None,
    leg_eval: Optional[Callable] = None,
) -> Optional[str]:
    """
    Liquida una combinada contra los resultados reales.

    Devuelve:
      "LOSS"  en cuanto una pata resuelta falla (definitivo),
      "WIN"   si TODAS las patas están resueltas y ganan,
      None    si falta el resultado de alguna pata (reintentar luego).
    """
    # Resolver en tiempo de llamada (permite testear y monkeypatch del módulo)
    if get_result is None:
        get_result = get_match_result
    if leg_eval is None:
        leg_eval = _leg_wins

    legs = combo.get("legs", []) or []
    if not legs:
        return None

    pending = False
    for leg in legs:
        home = str(leg.get("home_team") or _split_match(leg.get("match", ""))[0])
        away = str(leg.get("away_team") or _split_match(leg.get("match", ""))[1])
        pick = str(leg.get("pick", ""))
        league = str(leg.get("league", "") or "")
        date = str(leg.get("date", "") or "")
        if not home or not away or not date:
            pending = True
            continue
        result = get_result(home, away, date, league)
        if result is None:
            pending = True
            continue
        win = leg_eval(pick, result)
        if win is None:
            pending = True          # mercado no soportado → liquidación manual
            continue
        if not win:
            return "LOSS"           # una pata perdida → combinada perdida
    return None if pending else "WIN"


def auto_settle_combos(storage) -> dict:
    """
    Liquida automáticamente las combinadas PENDING cuyas patas ya tengan resultado.

    Returns {"settled": [ {n_legs, odds, outcome, profit}, ... ]}
    """
    try:
        combos = storage.load_combos(limit=200)
    except Exception as exc:
        logger.debug("Combo settler: no se cargaron combinadas: %s", exc)
        return {"settled": []}

    pending = [
        c for c in combos
        if (c.get("status") or "PENDING") == "PENDING" and c.get("legs")
    ]
    if not pending:
        return {"settled": []}

    settled: list[dict] = []
    for c in pending:
        outcome = settle_combo(c)
        if outcome is None:
            continue
        stake = float(c.get("stake_amount", 0) or 0)
        odds  = float(c.get("total_odds", 0) or 0)
        profit = round(stake * (odds - 1), 2) if outcome == "WIN" else round(-stake, 2)
        roi    = round((profit / stake) * 100, 2) if stake else 0.0
        c.update({
            "status":     outcome,
            "profit":     profit,
            "roi":        roi,
            "settled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        try:
            storage.update_combo_by_id(c["_db_id"], c)
            settled.append({"n_legs": len(c.get("legs", [])), "odds": odds,
                            "outcome": outcome, "profit": profit})
            logger.info("Combinada #%s liquidada: %s (cuota %.2f)",
                        c.get("_db_id"), outcome, odds)
        except Exception as exc:
            logger.warning("Combo settler: error guardando combo %s: %s",
                           c.get("_db_id"), exc)

    return {"settled": settled}
