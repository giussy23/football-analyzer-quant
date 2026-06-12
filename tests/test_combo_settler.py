# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_combo_settler.py — Tests de la auto-liquidación de combinadas.

Ejecutar:  pytest tests/test_combo_settler.py -v
"""

from football_analyzer.core.combo_settler import (
    _leg_wins, _split_match, settle_combo, auto_settle_combos,
)


def _res(h, a):
    r = "H" if h > a else ("D" if h == a else "A")
    return {"result": r, "home_goals": h, "away_goals": a}


# ── _leg_wins (1X2 + doble oportunidad + goles) ──────────────────────────────────

class TestLegWins:
    def test_1x2(self):
        assert _leg_wins("1", _res(2, 0)) is True
        assert _leg_wins("1", _res(0, 1)) is False
        assert _leg_wins("X", _res(1, 1)) is True
        assert _leg_wins("2", _res(0, 2)) is True

    def test_double_chance(self):
        assert _leg_wins("1X", _res(1, 1)) is True     # empate cubre 1X
        assert _leg_wins("1X", _res(2, 0)) is True     # local cubre 1X
        assert _leg_wins("1X", _res(0, 1)) is False    # visitante NO
        assert _leg_wins("X2", _res(0, 2)) is True
        assert _leg_wins("12", _res(2, 0)) is True
        assert _leg_wins("12", _res(1, 1)) is False    # empate NO en 12

    def test_goals(self):
        assert _leg_wins("OVER2.5", _res(2, 1)) is True    # 3 goles
        assert _leg_wins("UNDER2.5", _res(1, 1)) is True   # 2 goles

    def test_split_match(self):
        assert _split_match("Arsenal vs Chelsea") == ("Arsenal", "Chelsea")
        assert _split_match("raro") == ("", "")


# ── settle_combo ─────────────────────────────────────────────────────────────────

def _leg(home, away, pick, res):
    return {"home_team": home, "away_team": away, "pick": pick,
            "league": "E0", "date": "2026-05-10", "_res": res}


def _fake_get(legs_by_team):
    """Devuelve un get_result que busca el marcador por nombre de equipo."""
    def _get(home, away, date, league):
        return legs_by_team.get(home)
    return _get


class TestSettleCombo:
    def test_all_win(self):
        legs = [_leg("A", "B", "1", _res(2, 0)), _leg("C", "D", "X", _res(1, 1))]
        combo = {"legs": legs}
        get = _fake_get({"A": _res(2, 0), "C": _res(1, 1)})
        assert settle_combo(combo, get_result=get) == "WIN"

    def test_one_leg_loses(self):
        legs = [_leg("A", "B", "1", None), _leg("C", "D", "X", None)]
        combo = {"legs": legs}
        get = _fake_get({"A": _res(2, 0), "C": _res(2, 0)})   # C no fue empate → falla X
        assert settle_combo(combo, get_result=get) == "LOSS"

    def test_pending_if_missing(self):
        legs = [_leg("A", "B", "1", None), _leg("C", "D", "1", None)]
        combo = {"legs": legs}
        get = _fake_get({"A": _res(2, 0)})   # falta el resultado de C
        assert settle_combo(combo, get_result=get) is None

    def test_loss_short_circuits_even_if_other_pending(self):
        # Si una pata YA perdió, la combinada pierde aunque falte otra
        legs = [_leg("A", "B", "1", None), _leg("C", "D", "1", None)]
        combo = {"legs": legs}
        get = _fake_get({"A": _res(0, 2)})   # A perdió; C aún sin dato
        assert settle_combo(combo, get_result=get) == "LOSS"

    def test_empty(self):
        assert settle_combo({"legs": []}) is None


# ── auto_settle_combos (storage falso) ──────────────────────────────────────────

class _FakeStorage:
    def __init__(self, combos):
        self._combos = combos
        self.updates = []

    def load_combos(self, limit=200):
        return self._combos

    def update_combo_by_id(self, db_id, payload):
        self.updates.append((db_id, payload["status"], payload["profit"]))


class TestAutoSettle:
    def test_settles_winning_combo(self, monkeypatch):
        import football_analyzer.core.combo_settler as cs
        # Forzar que todas las patas ganen
        monkeypatch.setattr(cs, "get_match_result", lambda h, a, d, l: _res(2, 0))
        combo = {
            "_db_id": 1, "status": "PENDING", "stake_amount": 10, "total_odds": 3.0,
            "legs": [{"home_team": "A", "away_team": "B", "pick": "1",
                      "league": "E0", "date": "2026-05-10"}],
        }
        storage = _FakeStorage([combo])
        res = cs.auto_settle_combos(storage)
        assert len(res["settled"]) == 1
        assert res["settled"][0]["outcome"] == "WIN"
        assert storage.updates[0][1] == "WIN"
        assert storage.updates[0][2] == 20.0   # 10 * (3.0 - 1)


# ── Integración con el Storage REAL (DB temporal) ────────────────────────────────
# Blinda el contrato app.save_ia_combo → save_combo → load_combos → settle → update.

class TestRealStorageRoundtrip:
    def _storage(self, tmp_path):
        from football_analyzer.core.storage import Storage
        return Storage(db_file=str(tmp_path / "test_combos.db"))

    def test_ia_combo_payload_settles_to_win(self, tmp_path, monkeypatch):
        import football_analyzer.core.combo_settler as cs
        storage = self._storage(tmp_path)

        # Payload con la forma EXACTA que produce app.save_ia_combo (campos de
        # liquidación por pata: home_team / away_team / date / league).
        payload = {
            "timestamp": "2026-05-10 12:00:00", "size": 2,
            "total_odds": 4.0, "risk": "VERDE",
            "stake_units": 1.0, "stake_amount": 5.0,
            "status": "PENDING", "profit": 0.0, "roi": 0.0,
            "source": "combinada_ia",
            "legs": [
                {"league": "E0", "match": "A vs B", "pick": "1",
                 "odds": 2.0, "home_team": "A", "away_team": "B", "date": "2026-05-10"},
                {"league": "SP1", "match": "C vs D", "pick": "1X",
                 "odds": 2.0, "home_team": "C", "away_team": "D", "date": "2026-05-10"},
            ],
        }
        storage.save_combo(payload)

        # Ambas patas ganan (local 2-0 → '1' gana y '1X' gana).
        monkeypatch.setattr(cs, "get_match_result", lambda h, a, d, l: _res(2, 0))
        res = cs.auto_settle_combos(storage)

        assert len(res["settled"]) == 1
        combos = storage.load_combos()
        assert combos[0]["status"] == "WIN"
        assert combos[0]["profit"] == 15.0          # 5 * (4.0 - 1)
        assert combos[0]["roi"] == 300.0

    def test_pending_stays_pending_without_results(self, tmp_path, monkeypatch):
        import football_analyzer.core.combo_settler as cs
        storage = self._storage(tmp_path)
        storage.save_combo({
            "timestamp": "2026-05-10 12:00:00", "size": 1, "total_odds": 2.0,
            "stake_amount": 5.0, "status": "PENDING", "profit": 0.0, "roi": 0.0,
            "legs": [{"league": "E0", "match": "A vs B", "pick": "1",
                      "home_team": "A", "away_team": "B", "date": "2026-05-10"}],
        })
        monkeypatch.setattr(cs, "get_match_result", lambda h, a, d, l: None)  # sin datos
        res = cs.auto_settle_combos(storage)
        assert res["settled"] == []
        assert storage.load_combos()[0]["status"] == "PENDING"
