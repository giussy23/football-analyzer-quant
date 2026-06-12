# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
config.py — Constantes globales, mapas de ligas y paleta de colores.
"""

import os as _os
import sys as _sys

# Carpeta de datos escribible. Empaquetada (instalada en Archivos de programa,
# solo lectura) → %LOCALAPPDATA%\AlphaBet. En desarrollo → raíz del proyecto
# (mismo sitio que antes, sin perder la BD existente).
if getattr(_sys, "frozen", False):
    DATA_DIR = _os.path.join(
        _os.environ.get("LOCALAPPDATA") or _os.path.expanduser("~"), "AlphaBet")
else:
    DATA_DIR = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
try:
    _os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = _os.path.abspath(".")

DB_FILE    = _os.path.join(DATA_DIR, "football_analyzer.db")
MODEL_FILE = _os.path.join(DATA_DIR, "football_model_v15.joblib")   # v15: +stacking ensemble (HistGBM + XGBoost + RF) + meta-learner LogisticRegression

# Monitor de líneas
LINE_POLL_INTERVAL = 300    # segundos entre polls (5 min)
STEAM_THRESHOLD    = 0.025  # caída ≥2.5% en prob implícita = steam move
LINE_MOVE_THRESHOLD = 0.015 # caída ≥1.5% = movimiento notable

# Tier de liga: el modelo aprende patrones específicos por nivel competitivo
LEAGUE_TIER: dict[str, int] = {
    "E0": 1, "SP1": 1, "I1": 1, "D1": 1, "F1": 1,   # top 5 europeas
    "P1": 2, "N1": 2, "E1": 2, "SP2": 2,              # tier 2
    "WC": 0, "LIB": 0, "CSU": 0,                      # internacionales (sin ML)
}

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

# Temporadas de histórico para entrenar el modelo. Una sola temporada
# (~330-740 partidos) producía overfitting con 124 features: logloss OOS
# 1.35-1.50, peor que el azar (1.0986). Con 3 temporadas el dataset por
# liga sube a ~1.100 partidos. La ÚLTIMA debe ser la temporada actual
# (la que aparece en las URLs de LEAGUE_MAP).
CURRENT_SEASON = "2526"
HIST_SEASONS   = ["2324", "2425", "2526"]

# Formato: (div_code, csv_historico_url_o_None, color_ui)
# csv=None → liga sin histórico en football-data.co.uk → solo cuotas en tiempo real
LEAGUE_MAP: dict[str, tuple[str, str | None, str]] = {
    # ── Ligas europeas (histórico + cuotas) ─────────────────────────────────
    "Premier League": ("E0",  "https://www.football-data.co.uk/mmz4281/2526/E0.csv",  "#8b5cf6"),
    "Championship":   ("E1",  "https://www.football-data.co.uk/mmz4281/2526/E1.csv",  "#3b82f6"),
    "La Liga":        ("SP1", "https://www.football-data.co.uk/mmz4281/2526/SP1.csv", "#f59e0b"),
    "Segunda":        ("SP2", "https://www.football-data.co.uk/mmz4281/2526/SP2.csv", "#22c55e"),
    "Serie A":        ("I1",  "https://www.football-data.co.uk/mmz4281/2526/I1.csv",  "#06b6d4"),
    "Bundesliga":     ("D1",  "https://www.football-data.co.uk/mmz4281/2526/D1.csv",  "#ef4444"),
    "Ligue 1":        ("F1",  "https://www.football-data.co.uk/mmz4281/2526/F1.csv",  "#38bdf8"),
    "Primeira Liga":  ("P1",  "https://www.football-data.co.uk/mmz4281/2526/P1.csv",  "#10b981"),
    "Eredivisie":     ("N1",  "https://www.football-data.co.uk/mmz4281/2526/N1.csv",  "#fb923c"),
    # ── Competiciones internacionales (solo cuotas en tiempo real) ───────────
    "🏆 Mundial 2026":     ("WC",  None, "#ffd700"),
    "🌎 Copa Libertadores": ("LIB", None, "#10b981"),
    "🌎 Copa Sudamericana": ("CSU", None, "#06b6d4"),
}

# ── Paleta UI — terminal quant oscuro, estilo cyber-trading ──────────────────
BG       = "#020810"   # negro azulado profundo (deep space)
CARD     = "#040c18"   # carta vidrio oscuro navy
CARD_2   = "#060f1f"   # panel secundario
BORDER   = "#0d9488"   # teal (del logo — ring exterior)
TEXT     = "#e0f2fe"   # blanco azulado cristalino
MUTED    = "#4d7a94"   # teal gris apagado
ACCENT   = "#22d3ee"   # cyan brillante (órbita del logo)
ACCENT_2 = "#0891b2"   # hover cyan oscuro

OUTCOME_LABELS = ["H", "D", "A"]

# ── Parámetros del modelo ──────────────────────────────────────────────────────
# Walk-forward: porcentaje mínimo de datos históricos para entrenar
WF_MIN_TRAIN_RATIO = 0.60   # entrena con el 60 % inicial, valida en el resto
WF_SPLITS          = 5      # número de ventanas temporales

# Fractional Kelly
KELLY_FRACTION = 0.20
KELLY_CAP      = 0.015      # máximo 1.5 % del bankroll por apuesta

# Blend modelo+mercado (pooling geométrico: modelo^w · mercado^(1-w)).
# Holdout cronológico 12/06/2026 (tools/eval_holdout.py, 1.417 partidos):
# w=0.35 es el peso óptimo y el blend bate al mercado (logloss 0.9978 vs
# 1.0039). Usar el modelo a pelo (w=1) sobreestima los edges ~3×.
# 0 = confiar solo en el mercado; 1 = solo el modelo (comportamiento antiguo).
BLEND_MODEL_WEIGHT = 0.35

# Filtros de mercado
MAX_OVERROUND_1X2 = 1.08
MAX_OVERROUND_OU  = 1.10
CLV_MIN           = -0.01   # no apostar si CLV < -1 %
MIN_SAMPLE        = 6       # mínimo de partidos previos por equipo

# Modelos por liga
MIN_ROWS_PER_LEAGUE   = 300    # mínimo de partidos para entrenar modelo propio
MODEL_FILE_TEMPLATE   = _os.path.join(DATA_DIR, "football_model_{div}_v15.joblib")  # {div} = E0, SP1, etc.
USE_LEAGUE_MODELS     = True   # flag para activar/desactivar fácilmente
