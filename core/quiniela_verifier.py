# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/quiniela_verifier.py — Verificación automática de boletos de quiniela.

Hasta ahora los boletos se verificaban a mano (el usuario introducía los 15
resultados). Este módulo lo hace solo: obtiene los resultados reales de cada
partido vía la ESPN Scores API (reutilizando core.auto_settler, sin API key) y
calcula los aciertos y la categoría, igual que el diálogo manual.

  · build_results_index  — descarga los marcadores de la jornada (I/O).
  · verify_boleto        — cuenta aciertos de un boleto contra el índice (puro).
  · auto_verify_quinielas— recorre los boletos PENDIENTES y los liquida.

Limitación: ESPN cubre las ligas de _DIV_TO_ESPN (5 grandes + Segunda,
Championship, 2.Bundesliga, Eredivisie, Primeira). Partidos de otras ligas no
se resuelven solos y el boleto queda PENDIENTE para verificación manual.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from .auto_settler import _DIV_TO_ESPN, _ESPN_BASE, _get, _team_match

logger = logging.getLogger(__name__)


# ── Helpers puros ────────────────────────────────────────────────────────────────

def _result_char(hg: int, ag: int) -> str:
    """Marcador → signo de quiniela."""
    return "1" if hg > ag else ("X" if hg == ag else "2")


def _pick_covers(pick: str, real: str) -> bool:
    """True si el resultado real está cubierto por el pick (incluye dobles/triples).
    '1X' cubre '1' y 'X'; '1X2' cubre todo. (Misma regla que el diálogo manual.)"""
    return bool(real) and real in (pick or "")


