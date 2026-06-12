# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
data.py — Descarga, limpieza y preparación de datos de football-data.co.uk
"""

from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

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

def fetch_csv(url: str, timeout: int = 30) -> pd.DataFrame:
    """Descarga y parsea un CSV de football-data.co.uk."""
    logger.info("Descargando %s", url)
    resp = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    df = pd.read_csv(
        io.StringIO(resp.content.decode("utf-8-sig", errors="replace"))
    )
    df = clean_columns(df)
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].map(_clean_text)
    return df


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
