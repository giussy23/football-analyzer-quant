# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_clv_tracker.py — Tests de la captura automática de CLV.

Ejecutar:  pytest tests/test_clv_tracker.py -v
"""

import math

import pandas as pd

from football_analyzer.core.clv_tracker import (
    closing_odds_for_pick, compute_clv, capture_closing_lines,
)


# ── closing_odds_for_pick ────────────────────────────────────────────────────────

class TestClosingOddsForPick:
    ROW = {"B365H": 2.10, "B365D": 3.40, "B365A": 3.60,
           "B365O25": 1.90, "B365U25": 1.95}

    def test_1x2(self):
        assert closing_odds_for_pick("1", self.ROW) == 2.10
        assert closing_odds_for_pick("X", self.ROW) == 3.40
        assert closing_odds_for_pick("2", self.ROW) == 3.60
        assert closing_odds_for_pick("H", self.ROW) == 2.10

    def test_over_under(self):
        assert closing_odds_for_pick("OVER 2.5", self.ROW) == 1.90
        assert closing_odds_for_pick("UNDER 2.5", self.ROW) == 1.95

    def test_unsupported_market(self):
        # Doble oportunidad no mapea a una sola cuota
        assert closing_odds_for_pick("1X", self.ROW) is None
        assert closing_odds_for_pick("BTTS", self.ROW) is None

    def test_missing_or_invalid_odds(self):
        assert closing_odds_for_pick("1", {"B365H": None}) is None
        assert closing_odds_for_pick("1", {"B365H": float("nan")}) is None
        assert closing_odds_for_pick("1", {"B365H": 1.0}) is None   # cuota <= 1
        assert closing_odds_for_pick("1", {}) is None


# ── compute_clv ──────────────────────────────────────────────────────────────────

class TestComputeClv:
    def test_positive_clv(self):
        # apostado 2.10, cierre 1.95 → batiste el mercado
        clv = compute_clv(2.10, 1.95)
        assert clv is not None and clv > 0
        assert math.isclose(clv, 2.10 / 1.95 - 1.0, rel_tol=1e-9)

    def test_negative_clv(self):
        # apostado 1.90, cierre 2.10 → peor precio que el cierre
        assert compute_clv(1.90, 2.10) < 0

    def test_invalid(self):
        assert compute_clv(0, 1.95) is None
        assert compute_clv(2.10, 1.0) is None
        assert compute_clv(None, 1.95) is None


# ── capture_closing_lines (integración con storage falso) ────────────────────────

class _FakeStorage:
    def __init__(self, pending):
        self._pending = pending
        self.updates = []   # (id, closing, clv)

    def load_model_picks(self, status=None, limit=200):
        if status == "PENDING":
            return [p for p in self._pending if p["status"] == "PENDING"]
        return self._pending

    def update_pick_clv(self, pick_id, closing_odds, clv):
        self.updates.append((pick_id, closing_odds, clv))


class TestCaptureClosingLines:
    def _fixtures(self):
        return pd.DataFrame([
            {"HomeTeam": "Manchester United", "AwayTeam": "Liverpool",
             "B365H": 2.00, "B365D": 3.50, "B365A": 3.80,
             "B365O25": 1.85, "B365U25": 2.00},
        ])

    def test_updates_matching_pending_pick(self):
        # Pick a "Man United" (abreviado) — debe casar con "Manchester United"
        storage = _FakeStorage([
            {"id": 1, "home_team": "Man United", "away_team": "Liverpool",
             "pick": "1", "odds": 2.20, "status": "PENDING"},
        ])
        res = capture_closing_lines(storage, self._fixtures())
        assert res["updated"] == 1
        pid, closing, clv = storage.updates[0]
        assert pid == 1
        assert closing == 2.00              # B365H del fixture
        assert clv > 0                      # 2.20 / 2.00 - 1 = +10%

    def test_no_match_no_update(self):
        storage = _FakeStorage([
            {"id": 2, "home_team": "Arsenal", "away_team": "Chelsea",
             "pick": "1", "odds": 2.20, "status": "PENDING"},
        ])
        res = capture_closing_lines(storage, self._fixtures())
        assert res["updated"] == 0
        assert storage.updates == []

    def test_empty_fixtures(self):
        storage = _FakeStorage([])
        assert capture_closing_lines(storage, pd.DataFrame())["updated"] == 0

    def test_unsupported_pick_skipped(self):
        # Doble oportunidad → no se puede capturar cuota de cierre simple
        storage = _FakeStorage([
            {"id": 3, "home_team": "Man United", "away_team": "Liverpool",
             "pick": "1X", "odds": 1.40, "status": "PENDING"},
        ])
        res = capture_closing_lines(storage, self._fixtures())
        assert res["updated"] == 0
