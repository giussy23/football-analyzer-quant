# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/quiniela_lae.py — Obtiene la jornada oficial de La Quiniela.

Fuente primaria : juegos.loteriasyapuestas.es (página oficial de SELAE).
Fuente fallback : resultados-futbol.com (espejo público, ligues españolas).
Incluye normalización de nombres y matching con predicciones del modelo.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import warnings
from difflib import SequenceMatcher
from typing import Optional

import pandas as pd
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suprimir warnings de SSL (SELAE usa cert de subdominio válido pero urllib3 avisa)
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

# ── URLs y cabeceras ──────────────────────────────────────────────────────────

# Fuente 1: SELAE oficial — la página de apuesta muestra todos los partidos
_URL_SELAE = (
    "https://juegos.loteriasyapuestas.es/jugar/la-quiniela/apuesta/"
    "?access=headercms&lang=es"
)
_HEADERS_SELAE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Host":            "juegos.loteriasyapuestas.es",
}

# Fuente 2: resultados-futbol.com — fallback para jornadas de liga española
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


# ── Fuzzy matching de nombres de equipo ──────────────────────────────────────

def _team_similarity(a: str, b: str) -> float:
    """
    Ratio de similitud entre dos nombres de equipo ya normalizados.

    Usa substring fast-path primero; SequenceMatcher para casos ambiguos.
    Umbral recomendado: ≥ 0.72 para evitar falsos positivos tipo
    «Real Madrid» ↔ «Real Sociedad».
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Fast-path: si uno es subcadena del otro con suficiente longitud
    # Mínimo 5 chars para evitar que prefijos cortos ("real", "fc") den falsos positivos
    if len(a) >= 5 and a in b:
        return 0.88
    if len(b) >= 5 and b in a:
        return 0.88
    return SequenceMatcher(None, a, b).ratio()


def _teams_match(
    norms_set: set[str],
    target_norm: str,
    threshold: float = 0.72,
) -> bool:
    """True si algún nombre del conjunto supera el umbral de similitud con target."""
    return any(
        _team_similarity(n, target_norm) >= threshold
        for n in norms_set if n
    )


# ── Fetch principal ───────────────────────────────────────────────────────────

def fetch_quiniela_fixture(timeout: int = 20) -> Optional[dict]:
    """
    Obtiene la jornada actual de La Quiniela oficial.

    Estrategia:
      1. Intenta SELAE (juegos.loteriasyapuestas.es) — fuente oficial, siempre correcta.
      2. Si falla, usa resultados-futbol.com como fallback (solo liga española).

    Retorna dict con: jornada, matches (15), fecha, ya_jugada, jornada_anterior.
    """
    # ── 1. Fuente primaria: SELAE oficial ─────────────────────────────────────
    try:
        resp = requests.get(
            _URL_SELAE, headers=_HEADERS_SELAE,
            timeout=timeout, verify=False,
        )
        if resp.status_code == 200 and len(resp.text) > 10_000:
            data = _parse_selae_html(resp.text)
            if data and data.get("matches"):
                logger.info(
                    "Quiniela jornada %s obtenida de SELAE (%d partidos).",
                    data["jornada"], len(data["matches"]),
                )
                return data
            logger.warning("SELAE: HTML obtenido pero sin partidos parseables.")
        else:
            logger.warning("SELAE: respuesta inesperada %s.", resp.status_code)
    except Exception as exc:
        logger.warning("SELAE no accesible (%s) — probando fallback.", exc)

    # ── 2. Fallback: resultados-futbol.com ────────────────────────────────────
    logger.info("Usando fallback resultados-futbol.com para la quiniela.")
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
        return _parse_html(resp.text)
    except Exception as exc:
        logger.warning("Fallback también falló: %s", exc)
        return None


def _parse_selae_html(html: str) -> Optional[dict]:
    """
    Parsea la página oficial de SELAE (juegos.loteriasyapuestas.es).

    Estructura relevante:
      Número de jornada : 'Jornada NN'
      Partidos 1–15     : <span class="nombre-partido-completo">Local - Visitante</span>
    """
    import datetime as _dt
    from datetime import date as _date

    # ── Número de jornada ─────────────────────────────────────────────────────
    m_jor = re.search(r'Jornada\s+(\d+)', html)
    jornada = m_jor.group(1) if m_jor else "?"
    try:
        jornada_anterior = str(int(jornada) - 1) if jornada != "?" else "?"
    except ValueError:
        jornada_anterior = "?"

    # ── Partidos ──────────────────────────────────────────────────────────────
    # <span class="nombre-partido-completo"> Local \n - \n Visitante </span>
    pattern = (
        r'<span[^>]*class="nombre-partido-completo"[^>]*>'
        r'\s*([^<\-]+?)\s*-\s*([^<]+?)\s*</span>'
    )
    raw = re.findall(pattern, html, re.DOTALL)

    if not raw:
        return None

    # Deduplica: la página incluye los nombres dos veces (versión completa + versión corta)
    # Usamos solo las primeras 15 ocurrencias únicas por posición
    seen: list[tuple[str, str]] = []
    for loc, vis in raw:
        loc = re.sub(r'\s+', ' ', loc).strip()
        vis = re.sub(r'\s+', ' ', vis).strip()
        if loc and vis and (loc, vis) not in seen:
            seen.append((loc, vis))
        if len(seen) == 15:
            break

    if not seen:
        return None

    today = _date.today()
    matches = []
    for i, (local, visitante) in enumerate(seen, 1):
        matches.append({
            "num":          i,
            "local":        local,
            "visitante":    visitante,
            "local_en":     to_english(local),
            "visitante_en": to_english(visitante),
            "url":          "",
            "fecha_partido": "",
        })

    return {
        "jornada":          jornada,
        "jornada_anterior": jornada_anterior,
        "matches":          matches,
        "fecha":            today.strftime("%d/%m/%Y"),
        "ya_jugada":        False,   # SELAE solo muestra la jornada activa/próxima
    }


def _parse_html(html: str) -> Optional[dict]:
    import datetime as _dt
    from datetime import date as _date

    # ── Número de jornada ─────────────────────────────────────────────────────
    # Estrategia fiable: extraer el MÁXIMO número de las URLs históricas
    # (/quiniela/historico/N) → la próxima jornada = max + 1.
    # El HTML no expone el número de la jornada en curso en texto limpio.
    hist_nums = [int(n) for n in re.findall(r'/quiniela/historico/(\d+)', html)]
    if hist_nums:
        max_hist = max(hist_nums)
        jornada  = str(max_hist + 1)    # la jornada "en juego" es la siguiente a la última archivada
        jornada_anterior = str(max_hist)
        logger.debug("Historial detectado hasta jornada %d → jornada actual: %s", max_hist, jornada)
    else:
        # Fallback: buscar número explícito antes del dropdown histórico
        main_section = html.split('id="desplega_jornadas"')[0] \
                       if 'id="desplega_jornadas"' in html else html[:15_000]
        m_j = re.search(r'(?i)jornada\s+(\d+)', main_section)
        if not m_j:
            m_j = re.search(r'<title[^>]*>[^<]*?(\d{2,})[^<]*</title>', html)
        jornada          = m_j.group(1) if m_j else "?"
        jornada_anterior = "?"

    # ── Los partidos (la página tiene 30: jornada actual + próxima) ──────────
    # La tabla usa <td class="q_teams"> con un enlace al partido.
    # Extraemos hasta 30 y separamos en dos grupos de 15.
    pattern_match = (
        r'<td class="q_teams"[^>]*>.*?'
        r'<a[^>]*href="(/partido/[^"]+)">([^<]+)</a>'
    )
    all_raw = re.findall(pattern_match, html, re.DOTALL)
    group1  = all_raw[:15]
    group2  = all_raw[15:30]   # próxima jornada (vacío si la página no la tiene aún)

    if not group1:
        logger.warning("No se encontraron partidos en la página de la quiniela.")
        return None

    # ── Fechas de cada partido (columna q_day → <span>DD/MM</span>) ──────────
    # Extraer filas completas para leer también la fecha
    pattern_row = (
        r'<tr[^>]*>.*?'
        r'<td class="q_teams"[^>]*>.*?<a[^>]*href="(/partido/[^"]+)">([^<]+)</a>'
        r'.*?'
        r'<td class="q_day"[^>]*>.*?<span[^>]*>([^<]*)</span>'
    )
    rows_with_dates = re.findall(pattern_row, html, re.DOTALL)
    date_map: dict[str, str] = {}   # url → "DD/MM"
    for url, _, day_text in rows_with_dates:
        day_text = day_text.strip()
        if re.match(r'\d{1,2}/\d{1,2}', day_text):
            date_map[url] = day_text

    # ── Detectar si el grupo 1 (jornada visualizada) ya fue jugada ────────────
    today     = _date.today()
    cur_year  = today.year
    match_dates: list[_date] = []
    for url, _ in group1:
        day_str = date_map.get(url, "")
        if day_str and re.match(r'\d{1,2}/\d{2}$', day_str):
            try:
                day, month = (int(x) for x in day_str.split("/"))
                # Elegir año: si el mes ya pasó este año, puede ser del año siguiente
                for year in [cur_year, cur_year + 1]:
                    candidate = _date(year, month, day)
                    if candidate >= today - _dt.timedelta(days=30):
                        match_dates.append(candidate)
                        break
            except (ValueError, OverflowError):
                pass

    ya_jugada = False
    if match_dates:
        max_match_date = max(match_dates)
        # "ya jugada" si TODOS los partidos del grupo 1 son anteriores a hoy
        ya_jugada = max_match_date < today

    # ── Si el grupo 1 ya se jugó y el grupo 2 tiene 15 partidos → usar grupo 2
    # La página expone simultáneamente la jornada recién terminada (grupo 1)
    # y la próxima jornada pendiente (grupo 2). Cuando grupo 1 = ya jugada y
    # grupo 2 está completo, la jornada "actual" que queremos mostrar es grupo 2.
    raw = group1
    if ya_jugada and len(group2) == 15:
        logger.info(
            "Grupo 1 (jornada %s) ya jugada — usando grupo 2 (jornada %s) con %d partidos.",
            jornada_anterior, jornada, len(group2),
        )
        raw         = group2
        ya_jugada   = False   # grupo 2 = jornada próxima, aún no disputada
        match_dates = []      # sin fechas confirmadas para la próxima jornada

    # ── Construir lista de partidos ───────────────────────────────────────────
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
            "fecha_partido": date_map.get(url, ""),
        })

    # ── Fecha global de la jornada ────────────────────────────────────────────
    if match_dates:
        # Usar la fecha del primer partido del grupo
        first_date = match_dates[0] if match_dates else None
        fecha = first_date.strftime("%d/%m/%Y") if first_date else today.strftime("%d/%m/%Y")
    else:
        fecha = today.strftime("%d/%m/%Y")

    logger.info(
        "Quiniela jornada %s: %d partidos · fecha %s · ya_jugada=%s",
        jornada, len(matches), fecha, ya_jugada,
    )
    return {
        "jornada":          jornada,
        "jornada_anterior": jornada_anterior,
        "matches":          matches,
        "fecha":            fecha,
        "ya_jugada":        ya_jugada,
    }


# ── Cuotas en tiempo real desde The Odds API ─────────────────────────────────

def enrich_with_api_odds(
    matches: list[dict],
    api_key: str,
    timeout: int = 12,
) -> list[dict]:
    """
    Enriquece los partidos de la quiniela con probabilidades de The Odds API.

    Consulta La Liga (SP1) y Segunda División (SP2).
    Para partidos sin cobertura deja las claves vacías → ELO actuará de fallback.
    Probabilidades calculadas con normalización no-vig (sin margen de casa).
    """
    try:
        from .odds_api import fetch_odds_fixtures
        from .features import fair_probs as _fair
        odds_df, _ = fetch_odds_fixtures(api_key, ["SP1", "SP2"])
    except Exception as exc:
        logger.warning("Odds API: no se pudieron obtener cuotas para la quiniela: %s", exc)
        return matches

    if odds_df is None or odds_df.empty:
        return matches

    # Construir tabla de búsqueda normalizada: "h_norm|a_norm" → datos
    lookup: dict[str, dict] = {}
    h_col = "HomeTeam" if "HomeTeam" in odds_df.columns else "home_team"
    a_col = "AwayTeam" if "AwayTeam" in odds_df.columns else "away_team"

    for _, row in odds_df.iterrows():
        hn = normalize(str(row.get(h_col, "")))
        an = normalize(str(row.get(a_col, "")))
        oh = row.get("B365H")
        od = row.get("B365D")
        oa = row.get("B365A")
        try:
            if oh and od and oa and float(oh) > 1 and float(od) > 1 and float(oa) > 1:
                fh, fd, fa = _fair(float(oh), float(od), float(oa))
                lookup[f"{hn}|{an}"] = {
                    "p_home":      fh,
                    "p_draw":      fd,
                    "p_away":      fa,
                    "odds_h":      float(oh),
                    "odds_d":      float(od),
                    "odds_a":      float(oa),
                    "p_source":    "odds_api",
                    "reliability": 55,
                }
        except (TypeError, ValueError):
            continue

    enriched = []
    for match in matches:
        entry = dict(match)

        local_norms    = {normalize(match["local"]),
                          normalize(match.get("local_en", match["local"]))}
        visit_norms    = {normalize(match["visitante"]),
                          normalize(match.get("visitante_en", match["visitante"]))}

        found_data = None
        for key, data in lookup.items():
            hn, an = key.split("|", 1)
            home_ok = _teams_match(local_norms, hn)
            away_ok = _teams_match(visit_norms, an)
            if home_ok and away_ok:
                found_data = data
                break

        if found_data:
            entry.update(found_data)
            logger.debug(
                "Odds API match: %s vs %s → P(1)=%.0f%% P(X)=%.0f%% P(2)=%.0f%%",
                match["local"], match["visitante"],
                found_data["p_home"] * 100,
                found_data["p_draw"] * 100,
                found_data["p_away"] * 100,
            )

        enriched.append(entry)

    matched = sum(1 for m in enriched if m.get("p_source") == "odds_api")
    logger.info("Odds API quiniela: %d/%d partidos con cuotas.", matched, len(enriched))
    return enriched


# ── Matching con predicciones del modelo (opcional) ───────────────────────────

def _is_national_team(name: str) -> bool:
    """Devuelve True si el nombre (en español) corresponde a una selección nacional."""
    return normalize(name) in _ES_TO_EN


def match_with_predictions(
    quiniela_matches: list[dict],
    results_df: Optional[pd.DataFrame],
    elo_model=None,
    club_elo_model=None,
) -> list[dict]:
    """
    Enriquece cada partido con predicciones.

    Jerarquía de fuentes:
      1. Cuotas ya fijadas (odds_api) → respeta sin sobrescribir
      2. ML del Trading Desk (results_df, opcional)
      3. Club ELO (clubelo.com) — para partidos de clubes sin ML
      4. ELO nacional (eloratings.net) — para selecciones sin otra fuente

    results_df puede ser None si el usuario no ha ejecutado el análisis principal.
    club_elo_model puede ser None (ClubEloModel de core/club_elo.py).
    """
    # Pre-normalizar el DataFrame ML si está disponible
    if results_df is not None and not results_df.empty:
        df = results_df.copy()
        df["_norm_home"] = df["home_team"].astype(str).map(normalize)
        df["_norm_away"] = df["away_team"].astype(str).map(normalize)
    else:
        df = None

    enriched = []
    for match in quiniela_matches:
        entry = dict(match)

        # ── 1. Ya tiene probabilidades (p. ej. del Odds API) ─────────────────
        if entry.get("p_source") in ("odds_api", "ml") and entry.get("p_home") is not None:
            # Rellenar model_pick a partir de las probabilidades si falta
            if not entry.get("model_pick") and entry.get("p_home"):
                ph, pd_, pa = float(entry["p_home"]), float(entry.get("p_draw", 0)), float(entry.get("p_away", 0))
                if ph >= pd_ and ph >= pa:
                    entry["model_pick"] = "1"
                elif pd_ >= ph and pd_ >= pa:
                    entry["model_pick"] = "X"
                else:
                    entry["model_pick"] = "2"
            enriched.append(entry)
            continue

        local_norms    = {normalize(match["local"]),
                          normalize(match.get("local_en", match["local"]))}
        visitante_norms = {normalize(match["visitante"]),
                           normalize(match.get("visitante_en", match["visitante"]))}

        # ── 2. ML del Trading Desk ────────────────────────────────────────────
        found = None
        if df is not None:
            for _, row in df.iterrows():
                rh = row["_norm_home"]
                ra = row["_norm_away"]
                home_ok = _teams_match(local_norms, rh)
                away_ok = _teams_match(visitante_norms, ra)
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
            entry["p_source"]   = "ml"
        else:
            # ── 3. Club ELO (clubelo.com) — para partidos de clubes ───────────
            entry["model_pick"] = None
            if not entry.get("odds_h"):
                entry["odds_h"] = entry["odds_d"] = entry["odds_a"] = None

            local_name = match.get("local", "")
            visit_name = match.get("visitante", "")
            is_intl    = _is_national_team(local_name) or _is_national_team(visit_name)

            club_pred = None
            if (not is_intl
                    and club_elo_model is not None
                    and club_elo_model.is_ready()):
                # Intentar con nombre en español primero, luego en inglés
                for h_name in [local_name, match.get("local_en", local_name)]:
                    for a_name in [visit_name, match.get("visitante_en", visit_name)]:
                        club_pred = club_elo_model.predict(h_name, a_name)
                        if club_pred is not None:
                            break
                    if club_pred is not None:
                        break

            if club_pred is not None:
                p_h, p_d, p_a, elo_h, elo_a = club_pred
                entry["p_home"]      = p_h
                entry["p_draw"]      = p_d
                entry["p_away"]      = p_a
                entry["elo_home"]    = elo_h
                entry["elo_away"]    = elo_a
                entry["p_source"]    = "club_elo"
                entry["reliability"] = 42   # Club ELO es más fiable que ELO nacional para clubes
                logger.debug(
                    "ClubELO %s vs %s → %.0f/%.0f  (%.0f%%/%.0f%%/%.0f%%)",
                    local_name, visit_name, elo_h, elo_a,
                    p_h * 100, p_d * 100, p_a * 100,
                )

            # ── 4. ELO nacional (fallback: selecciones / sin datos de club) ────
            elif elo_model is not None and elo_model.is_ready():
                local_en     = match.get("local_en",     local_name)
                visitante_en = match.get("visitante_en", visit_name)
                p_h, p_d, p_a, elo_h, elo_a = elo_model.predict(local_en, visitante_en)
                entry["p_home"]      = p_h
                entry["p_draw"]      = p_d
                entry["p_away"]      = p_a
                entry["elo_home"]    = elo_h
                entry["elo_away"]    = elo_a
                entry["p_source"]    = "elo"
                entry["reliability"] = 30
                logger.debug(
                    "ELO nacional %s vs %s → %.0f/%.0f  (%.0f%%/%.0f%%/%.0f%%)",
                    local_en, visitante_en, elo_h, elo_a,
                    p_h * 100, p_d * 100, p_a * 100,
                )
            else:
                entry["p_home"] = entry["p_draw"] = entry["p_away"] = None
                entry["p_source"]    = None
                entry["reliability"] = 0

        enriched.append(entry)

    return enriched
