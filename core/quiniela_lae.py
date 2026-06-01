"""
core/quiniela_lae.py — Obtiene la jornada oficial de La Quiniela.

Fuente: resultados-futbol.com (espejo público de los datos de SELAE).
No requiere API key. Incluye normalización de nombres y matching
con los resultados de nuestro modelo para obtener predicciones IA.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_URL     = "https://www.resultados-futbol.com/quiniela"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "es-ES,es;q=0.9",
}

# ── Mapeo español → inglés para selecciones nacionales ───────────────────────

_ES_TO_EN: dict[str, str] = {
    "alemania":          "Germany",
    "argentina":         "Argentina",
    "australia":         "Australia",
    "austria":           "Austria",
    "belgica":           "Belgium",
    "bolivia":           "Bolivia",
    "bosnia":            "Bosnia & Herzegovina",
    "bosnia y herzegovina": "Bosnia & Herzegovina",
    "brasil":            "Brazil",
    "camerun":           "Cameroon",
    "canada":            "Canada",
    "chile":             "Chile",
    "chipre":            "Cyprus",
    "colombia":          "Colombia",
    "corea del sur":     "South Korea",
    "costa de marfil":   "Ivory Coast",
    "costa rica":        "Costa Rica",
    "croacia":           "Croatia",
    "dinamarca":         "Denmark",
    "ecuador":           "Ecuador",
    "egipto":            "Egypt",
    "el salvador":       "El Salvador",
    "escocia":           "Scotland",
    "eslovaquia":        "Slovakia",
    "eslovenia":         "Slovenia",
    "espana":            "Spain",
    "estados unidos":    "USA",
    "estonia":           "Estonia",
    "finlandia":         "Finland",
    "francia":           "France",
    "gales":             "Wales",
    "ghana":             "Ghana",
    "grecia":            "Greece",
    "haiti":             "Haiti",
    "honduras":          "Honduras",
    "hungria":           "Hungary",
    "inglaterra":        "England",
    "iran":              "Iran",
    "irlanda":           "Ireland",
    "islandia":          "Iceland",
    "islas feroe":       "Faroe Islands",
    "italia":            "Italy",
    "jamaica":           "Jamaica",
    "japon":             "Japan",
    "letonia":           "Latvia",
    "liechtenstein":     "Liechtenstein",
    "lituania":          "Lithuania",
    "marruecos":         "Morocco",
    "mexico":            "Mexico",
    "nigeria":           "Nigeria",
    "noruega":           "Norway",
    "nueva zelanda":     "New Zealand",
    "paises bajos":      "Netherlands",
    "panama":            "Panama",
    "paraguay":          "Paraguay",
    "peru":              "Peru",
    "polonia":           "Poland",
    "portugal":          "Portugal",
    "qatar":             "Qatar",
    "republica checa":   "Czech Republic",
    "rumania":           "Romania",
    "rusia":             "Russia",
    "arabia saudi":      "Saudi Arabia",
    "senegal":           "Senegal",
    "serbia":            "Serbia",
    "sudafrica":         "South Africa",
    "suecia":            "Sweden",
    "suiza":             "Switzerland",
    "tunez":             "Tunisia",
    "turquia":           "Turkey",
    "ucrania":           "Ukraine",
    "uruguay":           "Uruguay",
    "venezuela":         "Venezuela",
}


# ── Utilidades de normalización ───────────────────────────────────────────────

def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(name: str) -> str:
    """Minúsculas sin acentos, sin puntuación extra."""
    return re.sub(r"\s+", " ", _strip_accents(name).lower()).strip()


def to_english(spanish: str) -> str:
    """Convierte el nombre de una selección del español al inglés."""
    key = normalize(spanish)
    return _ES_TO_EN.get(key, spanish)


# ── Fetch principal ───────────────────────────────────────────────────────────

def fetch_quiniela_fixture(timeout: int = 20) -> Optional[dict]:
    """
    Obtiene la jornada actual de La Quiniela oficial.

    Retorna:
        {
            "jornada": "66",
            "matches": [
                {
                  "num": 1, "local": "CD Castellón", "visitante": "Almería",
                  "local_en": "CD Castellon", "visitante_en": "Almeria"
                },
                ...  # 15 entradas
            ]
        }
        o None si la petición falla.
    """
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.warning("Error al obtener quiniela: %s", exc)
        return None

    return _parse_html(html)


def _parse_html(html: str) -> Optional[dict]:
    # ── Número de jornada ─────────────────────────────────────────────────────
    # Buscarlo ANTES de la lista de histórico para evitar "Jornada 1, 2, 3..."
    main_section = html.split('id="desplega_jornadas"')[0] \
                   if 'id="desplega_jornadas"' in html else html[:15_000]

    jornada = "?"
    m_j = re.search(r'(?i)jornada\s+(\d+)', main_section)
    if not m_j:
        # Buscar en el title o h1
        m_j = re.search(r'<title[^>]*>[^<]*?(\d{2,})[^<]*</title>', html)
    if m_j:
        jornada = m_j.group(1)

    # ── Los 15 partidos ───────────────────────────────────────────────────────
    pattern = (
        r'<td class="q_teams"[^>]*>.*?'
        r'<a[^>]*href="(/partido/[^"]+)">([^<]+)</a>'
    )
    raw = re.findall(pattern, html, re.DOTALL)[:15]

    if not raw:
        logger.warning("No se encontraron partidos en la página de la quiniela.")
        return None

    matches = []
    for i, (url, teams) in enumerate(raw, 1):
        if " - " in teams:
            local, visitante = teams.split(" - ", 1)
        else:
            local, visitante = teams, "?"

        local_c     = local.strip()
        visitante_c = visitante.strip()

        matches.append({
            "num":         i,
            "local":       local_c,
            "visitante":   visitante_c,
            "local_en":    to_english(local_c),
            "visitante_en": to_english(visitante_c),
            "url":         url,
        })

    logger.info("Quiniela jornada %s: %d partidos.", jornada, len(matches))
    return {"jornada": jornada, "matches": matches}


# ── Matching con predicciones del modelo ─────────────────────────────────────

def match_with_predictions(
    quiniela_matches: list[dict],
    results_df: pd.DataFrame,
) -> list[dict]:
    """
    Para cada partido de la quiniela intenta encontrar la predicción del modelo.
    Añade claves p_home, p_draw, p_away, model_pick, odds_h/d/a si se encuentra.

    El matching usa normalización sin acentos + similitud de token.
    """
    if results_df is None or results_df.empty:
        return quiniela_matches

    # Pre-normalizar el DataFrame
    df = results_df.copy()
    df["_norm_home"] = df["home_team"].astype(str).map(normalize)
    df["_norm_away"] = df["away_team"].astype(str).map(normalize)

    enriched = []
    for match in quiniela_matches:
        entry = dict(match)

        # Nombres a buscar: original en español + versión inglés
        local_norms     = {normalize(match["local"]),     normalize(match["local_en"])}
        visitante_norms = {normalize(match["visitante"]), normalize(match["visitante_en"])}

        found = None
        for _, row in df.iterrows():
            rh = row["_norm_home"]
            ra = row["_norm_away"]

            # Coincidencia exacta o por contenido
            home_ok = any(ln in rh or rh in ln for ln in local_norms)
            away_ok = any(vn in ra or ra in vn for vn in visitante_norms)

            if home_ok and away_ok:
                found = row
                break

        if found is not None:
            entry["p_home"]     = found.get("p_home")
            entry["p_draw"]     = found.get("p_draw")
            entry["p_away"]     = found.get("p_away")
            entry["model_pick"] = found.get("pick")
            entry["odds_h"]     = found.get("B365H") or found.get("odds")
            entry["odds_d"]     = found.get("B365D")
            entry["odds_a"]     = found.get("B365A")
            entry["reliability"] = found.get("reliability_score", 0)
        else:
            entry["p_home"] = entry["p_draw"] = entry["p_away"] = None
            entry["model_pick"] = None
            entry["odds_h"] = entry["odds_d"] = entry["odds_a"] = None
            entry["reliability"] = 0

        enriched.append(entry)

    return enriched
