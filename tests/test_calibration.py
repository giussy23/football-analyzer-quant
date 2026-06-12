# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_calibration.py — Tests de la calibración del modelo.

Ejecutar:  pytest tests/test_calibration.py -v
"""

from football_analyzer.core.calibration import compute_calibration, calibration_grade


def _pick(prob, status):
    return {"model_prob": prob, "status": status}


class TestComputeCalibration:
    def test_empty(self):
        out = compute_calibration([])
        assert out["bins"] == []
        assert out["brier"] is None
        assert out["n"] == 0

    def test_perfect_calibration_brier_zero(self):
        # Predicciones 1.0 que ganan y 0.0 que pierden → Brier 0
        picks = [_pick(1.0, "WIN"), _pick(0.0, "LOSS"), _pick(1.0, "WIN")]
        out = compute_calibration(picks)
        assert out["brier"] == 0.0

    def test_coin_flip_brier(self):
        # prob 0.5 siempre → Brier = 0.25 independientemente del resultado
        picks = [_pick(0.5, "WIN"), _pick(0.5, "LOSS")]
        out = compute_calibration(picks)
        assert abs(out["brier"] - 0.25) < 1e-9

    def test_bins_aggregate_correctly(self):
        # Cuatro picks al 60%: 3 WIN, 1 LOSS → un bin con pred≈0.6, obs=0.75
        picks = [_pick(0.6, "WIN"), _pick(0.6, "WIN"),
                 _pick(0.6, "WIN"), _pick(0.6, "LOSS")]
        out = compute_calibration(picks, n_bins=10)
        # Todos caen en el bin [0.6, 0.7)
        assert len(out["bins"]) == 1
        b = out["bins"][0]
        assert abs(b["pred"] - 0.6) < 1e-9
        assert abs(b["obs"] - 0.75) < 1e-9
        assert b["count"] == 4

    def test_ignores_invalid(self):
        picks = [
            _pick(None, "WIN"),         # sin prob
            _pick(0.6, "PENDING"),      # no liquidado
            _pick("abc", "WIN"),        # prob no numérica
            _pick(1.5, "WIN"),          # fuera de rango
            _pick(0.7, "WIN"),          # válido
        ]
        out = compute_calibration(picks)
        assert out["n"] == 1

    def test_edge_prob_one_lands_in_last_bin(self):
        # prob exactamente 1.0 debe entrar en el último bin, no descartarse
        out = compute_calibration([_pick(1.0, "WIN")], n_bins=10)
        assert out["n"] == 1
        assert len(out["bins"]) == 1


class TestCalibrationGrade:
    def test_grades(self):
        assert calibration_grade(None) == "—"
        assert calibration_grade(0.15) == "Excelente"
        assert calibration_grade(0.20) == "Buena"
        assert calibration_grade(0.24) == "Aceptable"
        assert calibration_grade(0.30) == "Pobre"
