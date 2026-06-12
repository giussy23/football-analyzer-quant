# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
"""Tests del caché persistente de respuestas IA (ai_cache en SQLite)."""
import pytest

from football_analyzer.core.storage import Storage


@pytest.fixture
def store(tmp_path):
    return Storage(db_file=str(tmp_path / "test_ai_cache.db"))


def test_set_y_get(store):
    store.set_ai_cache("enrich|A|B", '{"x": 1}')
    assert store.get_ai_cache("enrich|A|B") == '{"x": 1}'


def test_miss_devuelve_none(store):
    assert store.get_ai_cache("no-existe") is None


def test_caducidad_por_ttl(store):
    store.set_ai_cache("k", "viejo")
    with store._connect() as con:
        con.execute(
            "UPDATE ai_cache SET updated_at = datetime('now', '-13 hours') "
            "WHERE cache_key = 'k'"
        )
        con.commit()
    assert store.get_ai_cache("k", max_age_hours=12.0) is None
    assert store.get_ai_cache("k", max_age_hours=24.0) == "viejo"


def test_reemplazo_actualiza_payload(store):
    store.set_ai_cache("k", "v1")
    store.set_ai_cache("k", "v2")
    assert store.get_ai_cache("k") == "v2"


def test_enricher_usa_cache_persistente(store, monkeypatch):
    """El enricher debe leer del caché BD sin llamar a la API."""
    from football_analyzer.core.claude_enricher import (
        ClaudeFeatureEnricher, _CLAUDE_FEATURES,
    )

    payload = {k: 0.7 for k in _CLAUDE_FEATURES}
    import json
    store.set_ai_cache("enrich|Local|Visitante", json.dumps(payload))

    enricher = ClaudeFeatureEnricher("sk-ant-test", storage=store)

    def _no_llamar(*a, **kw):
        raise AssertionError("no debería llamar a la API: hay caché")

    monkeypatch.setattr(enricher, "_call_api", _no_llamar)
    result = enricher.enrich("Local", "Visitante")
    assert result == payload
    assert enricher.n_cached == 1
    assert enricher.n_calls == 0
