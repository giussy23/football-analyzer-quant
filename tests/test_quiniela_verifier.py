# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_quiniela_verifier.py — Tests de la verificación de boletos.

Ejecutar:  pytest tests/test_quiniela_verifier.py -v
"""

from football_analyzer.core.quiniela_verifier import (
    _result_char, _pick_covers, candidate_dates, categoria,
    result_for_match, verify_boleto, format_telegram,
)


def _p(home, away, pick):
    return {"home": home, "away": away, "pick": pick}


def _idx(home, away, result):
    return {"home": home, "away": away, "result": result}


def _make(picks, results):
    """Construye (partidos, index) con equipos distintos por índice.
    Nombres de longitud fija (Home00, Home01…) para que ninguno sea prefijo de
    otro y no colisionen en el emparejamiento por tokens."""
    partidos = [_p(f"Home{i:02d}", f"Away{i:02d}", picks[i]) for i in range(len(picks))]
    index    = [_idx(f"Home{i:02d}", f"Away{i:02d}", results[i]) for i in range(len(results))]
    return partidos, index


# ── Helpers puros ────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_result_char(self):
        assert _result_char(2, 0) == "1"
        assert _result_char(1, 1) == "X"
        assert _result_char(0, 3) == "2"

    def test_pick_covers(self):
        assert _pick_covers("1", "1")
        assert _pick_covers("1X", "X")        # doble cubre
        assert _pick_covers("1X2", "2")       # triple cubre todo
        assert not _pick_covers("1", "X")
        assert not _pick_covers("2", "1")
        assert not _pick_covers("1X", "2")
        assert not _pick_covers("1", "")      # sin resultado

    def test_candidate_dates(self):
        d = candidate_dates("2026-05-10", before=1, after=2)
        assert d == ["20260509", "20260510", "20260511", "20260512"]
        assert candidate_dates("texto inválido") == []

    def test_categoria(self):
        assert categoria(14, 1) == "1ª (¡Pleno!)"     # 15 aciertos
        assert categoria(14, 0) == "3ª"
        assert categoria(13, 0) == "4ª"
        assert categoria(12, 0) == "Sin premio (12/14)"
        assert categoria(8, 0) == "Sin premio (8/14)"


# ── result_for_match (emparejamiento por tokens) ─────────────────────────────────

class TestResultForMatch:
    def test_exact(self):
        idx = [_idx("Real Madrid", "Sevilla", "1")]
        assert result_for_match("Real Madrid", "Sevilla", idx) == "1"

    def test_abbreviation(self):
        # nombre abreviado del boleto vs nombre completo de ESPN
        idx = [_idx("Manchester United", "Liverpool", "X")]
        assert result_for_match("Man United", "Liverpool", idx) == "X"

    def test_not_found(self):
        idx = [_idx("Real Madrid", "Sevilla", "1")]
        assert result_for_match("Arsenal", "Chelsea", idx) is None

    def test_homonyms_not_confused(self):
        # Real Madrid no debe casar con Real Sociedad
        idx = [_idx("Real Sociedad", "Getafe", "2")]
        assert result_for_match("Real Madrid", "Getafe", idx) is None


# ── verify_boleto ────────────────────────────────────────────────────────────────

class TestVerifyBoleto:
    def test_pleno(self):
        # 15 aciertos: todos "1" y resultados "1"
        partidos, index = _make(["1"] * 15, ["1"] * 15)
        res = verify_boleto({"partidos": partidos}, index)
        assert res["aciertos"] == 15
        assert res["aciertos_14"] == 14
        assert res["pleno"] == 1
        assert res["categoria"] == "1ª (¡Pleno!)"

    def test_thirteen_plus_pleno(self):
        # 13 de 14 + pleno: el partido 13 falla
        picks   = ["1"] * 15
        results = ["1"] * 13 + ["2"] + ["1"]    # idx 13 → "2" (fallo), pleno ok
        partidos, index = _make(picks, results)
        res = verify_boleto({"partidos": partidos}, index)
        assert res["aciertos_14"] == 13
        assert res["pleno"] == 1
        assert res["aciertos"] == 14
        assert res["categoria"] == "4ª"

    def test_double_pick_counts(self):
        # pick doble "1X" acierta si sale "X"
        picks   = ["1X"] + ["1"] * 14
        results = ["X"]  + ["1"] * 14
        partidos, index = _make(picks, results)
        res = verify_boleto({"partidos": partidos}, index)
        assert res["aciertos_14"] == 14          # el doble cubre la X

    def test_missing_result_returns_none(self):
        partidos, index = _make(["1"] * 15, ["1"] * 15)
        index = index[:-3]                        # faltan 3 resultados
        assert verify_boleto({"partidos": partidos}, index) is None

    def test_too_few_matches(self):
        partidos, index = _make(["1"] * 10, ["1"] * 10)
        assert verify_boleto({"partidos": partidos}, index) is None


# ── format_telegram ──────────────────────────────────────────────────────────────

class TestFormatTelegram:
    def test_message(self):
        msg = format_telegram([
            {"jornada": "42", "aciertos": 14, "categoria": "3ª"},
            {"jornada": "43", "aciertos": 9,  "categoria": "Sin premio (9/14)"},
        ])
        assert "Jornada 42" in msg
        assert "14/15" in msg
        assert "🏆" in msg          # 14 aciertos → trofeo
