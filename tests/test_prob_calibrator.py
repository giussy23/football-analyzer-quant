# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
tests/test_prob_calibrator.py — Tests de la corrección de calibración.

Ejecutar:  pytest tests/test_prob_calibrator.py -v
"""

from football_analyzer.core.prob_calibrator import ProbCalibrator, fit_from_picks


def _dataset(spec):
    """spec: lista de (prob, n, wins) → (probs, outcomes)."""
    probs, outs = [], []
    for prob, n, wins in spec:
        probs += [prob] * n
        outs  += [1] * wins + [0] * (n - wins)
    return probs, outs


class TestNotFitted:
    def test_identity_below_min_samples(self):
        cal = ProbCalibrator().fit([0.6, 0.8], [1, 0], min_samples=50)
        assert not cal.is_fitted
        assert cal.transform(0.8) == 0.8          # identidad
        assert cal.transform(0.5) == 0.5

    def test_empty(self):
        cal = ProbCalibrator().fit([], [])
        assert not cal.is_fitted
        assert cal.transform(0.7) == 0.7


class TestOverconfidentModel:
    def _cal(self):
        # Modelo optimista: dice 0.6 pero gana 0.4; dice 0.8 pero gana 0.6
        probs, outs = _dataset([(0.6, 50, 20), (0.8, 50, 30)])
        return ProbCalibrator().fit(probs, outs, min_samples=50)

    def test_fitted(self):
        assert self._cal().is_fitted

    def test_corrects_downward(self):
        cal = self._cal()
        # con corrección plena, 0.8 debe bajar hacia ~0.6
        assert cal.transform(0.8, blend=1.0) < 0.8
        assert cal.transform(0.6, blend=1.0) < 0.6

    def test_blend_is_conservative(self):
        cal = self._cal()
        full = cal.transform(0.8, blend=1.0)
        half = cal.transform(0.8, blend=0.5)
        # el blend a la mitad queda ENTRE la cruda (0.8) y la corrección plena
        assert full < half < 0.8


class TestWellCalibratedModel:
    def test_near_identity(self):
        # Modelo bien calibrado: 0.6→0.6, 0.8→0.8
        probs, outs = _dataset([(0.6, 50, 30), (0.8, 50, 40)])
        cal = ProbCalibrator().fit(probs, outs, min_samples=50)
        assert cal.is_fitted
        # un punto intermedio debe quedar muy cerca de su valor (bien calibrado)
        assert abs(cal.transform(0.7, blend=1.0) - 0.7) < 0.06


class TestSafety:
    def _cal(self):
        probs, outs = _dataset([(0.6, 50, 20), (0.8, 50, 30)])
        return ProbCalibrator().fit(probs, outs, min_samples=50)

    def test_output_bounded(self):
        cal = self._cal()
        for p in (0.0, 0.01, 0.5, 0.99, 1.0):
            out = cal.transform(p, blend=1.0)
            assert 0.01 <= out <= 0.99

    def test_invalid_input_passthrough(self):
        cal = self._cal()
        assert cal.transform("abc") == "abc"       # no numérico → tal cual
        assert cal.transform(1.5) == 1.5           # fuera de rango → identidad


class TestFitFromPicks:
    def test_builds_and_fits(self):
        picks = []
        for _ in range(50):
            picks.append({"model_prob": 0.6, "status": "LOSS"})
        for _ in range(50):
            picks.append({"model_prob": 0.8, "status": "WIN"})
        cal = fit_from_picks(picks, min_samples=50)
        assert cal.is_fitted
        assert cal.n_samples == 100

    def test_ignores_pending_and_invalid(self):
        picks = [
            {"model_prob": 0.6, "status": "PENDING"},
            {"model_prob": None, "status": "WIN"},
            {"model_prob": 0.7, "status": "WIN"},
        ]
        cal = fit_from_picks(picks, min_samples=1)
        assert cal.n_samples == 1
