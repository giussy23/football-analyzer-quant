# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/injuries.py — Datos de lesiones en tiempo real via API-Football (api-sports.io).

Plan gratuito: 100 peticiones/día — suficiente para ~20 fixtures por análisis.
Registro gratuito en: dashboard.api-football.com

Flujo:
  1. team_name + league_code → team_id   (GET /teams, 1 llamada, cacheada por nombre)
  2. team_id + season         → injuries  (GET /injuries, 1 llamada, cacheada 24h)
  3. injuries                 → impact [0.0–1.0]  (cálculo local)

El impacto se convierte a los campos f_claude_injury_home/away que el ClaudeEnricher
ya sabe ajustar sobre las probabilidades ML.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Mapeo div (football-data.co.uk) → (league_id API-Football, season) ────────

def _current_season() -> int:
    """Temporada en curso según el calendario europeo (empieza en agosto)."""
    now = datetime.now()
    return now.year if now.month >= 8 else now.year - 1


_DIV_TO_AFL: dict[str, int] = {
    "E0":  39,    # Premier League
    "SP1": 140,   # La Liga
    "I1":  135,   # Serie A
    "D1":  78,    # Bundesliga
    "F1":  61,    # Ligue 1
    "P1":  94,    # Primeira Liga
    "N1":  88,    # Eredivisie
    "E1":  40,    # Championship
    "SP2": 141,   # LaLiga2
    "D2":  79,    # 2. Bundesliga
}

# ── Impacto por número de lesionados (escala empírica) ────────────────────────
# 1 lesionado relevante → 0.2  |  3+ → 0.6  |  5+ → 0.85
_N_TO_IMPACT = [0.0, 0.20, 0.38, 0.55, 0.68, 0.78, 0.85, 0.90, 0.93, 0.95]

# Palabras en el motivo de lesión que indican baja grave (larga duración)
_SEVERE_KEYWORDS = (
    "acl", "cruciate", "ligament", "fracture", "surgery",
    "torn", "rupture", "season", "meses", "months",
)


