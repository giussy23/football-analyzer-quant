# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_settler.py — Tests de la liquidación automática de picks.

Cubre las dos funciones puras de core/auto_settler.py:
  · pick_is_win   — evaluación de cada mercado (1X2, Over/Under, BTTS)
  · _team_match   — emparejamiento de nombres de equipo

Estos tests habrían cazado el bug de _team_match (prefijo de 5 chars) que
confundía "Real Madrid" con "Real Sociedad" y liquidaba el pick equivocado.

Ejecutar:  pytest tests/test_settler.py -v
"""

import pytest

from football_analyzer.core.auto_settler import pick_is_win, _team_match


def _res(h: int, a: int) -> dict:
    """Construye un match_result con el campo 'result' derivado del marcador."""
    result = "H" if h > a else ("D" if h == a else "A")
    return {"result": result, "home_goals": h, "away_goals": a}


# ── pick_is_win ─────────────────────────────────────────────────────────────────

class TestPickIsWin:
    def test_home(self):
        assert pick_is_win("H", _res(2, 0)) is True
        assert pick_is_win("HOME", _res(2, 0)) is True
        assert pick_is_win("H", _res(0, 2)) is False
        assert pick_is_win("H", _res(1, 1)) is False

    def test_draw(self):
        assert pick_is_win("X", _res(1, 1)) is True
        assert pick_is_win("D", _res(0, 0)) is True
        assert pick_is_win("DRAW", _res(2, 2)) is True
        assert pick_is_win("X", _res(2, 1)) is False

    def test_away(self):
        assert pick_is_win("A", _res(0, 2)) is True
        assert pick_is_win("AWAY", _res(1, 3)) is True
        assert pick_is_win("A", _res(2, 0)) is False

    def test_over_under_2_5(self):
        # 3 goles → OVER gana, UNDER pierde
        assert pick_is_win("OVER 2.5", _res(2, 1)) is True
        assert pick_is_win("UNDER 2.5", _res(2, 1)) is False
        # 2 goles → UNDER gana, OVER pierde (no hay empate en 2.5)
        assert pick_is_win("OVER 2.5", _res(1, 1)) is False
        assert pick_is_win("UNDER 2.5", _res(1, 1)) is True
        # 0 goles
        assert pick_is_win("UNDER 2.5", _res(0, 0)) is True

    def test_btts(self):
        assert pick_is_win("BTTS", _res(1, 1)) is True
        assert pick_is_win("BTTS", _res(2, 3)) is True
        assert pick_is_win("BTTS", _res(1, 0)) is False
        assert pick_is_win("NO BTTS", _res(1, 0)) is True
        assert pick_is_win("NO BTTS", _res(2, 2)) is False

    def test_unknown_market_returns_none(self):
        # Mercado no soportado → None (el settler lo salta, no lo liquida mal)
        assert pick_is_win("HANDICAP -1", _res(2, 0)) is None
        assert pick_is_win("", _res(1, 0)) is None


# ── _team_match ─────────────────────────────────────────────────────────────────

class TestTeamMatch:
    @pytest.mark.parametrize("query,candidate", [
        ("Man United",      "Manchester United"),
        ("Man City",        "Manchester City"),
        ("Tottenham",       "Tottenham Hotspur"),
        ("Arsenal",         "Arsenal FC"),
        ("Real Madrid",     "Real Madrid CF"),
        ("Atletico Madrid", "Atlético Madrid"),   # tolera acentos
        ("Barcelona",       "FC Barcelona"),
        ("Wolves",          "Wolves"),
    ])
    def test_should_match(self, query, candidate):
        assert _team_match(query, candidate) is True

    @pytest.mark.parametrize("query,candidate", [
        ("Real Madrid",      "Real Sociedad"),     # el bug original
        ("Real Madrid",      "Real Betis"),
        ("Real Sociedad",    "Real Betis"),
        ("Manchester United","Manchester City"),
        ("Athletic Bilbao",  "Atletico Madrid"),
        ("Sheffield United", "Sheffield Wednesday"),
        ("West Ham",         "West Brom"),
    ])
    def test_should_not_match(self, query, candidate):
        assert _team_match(query, candidate) is False

    def test_empty_names(self):
        assert _team_match("", "Arsenal") is False
        assert _team_match("Arsenal", "") is False
