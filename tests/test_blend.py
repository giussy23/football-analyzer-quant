# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
"""Tests del blend modelo+mercado (pooling geométrico)."""
import pytest

from football_analyzer.core.analyzer import blend_prob_binary, blend_probs_1x2


def test_w0_devuelve_mercado():
    model, market = (0.70, 0.20, 0.10), (0.45, 0.30, 0.25)
    out = blend_probs_1x2(model, market, 0.0)
    assert out == pytest.approx(market, abs=1e-9)


def test_w1_devuelve_modelo():
    model, market = (0.70, 0.20, 0.10), (0.45, 0.30, 0.25)
    out = blend_probs_1x2(model, market, 1.0)
    assert out == pytest.approx(model, abs=1e-9)


def test_blend_normalizado_y_entre_ambos():
    model, market = (0.70, 0.20, 0.10), (0.45, 0.30, 0.25)
    out = blend_probs_1x2(model, market, 0.35)
    assert sum(out) == pytest.approx(1.0, abs=1e-9)
    # Cada componente queda entre el valor del modelo y el del mercado
    # (propiedad del pooling geométrico tras normalizar, para este caso)
    assert market[0] < out[0] < model[0]
    assert model[1] < out[1] < market[1]


def test_blend_encoge_el_edge():
    """El edge tras el blend debe ser menor en magnitud y conservar el signo."""
    model, market = (0.55, 0.25, 0.20), (0.45, 0.30, 0.25)
    out = blend_probs_1x2(model, market, 0.35)
    edge_raw   = model[0] - market[0]
    edge_blend = out[0] - market[0]
    assert 0 < edge_blend < edge_raw
    # Aproximadamente w·edge_raw (pooling geométrico ≈ lineal en diffs pequeñas)
    assert edge_blend == pytest.approx(0.35 * edge_raw, rel=0.30)


def test_binary_extremos_y_simetria():
    assert blend_prob_binary(0.6, 0.5, 0.0) == pytest.approx(0.5)
    assert blend_prob_binary(0.6, 0.5, 1.0) == pytest.approx(0.6)
    mid = blend_prob_binary(0.6, 0.5, 0.35)
    assert 0.5 < mid < 0.6
    # Complementariedad: blend(p) + blend(1-p con mercado 1-q) = 1
    assert blend_prob_binary(0.4, 0.5, 0.35) == pytest.approx(1.0 - mid, abs=1e-9)


def test_probabilidades_extremas_no_rompen():
    out = blend_probs_1x2((1.0, 0.0, 0.0), (0.45, 0.30, 0.25), 0.35)
    assert sum(out) == pytest.approx(1.0, abs=1e-9)
    assert all(0.0 <= p <= 1.0 for p in out)