class InjuryFetcher:
    """
    Obtiene y cachea datos de lesiones de API-Football.

    Uso:
        fetcher = InjuryFetcher(api_key="tu_key")
        impact = fetcher.get_impact("Manchester City", "E0")
        # → 0.35  (varios lesionados)
    """

    BASE = "https://v3.football.api-sports.io"
    _CACHE_TTL_H = 12   # horas antes de re-consultar la misma baja

    def __init__(self, api_key: str) -> None:
        self._key         = api_key
        self._team_cache:  dict[str, Optional[int]]        = {}  # name → team_id
        self._inj_cache:   dict[int, tuple[float, list]]   = {}  # team_id → (ts, injuries)
        self.n_calls       = 0
        self.n_errors      = 0

    # ── API pública ───────────────────────────────────────────────────────────

    def get_impact(
        self,
        team_name: str,
        div:       str,
    ) -> tuple[float, list[str]]:
        """
        Retorna (impact_score, player_names_injured).
        impact_score: 0.0 (sin lesiones) → 1.0 (plantilla diezmada).
        Nunca lanza excepción — devuelve (0.5, []) en caso de error.
        """
        league_id = _DIV_TO_AFL.get(div)
        if league_id is None:
            return 0.5, []   # liga sin soporte → neutro

        try:
            team_id = self._find_team_id(team_name, league_id)
            if team_id is None:
                return 0.5, []

            injuries = self._fetch_injuries(team_id, _current_season())
            return self._calc_impact(injuries)

        except Exception as exc:
            logger.debug("InjuryFetcher [%s]: %s", team_name, exc)
            self.n_errors += 1
            return 0.5, []

    def prefetch_teams(
        self,
        fixtures: list[tuple[str, str, str]],  # [(home, away, div), ...]
    ) -> None:
        """
        Prefetch en lote: llama a get_impact por cada equipo único.
        Útil para llamar en segundo plano antes del análisis principal.
        """
        seen: set[tuple[str, str]] = set()
        for home, away, div in fixtures:
            for team in (home, away):
                key = (team, div)
                if key not in seen:
                    seen.add(key)
                    self.get_impact(team, div)  # rellena cache

    # ── Internos ──────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict) -> dict:
        """Llamada GET con manejo de rate-limit (429) y timeout."""
        try:
            import requests
        except ImportError:
            raise RuntimeError("Paquete 'requests' no instalado.")

        url = f"{self.BASE}/{endpoint}"
        headers = {"x-apisports-key": self._key}
        resp = requests.get(url, headers=headers, params=params, timeout=12)

        if resp.status_code == 429:
            logger.warning("InjuryFetcher: rate limit alcanzado (100 req/día)")
            raise RuntimeError("API rate limit")
        resp.raise_for_status()
        self.n_calls += 1
        return resp.json()

    def _find_team_id(self, team_name: str, league_id: int) -> Optional[int]:
        """Busca el team_id en API-Football con coincidencia aproximada."""
        cache_key = f"{team_name}:{league_id}"
        if cache_key in self._team_cache:
            return self._team_cache[cache_key]

        # Buscar por nombre (primeras 5 letras para mejor coincidencia)
        query = team_name[:6].strip()
        data  = self._get("teams", {"search": query, "league": league_id})

        best_id: Optional[int] = None
        best_score = 0.0

        for entry in data.get("response", []):
            candidate = entry["team"]["name"]
            score     = _name_similarity(team_name, candidate)
            if score > best_score:
                best_score = score
                best_id    = entry["team"]["id"]

        if best_score < 0.4:
            # Segunda búsqueda sin filtro de liga para equipos con nombre corto
            data2 = self._get("teams", {"search": query})
            for entry in data2.get("response", []):
                candidate = entry["team"]["name"]
                score     = _name_similarity(team_name, candidate)
                if score > best_score:
                    best_score = score
                    best_id    = entry["team"]["id"]

        if best_score < 0.35:
            best_id = None   # sin coincidencia suficiente

        self._team_cache[cache_key] = best_id
        if best_id:
            logger.debug("InjuryFetcher: '%s' → team_id=%d (score=%.2f)", team_name, best_id, best_score)
        else:
            logger.debug("InjuryFetcher: '%s' no encontrado en API-Football", team_name)
        return best_id

    def _fetch_injuries(self, team_id: int, season: int) -> list[dict]:
        """Devuelve lista de lesionados actuales, con cache de 12h."""
        if team_id in self._inj_cache:
            ts, cached = self._inj_cache[team_id]
            age_h = (time.time() - ts) / 3600
            if age_h < self._CACHE_TTL_H:
                return cached

        data     = self._get("injuries", {"team": team_id, "season": season})
        injuries = data.get("response", [])
        self._inj_cache[team_id] = (time.time(), injuries)
        return injuries

    def _calc_impact(self, injuries: list[dict]) -> tuple[float, list[str]]:
        """
        Convierte la lista de lesionados en un score de impacto [0, 1].

        Criterios:
        - Solo cuenta los lesionados activos (no los de hace más de 6 semanas)
        - Lesiones severas (ACL, cirugía...) puntúan como 1.5× un lesionado normal
        """
        if not injuries:
            return 0.0, []

        # Filtrar por lesiones en los últimos ~50 días (evitar historiales viejos)
        cutoff = datetime.now() - timedelta(days=50)
        active: list[dict] = []

        for inj in injuries:
            fixture_date = inj.get("fixture", {}).get("date", "")
            if fixture_date:
                try:
                    fd = datetime.fromisoformat(fixture_date[:10])
                    if fd < cutoff:
                        continue
                except Exception:
                    logger.debug("Excepción ignorada", exc_info=True)
            active.append(inj)

        if not active:
            return 0.0, []

        # Calcular peso total
        effective_count = 0.0
        names: list[str] = []

        for inj in active:
            player = inj.get("player", {})
            name   = player.get("name", "")
            reason = (player.get("reason") or "").lower()

            weight = 1.0
            if any(kw in reason for kw in _SEVERE_KEYWORDS):
                weight = 0.5   # lesión larga → jugador ya sustituido en plantilla

            effective_count += weight
            if name:
                names.append(name)

        idx    = min(int(effective_count), len(_N_TO_IMPACT) - 1)
        impact = _N_TO_IMPACT[idx]

        return round(impact, 3), names[:8]   # máx 8 nombres


# ── Helpers ───────────────────────────────────────────────────────────────────

def _name_similarity(a: str, b: str) -> float:
    """Similaridad de nombre simplificada (Jaccard sobre trigramas)."""
    a = a.lower().strip()
    b = b.lower().strip()

    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85

    def _trigrams(s: str) -> set[str]:
        s = " " + s + " "
        return {s[i:i+3] for i in range(len(s) - 2)}

    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
