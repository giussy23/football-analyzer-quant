# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
data.py — Descarga, limpieza y preparación de datos de football-data.co.uk
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import time

import numpy as np
import pandas as pd
import requests

from .config import CURRENT_SEASON, DATA_DIR, HIST_SEASONS

logger = logging.getLogger(__name__)

# Caché de CSVs descargados (football-data.co.uk). Evita re-descargar los
# mismos ficheros en cada análisis y permite trabajar sin red si hay copia.
_CACHE_DIR = os.path.join(DATA_DIR, "csv_cache")

# ── Helpers de limpieza ────────────────────────────────────────────────────────

def _clean_col_name(name: str) -> str:
    return str(name).replace("\ufeff", "").replace("ï»¿", "").strip()


def _clean_text(value) -> str:
    if isinstance(value, str):
        return value.replace("\ufeff", "").replace("ï»¿", "").strip()
    return value


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [_clean_col_name(c) for c in df.columns]
    return df


def first_existing(row: pd.Series, names: list[str]):
    """Devuelve el primer valor no-nulo de una lista de columnas."""
    for n in names:
        if n in row.index and pd.notna(row.get(n)):
            return row.get(n)
    return np.nan


# ── Descarga ───────────────────────────────────────────────────────────────────

def _parse_csv_bytes(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(
        io.StringIO(raw.decode("utf-8-sig", errors="replace"))
    )
    df = clean_columns(df)
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].map(_clean_text)
    return df


def _cache_path_for(url: str) -> str:
    key  = hashlib.sha1(url.encode()).hexdigest()[:12]
    tail = re.sub(r"[^A-Za-z0-9._-]", "_", "_".join(url.rstrip("/").split("/")[-2:]))[:48]
    return os.path.join(_CACHE_DIR, f"{tail}_{key}.csv")


def fetch_csv(url: str, timeout: int = 30, cache_hours: float = 6.0) -> pd.DataFrame:
    """Descarga y parsea un CSV de football-data.co.uk.

    cache_hours > 0 → guarda copia en disco y la reutiliza mientras no caduque.
    Si la descarga falla y existe copia (aunque esté caducada), se usa como
    fallback para que la app funcione sin red.
    """
    cache_path = None
    if cache_hours > 0:
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            cache_path = _cache_path_for(url)
            if os.path.exists(cache_path):
                age = time.time() - os.path.getmtime(cache_path)
                if age < cache_hours * 3600:
                    logger.debug("CSV desde caché (%.1f h): %s", age / 3600, url)
                    with open(cache_path, "rb") as fh:
                        return _parse_csv_bytes(fh.read())
        except Exception as exc:
            logger.debug("Caché CSV no disponible (%s): %s", exc, url)
            cache_path = None

    logger.info("Descargando %s", url)
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    except Exception:
        # Fallback: copia caducada mejor que fallo total
        if cache_path and os.path.exists(cache_path):
            logger.warning("Descarga fallida — usando caché caducada: %s", url)
            with open(cache_path, "rb") as fh:
                return _parse_csv_bytes(fh.read())
        raise

    if cache_path:
        try:
            with open(cache_path, "wb") as fh:
                fh.write(resp.content)
        except Exception as exc:
            logger.debug("No se pudo escribir caché CSV: %s", exc)
    return _parse_csv_bytes(resp.content)


def fetch_historic_multi(csv_url: str, seasons: list[str] | None = None) -> pd.DataFrame:
    """Descarga el histórico de una liga para varias temporadas y las concatena
    en orden cronológico.

    csv_url es la URL de la temporada ACTUAL (la de LEAGUE_MAP); las URLs de
    temporadas anteriores se derivan sustituyendo el código de temporada.
    Las temporadas pasadas son inmutables → caché de 30 días; la actual, 6 h.
    Si una temporada antigua falla se omite (la actual es obligatoria).
    """
    seasons = seasons or HIST_SEASONS
    frames: list[pd.DataFrame] = []
    for season in seasons:
        url = csv_url.replace(f"/{CURRENT_SEASON}/", f"/{season}/")
        is_current = season == CURRENT_SEASON
        try:
            frames.append(fetch_csv(url, cache_hours=6.0 if is_current else 720.0))
        except Exception as exc:
            if is_current:
                raise
            logger.warning("Histórico %s no disponible (%s) — se omite", url, exc)
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


# ── Preparación de histórico ───────────────────────────────────────────────────

_HIST_RENAME = {
    "Date": "date", "HomeTeam": "home_team", "AwayTeam": "away_team",
    "FTHG": "home_goals", "FTAG": "away_goals", "FTR": "result", "Div": "div",
}

_ODDS_COLS = [
    "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5", "B365O25", "B365U25",
]


def prepare_historic(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df.copy()).rename(columns=_HIST_RENAME)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

    for col in _ODDS_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Normalizar columnas Over/Under (el nombre cambia por temporada)
    df["B365O25"] = df.apply(
        lambda r: first_existing(r, ["B365O25", "B365>2.5"]), axis=1
    )
    df["B365U25"] = df.apply(
        lambda r: first_existing(r, ["B365U25", "B365<2.5"]), axis=1
    )

    df = df.dropna(subset=["home_team", "away_team", "home_goals", "away_goals"])
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)

    df["result"] = np.where(
        df["home_goals"] > df["away_goals"], "H",
        np.where(df["home_goals"] < df["away_goals"], "A", "D"),
    )
    df["over25"]      = ((df["home_goals"] + df["away_goals"]) > 2).astype(int)
    df["total_goals"] = df["home_goals"] + df["away_goals"]

    if "div" in df.columns:
        df["div"] = df["div"].astype(str).map(_clean_text).str.upper()

    return df.sort_values("date").reset_index(drop=True)


# ── Preparación de fixtures ────────────────────────────────────────────────────

_FIX_RENAME = {
    "Date": "date", "Time": "time",
    "HomeTeam": "home_team", "AwayTeam": "away_team", "Div": "div",
}

_FIX_ODDS_COLS = [
    "B365H", "B365D", "B365A",
    "B365>2.5", "B365<2.5", "B365O25", "B365U25",
    "B365CH", "B365CD", "B365CA",
    "B365C>2.5", "B365C<2.5",
]


def prepare_fixtures(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df.copy()).rename(columns=_FIX_RENAME)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", dayfirst=True)

    for col in _FIX_ODDS_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["B365O25"] = df.apply(
        lambda r: first_existing(r, ["B365O25", "B365>2.5"]), axis=1
    )
    df["B365U25"] = df.apply(
        lambda r: first_existing(r, ["B365U25", "B365<2.5"]), axis=1
    )

    df["div"] = df["div"].astype(str).map(_clean_text).str.upper()
    return df.reset_index(drop=True)
