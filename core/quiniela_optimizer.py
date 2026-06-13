# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/quiniela_optimizer.py — Optimizador de boleto de La Quiniela (SELAE).

Para un presupuesto dado, determina qué partidos deben tener
simples / dobles / triples para maximizar P(acertar 15/15) y el Valor Esperado.

Reglas de coste:
  coste = COSTE_BASE × Π coverage_i
  coverage_i ∈ {1, 2, 3}  (partidos 1-14)
  coverage_P15 ∈ {1, 2, 3, 4}  (Pleno al 15 — 4 opciones de goles)

Algoritmo: Programación Dinámica global (DP) — v2.
  Estado  : (slot_index, combinaciones_acumuladas_como_producto)
  Objetivo: maximizar log P_pleno = Σ log(p_i(c_i))
            sujeto a Π c_i ≤ max_combinations

  La DP garantiza el óptimo global para cualquier presupuesto.
  Complejidad: O(n × max_combs × max_c) = O(15 × 64 × 4) ≈ 3840 ops.

Valor Esperado (VE):
  VE = P15 × Premio15 + P14 × Premio14 + P13 × Premio13 − coste
  Premios medios históricos SELAE configurables via parámetros.
"""

from __future__ import annotations

import math
from typing import Optional

COSTE_BASE = 0.55          # € por combinación (SELAE 2026)

# ── Premios medios históricos SELAE (configurables) ───────────────────────────
PREMIO_P15_DEFAULT =  500_000.0   # € promedio pleno 15 (varía mucho entre jornadas)
PREMIO_P14_DEFAULT =    2_000.0   # € promedio 14 aciertos
PREMIO_P13_DEFAULT =      150.0   # € promedio 13 aciertos

_LABEL_ORDER = {"1": 0, "X": 1, "2": 2, "0": 0, "M": 3}   # orden en el pick


def _sorted_pick(labels: list[str]) -> str:
    """Devuelve las etiquetas ordenadas correctamente (1 antes X, X antes 2)."""
    return "".join(sorted(labels, key=lambda x: _LABEL_ORDER.get(x, 9)))


def _normalize(ph: float, pd: float, pa: float) -> tuple[float, float, float]:
    """Normaliza probabilidades 1X2 y aplica prior si faltan datos."""
    ph, pd, pa = max(ph, 0.0), max(pd, 0.0), max(pa, 0.0)
    total = ph + pd + pa
    if total < 0.001:
        return 0.45, 0.27, 0.28   # prior histórico ligas europeas
    return ph / total, pd / total, pa / total


# ── DP global ────────────────────────────────────────────────────────────────

def _dp_optimize(all_slots: list[dict], max_combinations: int) -> list[int]:
    """
    Programación Dinámica para asignación óptima de coberturas.

    Maximiza  Σ log(p_i(c_i))  sujeto a  Π c_i ≤ max_combinations.

    Estado: {combinaciones_acumuladas: (log_p_total, [c_choices])}
    Transitions: para cada slot, probar todos los c ∈ [1, max_c].

    Retorna lista de coverage levels (uno por slot).
    """
    # Empezar con 1 combinación, log_p=0, path vacío
    dp: dict[int, tuple[float, list[int]]] = {1: (0.0, [])}

    for slot in all_slots:
        dp_new: dict[int, tuple[float, list[int]]] = {}
        ranked = slot["ranked"]
        max_c  = slot["max_c"]

        for combs, (log_p, path) in dp.items():
            for c in range(1, max_c + 1):
                new_combs = combs * c
                if new_combs > max_combinations:
                    break   # c crece monótonamente; los siguientes tampoco cabrán

                p_c    = min(sum(r[1] for r in ranked[:c]), 1.0)
                add_lp = math.log(max(p_c, 1e-12))
                total_lp = log_p + add_lp

                prev = dp_new.get(new_combs)
                if prev is None or total_lp > prev[0]:
                    dp_new[new_combs] = (total_lp, path + [c])

        if not dp_new:
            # Presupuesto tan ajustado que no caben más combinaciones
            # → rellenar el resto con simples
            remaining = len(all_slots) - len(next(iter(dp.values()))[1])
            best_log, best_path = max(dp.values(), key=lambda x: x[0])
            return best_path + [1] * remaining

        dp = dp_new

    if not dp:
        return [1] * len(all_slots)

    # Elegir el estado con máximo log_p entre todos los estados finales
    _best_log, best_path = max(dp.values(), key=lambda x: x[0])
    return best_path


# ── EV (Valor Esperado) ───────────────────────────────────────────────────────

def compute_ev(
    p_correct:   float,
    p_vec:       list[float],
    cost:        float,
    premio_p15:  float = PREMIO_P15_DEFAULT,
    premio_p14:  float = PREMIO_P14_DEFAULT,
    premio_p13:  float = PREMIO_P13_DEFAULT,
) -> float:
    """
    Calcula el Valor Esperado del boleto.

      VE = P15 × E[Premio15] + P14 × E[Premio14] + P13 × E[Premio13] − coste

    P14 y P13 se derivan de la distribución de p_vec y P15.
    """
    n = len(p_vec)
    if n == 0 or p_correct <= 0:
        return -cost

    # P14: exactamente 1 fallo
    p14 = sum(
        p_correct / max(p_vec[i], 1e-12) * (1.0 - p_vec[i])
        for i in range(n)
    )

    # P13: exactamente 2 fallos (aproximación)
    p13 = 0.0
    for i in range(n):
        pii = max(p_vec[i], 1e-12)
        for j in range(i + 1, n):
            pjj = max(p_vec[j], 1e-12)
            p13 += (p_correct / pii / pjj
                    * (1.0 - p_vec[i]) * (1.0 - p_vec[j]))

    return (p_correct * premio_p15
            + p14 * premio_p14
            + p13 * premio_p13
            - cost)


# ─────────────────────────────────────────────────────────────────────────────

def optimize_boleto(
    match_probs: list[dict],
    p15:         Optional[tuple[float, float, float, float]] = None,
    budget:      float = 0.55,
    optimize_p15: bool = False,
) -> dict:
    """
    Calcula el boleto óptimo para *budget* euros.

    Parámetros
    ----------
    match_probs : list[dict]
        14 dicts con claves ``p_home``, ``p_draw``, ``p_away``.
    p15 : tuple (p0, p1, p2, pM)
        Probabilidades del Pleno al 15 (rangos de goles).
        Si es None se usan priors.
    budget : float
        Presupuesto máximo en euros.
    optimize_p15 : bool
        Si True, el optimizador también asigna dobles/triples al P15.

    Devuelve
    --------
    dict con:
        picks        - list[str] — 15 picks (P1-P14 + P15)
        coverage     - list[int] — factor de cobertura por partido
        cost         - float — coste real en €
        combinations - int — combinaciones simples equivalentes
        p_correct    - float — P(acertar pleno 15)
        p_14         - float — P(acertar 14/15)
        p_13         - float — P(acertar 13/15) aprox.
    """
    max_combinations = max(1, int(budget / COSTE_BASE))

    # ── Construir slots para los 14 partidos ──────────────────────────────────
    slots_14: list[dict] = []
    for m in match_probs:
        ph, pd_, pa = _normalize(
            float(m.get("p_home", 0) or 0),
            float(m.get("p_draw", 0) or 0),
            float(m.get("p_away", 0) or 0),
        )
        ranked = sorted(
            [("1", ph), ("X", pd_), ("2", pa)],
            key=lambda x: -x[1],
        )
        slots_14.append({"ranked": ranked, "max_c": 3})

    # ── Slot P15 — prior LaLiga calibrado (Poisson μ≈2.75) ───────────────────
    if p15 and len(p15) == 4:
        p0, p1, p2, pm = p15
    else:
        p0, p1, p2, pm = 0.24, 0.46, 0.24, 0.06   # prior LaLiga Poisson(2.75)

    p15_ranked = sorted(
        [("0", p0), ("1", p1), ("2", p2), ("M", pm)],
        key=lambda x: -x[1],
    )
    slot_p15 = {"ranked": p15_ranked, "max_c": 4}

    # ── DP global: slots activos (incluye P15 si optimize_p15=True) ───────────
    dp_slots = slots_14 + ([slot_p15] if optimize_p15 else [])
    coverage_dp = _dp_optimize(dp_slots, max_combinations)

    # Aplicar coverage_dp a los slots
    for i, slot in enumerate(dp_slots):
        slot["c"] = coverage_dp[i] if i < len(coverage_dp) else 1
    if not optimize_p15:
        slot_p15["c"] = 1   # P15 queda como simple si no se optimiza

    # Combinaciones reales usadas
    current_combinations = 1
    for slot in dp_slots:
        current_combinations *= slot["c"]
    if not optimize_p15:
        current_combinations *= slot_p15["c"]   # siempre ×1

    # ── Construir resultado ───────────────────────────────────────────────────
    picks:    list[str]   = []
    coverage: list[int]   = []
    p_vec:    list[float] = []

    for slot in slots_14:
        labels = [r[0] for r in slot["ranked"][:slot["c"]]]
        picks.append(_sorted_pick(labels))
        coverage.append(slot["c"])
        p_vec.append(min(sum(r[1] for r in slot["ranked"][:slot["c"]]), 1.0))

    # P15 siempre al final
    p15_labels = [r[0] for r in slot_p15["ranked"][:slot_p15["c"]]]
    picks.append(_sorted_pick_p15(p15_labels))
    coverage.append(slot_p15["c"])
    p_vec.append(min(sum(r[1] for r in slot_p15["ranked"][:slot_p15["c"]]), 1.0))

    # ── Probabilidades de premio ───────────────────────────────────────────────
    p_correct = math.prod(max(v, 1e-12) for v in p_vec)

    p_14 = sum(
        p_correct / max(p_vec[i], 1e-12) * (1.0 - p_vec[i])
        for i in range(len(p_vec))
    )

    p_13 = 0.0
    for i in range(len(p_vec)):
        pii = max(p_vec[i], 1e-12)
        for j in range(i + 1, len(p_vec)):
            pjj = max(p_vec[j], 1e-12)
            p_13 += (p_correct / pii / pjj
                     * (1.0 - p_vec[i]) * (1.0 - p_vec[j]))

    # ── Valor Esperado ────────────────────────────────────────────────────────
    cost_real = round(current_combinations * COSTE_BASE, 2)
    ev = compute_ev(p_correct, p_vec, cost_real)

    return {
        "picks":        picks,
        "coverage":     coverage,
        "cost":         cost_real,
        "combinations": current_combinations,
        "p_correct":    p_correct,
        "p_14":         p_14,
        "p_13":         p_13,
        "ev":           round(ev, 4),
    }


def _sorted_pick_p15(labels: list[str]) -> str:
    """Ordena picks de P15: 0 < 1 < 2 < M."""
    order = {"0": 0, "1": 1, "2": 2, "M": 3}
    return "".join(sorted(labels, key=lambda x: order.get(x, 9)))


# ─────────────────────────────────────────────────────────────────────────────

def multi_budget(
    match_probs: list[dict],
    p15:         Optional[tuple[float, float, float, float]] = None,
    budgets:     Optional[list[float]] = None,
    optimize_p15: bool = False,
) -> list[dict]:
    """
    Devuelve el boleto óptimo para varios presupuestos.

    Útil para comparar qué se gana al subir el presupuesto.
    """
    if budgets is None:
        budgets = [0.55, 1.10, 2.20, 4.40, 8.80, 17.60, 35.20]

    results = []
    for b in budgets:
        r = optimize_boleto(match_probs, p15, b, optimize_p15)
        r["budget"] = b
        results.append(r)
    return results


def coverage_label(c: int, is_p15: bool = False) -> str:
    """Etiqueta legible del nivel de cobertura."""
    if is_p15:
        return {1: "Simple", 2: "Doble", 3: "Triple", 4: "Cuádruple"}.get(c, str(c))
    return {1: "Simple", 2: "Doble", 3: "Triple"}.get(c, str(c))