def _parse_date(s: str) -> Optional[datetime]:
    s = (str(s) or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def candidate_dates(base: str, before: int = 1, after: int = 4) -> list[str]:
    """Ventana de fechas (YYYYMMDD) alrededor de la fecha base — cubre el fin de
    semana de la jornada (vie→lun)."""
    d = _parse_date(base)
    if d is None:
        return []
    return [(d + timedelta(days=k)).strftime("%Y%m%d")
            for k in range(-before, after + 1)]


def categoria(aciertos_14: int, pleno: int) -> str:
    """Categoría de premio (idéntica a la del diálogo manual de la vista)."""
    total = aciertos_14 + pleno
    if total == 15:
        return "1ª (¡Pleno!)"
    if aciertos_14 == 14 and pleno == 1:
        return "2ª"
    if aciertos_14 == 14:
        return "3ª"
    if aciertos_14 == 13:
        return "4ª"
    if aciertos_14 == 12:
        return "Sin premio (12/14)"
    return f"Sin premio ({aciertos_14}/14)"


def result_for_match(home: str, away: str, index: list[dict]) -> Optional[str]:
    """Busca en el índice el signo (1/X/2) del partido home-away. None si no está."""
    for m in index:
        if _team_match(home, m.get("home", "")) and _team_match(away, m.get("away", "")):
            return m.get("result")
    return None


def verify_boleto(boleto: dict, index: list[dict]) -> Optional[dict]:
    """
    Cuenta aciertos de un boleto contra el índice de resultados.

    Devuelve None si falta el resultado de algún partido (el boleto se queda
    PENDIENTE y se reintenta en el siguiente ciclo). Si están todos:
      {aciertos, aciertos_14, pleno, categoria, resultados}
    """
    partidos = boleto.get("partidos", []) or []
    if len(partidos) < 14:
        return None

    resultados: list[str] = []
    for p in partidos:
        r = result_for_match(str(p.get("home", "")), str(p.get("away", "")), index)
        if r is None:
            return None        # aún falta algún resultado → no verificar
        resultados.append(r)

    aciertos_14 = sum(
        1 for i in range(14)
        if _pick_covers(partidos[i].get("pick", ""), resultados[i])
    )
    pleno = 0
    if len(partidos) >= 15:
        pleno = 1 if resultados[14] == partidos[14].get("pick", "") else 0

    return {
        "aciertos":    aciertos_14 + pleno,
        "aciertos_14": aciertos_14,
        "pleno":       pleno,
        "categoria":   categoria(aciertos_14, pleno),
        "resultados":  resultados,
    }


# ── I/O: índice de resultados desde ESPN ─────────────────────────────────────────

def build_results_index(dates: list[str], leagues: Optional[list[str]] = None) -> list[dict]:
    """
    Descarga los marcadores ESPN para las fechas/ligas dadas y devuelve los
    partidos COMPLETADOS: [{home, away, result}].
    """
    espn_leagues = (
        [_DIV_TO_ESPN[k] for k in leagues if k in _DIV_TO_ESPN]
        if leagues else list(_DIV_TO_ESPN.values())
    )
    index: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for league in espn_leagues:
        for d in dates:
            if (league, d) in seen:
                continue
            seen.add((league, d))
            data = _get(f"{_ESPN_BASE}/{league}/scoreboard", {"dates": d})
            for event in data.get("events", []):
                comps = event.get("competitions", [])
                if not comps:
                    continue
                comp = comps[0]
                if not comp.get("status", {}).get("type", {}).get("completed", False):
                    continue
                cs = comp.get("competitors", [])
                home_c = next((c for c in cs if c.get("homeAway") == "home"), None)
                away_c = next((c for c in cs if c.get("homeAway") == "away"), None)
                if not home_c or not away_c:
                    continue
                try:
                    hg = int(home_c.get("score", ""))
                    ag = int(away_c.get("score", ""))
                except (ValueError, TypeError):
                    continue
                index.append({
                    "home":   home_c.get("team", {}).get("displayName", ""),
                    "away":   away_c.get("team", {}).get("displayName", ""),
                    "result": _result_char(hg, ag),
                })
    return index


def auto_verify_quinielas(storage) -> dict:
    """
    Verifica todos los boletos PENDIENTES cuyos partidos ya tengan resultado.

    Returns {"verified": [ {jornada, aciertos, categoria, ...}, ... ]}
    """
    try:
        boletos = storage.load_quinielas(limit=50)
    except Exception as exc:
        logger.debug("Quiniela verifier: no se cargaron boletos: %s", exc)
        return {"verified": []}

    pending = [
        b for b in boletos
        if (b.get("status") or "PENDIENTE") == "PENDIENTE" and b.get("partidos")
    ]
    if not pending:
        return {"verified": []}

    # Ventana de fechas a partir de la fecha de cada jornada (o el saved_at)
    dates: set[str] = set()
    for b in pending:
        for d in candidate_dates(b.get("fecha") or b.get("saved_at", "")):
            dates.add(d)
    if not dates:
        return {"verified": []}

    index = build_results_index(sorted(dates))
    if not index:
        return {"verified": []}

    verified: list[dict] = []
    for b in pending:
        res = verify_boleto(b, index)
        if res is None:
            continue
        try:
            storage.update_quiniela_result(
                b["_db_id"], res["aciertos"], res["categoria"], res["resultados"],
            )
            verified.append({"jornada": b.get("jornada", "?"), **res})
            logger.info("Quiniela J%s verificada: %d/15 (%s)",
                        b.get("jornada", "?"), res["aciertos"], res["categoria"])
        except Exception as exc:
            logger.warning("Quiniela verifier: error guardando boleto %s: %s",
                           b.get("_db_id"), exc)

    return {"verified": verified}


def format_telegram(verified: list[dict]) -> str:
    """Mensaje de texto plano para Telegram con los boletos verificados."""
    lines = ["🎟️ Quinielas verificadas automáticamente", ""]
    for v in verified:
        ac = v.get("aciertos", 0)
        emoji = "🏆" if ac >= 13 else ("✅" if ac >= 10 else "▫️")
        lines.append(f"{emoji} Jornada {v.get('jornada', '?')}: "
                     f"{ac}/15 — {v.get('categoria', '')}")
    return "\n".join(lines)
