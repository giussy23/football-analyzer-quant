# Football Analyzer Quant Pro v10.0

Analizador cuantitativo de apuestas deportivas con modelo predictivo, backtest OOS y UI de escritorio.

## Estructura del proyecto

```
football_analyzer/
├── main.py                   # Punto de entrada
├── app.py                    # PremiumApp — orquestador principal
├── requirements.txt
│
├── core/
│   ├── config.py             # Constantes, LEAGUE_MAP, parámetros
│   ├── data.py               # Descarga y limpieza de datos
│   ├── features.py           # Ingeniería de características (team stats + market)
│   ├── model.py              # FootballModel con walk-forward OOS + joblib
│   ├── analyzer.py           # Pipeline: backtest, Kelly, scoring, analyze()
│   └── storage.py            # SQLite: settings + historial
│
├── ui/
│   ├── widgets.py            # Componentes reutilizables (cards, textboxes)
│   └── views/
│       ├── analysis.py       # Vista Trading Desk
│       ├── portfolio.py      # Vista Portfolio + Execution/Simulator
│       └── settings.py       # Vista Settings + Telegram
│
└── tests/
    └── test_core.py          # Tests unitarios del motor
```

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

```bash
cd football_analyzer
python main.py
```

## Tests

```bash
pytest tests/ -v
```

## Mejoras v10.0 respecto a v9.1

| Área | v9.1 | v10.0 |
|------|------|-------|
| Backtest | In-sample (optimista) | Walk-forward OOS temporal |
| Modelo | Reentrena siempre | Serializado con joblib |
| Código | Un fichero, líneas de 400 chars | Módulos separados, legible |
| Métricas | Log-loss in-sample | Log-loss + Brier **out-of-sample** |
| Tests | Sin tests | 20+ tests unitarios (pytest) |
| Logging | messagebox/print | logging estándar de Python |
| Look-ahead bias | Parcialmente corregido | Corregido con idx_limit + eval en 2ª mitad |

## Notas sobre las apuestas

- Las métricas OOS son más conservadoras que las in-sample: son realistas.
- Kelly fraccionado al 20% con cap 1.5%: gestión de bankroll conservadora.
- CLV (Closing Line Value) es la métrica más fiable de edge a largo plazo.
- Un ROI positivo en backtest OOS **no garantiza** rentabilidad futura.
