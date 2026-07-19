"""
config.py — Constantes globales, mapas de ligas y paleta de colores.
"""

DB_FILE = "football_analyzer.db"
MODEL_FILE = "football_model.joblib"

FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

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

# ── Paleta UI ──────────────────────────────────────────────────────────────────
BG       = "#07111f"
CARD     = "#0d1728"
CARD_2   = "#101c30"
BORDER   = "#1e2b44"
TEXT     = "#e6edf7"
MUTED    = "#8fa3bf"
ACCENT   = "#3b82f6"
ACCENT_2 = "#2563eb"

OUTCOME_LABELS = ["H", "D", "A"]

# ── Parámetros del modelo ──────────────────────────────────────────────────────
# Walk-forward: porcentaje mínimo de datos históricos para entrenar
WF_MIN_TRAIN_RATIO = 0.60   # entrena con el 60 % inicial, valida en el resto
WF_SPLITS          = 5      # número de ventanas temporales

# Fractional Kelly
KELLY_FRACTION = 0.20
KELLY_CAP      = 0.015      # máximo 1.5 % del bankroll por apuesta

# Filtros de mercado
MAX_OVERROUND_1X2 = 1.08
MAX_OVERROUND_OU  = 1.10
CLV_MIN           = -0.01   # no apostar si CLV < -1 %
MIN_SAMPLE        = 6       # mínimo de partidos previos por equipo
