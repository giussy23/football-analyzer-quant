# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
core/quiniela_calibrator.py — Motor de auto-calibración del generador de picks.

Aprende de DOS fuentes de datos:

  1. CSV históricos de SP1 y SP2 (football-data.co.uk)
     – Calcula la distribución empírica real de 1/X/2 en fútbol español
     – Mide el sesgo de empate del mercado (p_mercado vs p_real)
     – Optimiza los umbrales triple/doble por grid-search

  2. Boletos verificados en quiniela_history
     – Tasa de acierto real por tipo de pick (simple/doble/triple)
     – Ajuste fino de thresholds basado en tu historial personal

Parámetros que calibra:
  triple_threshold  — si max(prob) < este valor → pick triple (1X2)
  double_threshold  — si 2ª prob >= este valor  → pick doble  (1X / X2 / 12)
  draw_bias         — factor de corrección del sesgo de empate (histórico ~1.05)
  home_rate         — P(1) empírico en España
  draw_rate         — P(X) empírico en España
  away_rate         — P(2) empírico en España
"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Parámetros por defecto ─────────────────────────────────────────────────────
DEFAULT_PARAMS: dict = {
    "triple_threshold": 0.42,
    "double_threshold": 0.28,
    "draw_bias":        1.05,
    "home_rate":        0.452,   # base: SP1+SP2 histórico ~2018-2026
    "draw_rate":        0.264,
    "away_rate":        0.284,
    "calibrated":       False,
    "n_matches":        0,
    "n_boletos":        0,
    "accuracy":         None,    # % acierto en boletos verificados
    "accuracy_detail":  {},      # {"simple": X, "doble": X, "triple": X}
    "last_run":         None,
    "calibration_source": "defaults",
}

# URLs de SP1 y SP2 (temporadas recientes)
_SP_URLS = [
    "https://www.football-data.co.uk/mmz4281/2526/SP1.csv",
    "https://www.football-data.co.uk/mmz4281/2526/SP2.csv",
    "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
    "https://www.football-data.co.uk/mmz4281/2425/SP2.csv",
    "https://www.football-data.co.uk/mmz4281/2324/SP1.csv",
    "https://www.football-data.co.uk/mmz4281/2324/SP2.csv",
]

_SETTINGS_KEY = "quiniela_calibration_params"
_STALE_DAYS   = 7          # recalibrar si los parámetros tienen más de 7 días


class QuinielaCalibrator:
    """
    Motor de calibración del generador de picks de La Quiniela.

    Uso típico:
        cal = QuinielaCalibrator(storage)
        params = cal.load_params()          # carga lo guardado o defaults
        params = cal.calibrate(cb=print)    # recalibra (bloquea, usar en hilo)
    """

    def __init__(self, storage) -> None:
        self.storage = storage

    # ── API pública ───────────────────────────────────────────────────────────

    def load_params(self) -> dict:
        """Carga los parámetros guardados o devuelve los defaults."""
        try:
            raw = self.storage.get_setting(_SETTINGS_KEY, "")
            if raw:
                p = json.loads(raw)
                merged = dict(DEFAULT_PARAMS)
                merged.update(p)
                return merged
        except Exception:
            logger.debug("Excepción ignorada", exc_info=True)
        return dict(DEFAULT_PARAMS)

    def is_stale(self) -> bool:
        """True si los parámetros no se han calibrado recientemente."""
        params = self.load_params()
        if not params.get("calibrated"):
            return True
        last = params.get("last_run")
        if not last:
            return True
        try:
            from datetime import datetime, timedelta
            dt = datetime.fromisoformat(last)
            return (datetime.now() - dt) > timedelta(days=_STALE_DAYS)
        except Exception:
            return True

    def calibrate(
        self,
        cb: Callable[[str], None] | None = None,
    ) -> dict:
        """
        Pipeline completo de calibración. Ejecutar en hilo de fondo.

        cb: callback(mensaje) para reportar progreso.
        Devuelve el dict de parámetros calibrados.
        """
        def _log(msg: str) -> None:
            logger.info(msg)
            if cb:
                try:
                    cb(msg)
                except Exception:
                    logger.debug("Excepción ignorada", exc_info=True)

        params = dict(DEFAULT_PARAMS)

        # ── Fase 1: datos históricos SP1/SP2 ─────────────────────────────────
        _log("📥  Descargando datos históricos SP1/SP2…")
        hist_df = self._download_sp_history(_log)

        if hist_df is not None and len(hist_df) >= 200:
            _log(f"✓  {len(hist_df)} partidos cargados — calculando distribución 1/X/2…")
            params = self._calibrate_from_df(hist_df, params, _log)
        else:
            _log("⚠  Sin datos históricos suficientes — usando priors estadísticos.")

        # ── Fase 2: boletos verificados personales ────────────────────────────
        _log("📊  Analizando boletos verificados…")
        params = self._calibrate_from_boletos(params, _log)

        # ── Meta ──────────────────────────────────────────────────────────────
        from datetime import datetime
        params["calibrated"] = True
        params["last_run"]   = datetime.now().isoformat()

        self._save_params(params)
        _log("✅  Calibración guardada.")
        return params

    # ── Descarga ──────────────────────────────────────────────────────────────

    def _download_sp_history(
        self,
        _log: Callable[[str], None],
    ) -> pd.DataFrame | None:
        """Descarga CSVs de SP1/SP2 y los concatena en un DataFrame limpio."""
        frames = []
        for url in _SP_URLS:
            try:
                from .data import fetch_csv, prepare_historic
                raw = fetch_csv(url, timeout=20)
                df  = prepare_historic(raw)
                # Solo partidos con resultado y cuotas B365
                need = ["result", "B365H", "B365D", "B365A"]
                if all(c in df.columns for c in need):
                    df = df.dropna(subset=need)
                    if len(df) > 20:
                        frames.append(df[need + ["home_team", "away_team", "date"]])
                        _log(f"  {url.split('/')[-1]}: {len(df)} filas")
            except Exception as exc:
                _log(f"  ⚠  {url.split('/')[-1]}: {exc}")

        if not frames:
            return None

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["home_team", "away_team", "date"]
        )
        return combined.reset_index(drop=True)

    # ── Calibración desde histórico ───────────────────────────────────────────

    def _calibrate_from_df(
        self,
        df: pd.DataFrame,
        params: dict,
        _log: Callable[[str], None],
    ) -> dict:
        """
        Calcula distribución empírica y optimiza thresholds con grid-search.
        """
        total = len(df)

        # 1. Distribución empírica real
        home_rate = (df["result"] == "H").sum() / total
        draw_rate = (df["result"] == "D").sum() / total
        away_rate = (df["result"] == "A").sum() / total
        params["home_rate"] = round(float(home_rate), 4)
        params["draw_rate"] = round(float(draw_rate), 4)
        params["away_rate"] = round(float(away_rate), 4)
        params["n_matches"] = total
        _log(
            f"  Distribución real: 1={home_rate:.1%}  X={draw_rate:.1%}  2={away_rate:.1%}"
        )

        # 2. Sesgo de empate: cuánto subestima el mercado los empates
        draw_rows = df[df["result"] == "D"].copy()
        draw_rows = draw_rows.dropna(subset=["B365D"])
        if len(draw_rows) >= 50:
            draw_rows["p_d_market"] = 1.0 / draw_rows["B365D"].astype(float)
            # Probabilidad media que asignó el mercado cuando hubo empate
            avg_market_draw = float(draw_rows["p_d_market"].mean())
            if avg_market_draw > 0:
                raw_bias = draw_rate / avg_market_draw
                # Clamp conservador: no exceder ±20% del default
                draw_bias = float(np.clip(raw_bias, 1.00, 1.18))
                params["draw_bias"] = round(draw_bias, 4)
                _log(
                    f"  Sesgo de empate empírico: ×{draw_bias:.3f}  "
                    f"(mercado asigna {avg_market_draw:.1%}, real {draw_rate:.1%})"
                )

        # 3. Probabilidades fair desde cuotas
        try:
            from .features import fair_probs as _fair
            def _add_fair(row):
                try:
                    ph, pd_, pa = _fair(
                        float(row["B365H"]),
                        float(row["B365D"]),
                        float(row["B365A"]),
                    )
                    return pd.Series({"ph": ph, "pd": pd_, "pa": pa})
                except Exception:
                    return pd.Series({"ph": np.nan, "pd": np.nan, "pa": np.nan})

            fair = df.apply(_add_fair, axis=1)
            df = pd.concat([df, fair], axis=1).dropna(subset=["ph", "pd", "pa"])
            _log(f"  {len(df)} partidos con probabilidades fair calculadas.")
        except Exception as exc:
            _log(f"  ⚠  fair_probs no disponible ({exc}) — usando normalización simple.")
            df = df.copy()
            df["ph"] = 1.0 / df["B365H"].astype(float)
            df["pd"] = 1.0 / df["B365D"].astype(float)
            df["pa"] = 1.0 / df["B365A"].astype(float)
            s = df["ph"] + df["pd"] + df["pa"]
            df["ph"] /= s
            df["pd"] /= s
            df["pa"] /= s
            df = df.dropna(subset=["ph", "pd", "pa"])

        if len(df) < 200:
            return params

        # 4. Grid-search de thresholds ────────────────────────────────────────
        _log("  Optimizando thresholds (grid-search)…")
        best_score   = -999.0
        best_triple  = params["triple_threshold"]
        best_double  = params["double_threshold"]
        draw_b       = params["draw_bias"]

        results_arr = df["result"].values
        ph_arr      = df["ph"].values
        pd_arr      = df["pd"].values
        pa_arr      = df["pa"].values

        for triple_th in [0.36, 0.39, 0.42, 0.45, 0.48, 0.51]:
            for double_th in [0.20, 0.23, 0.26, 0.28, 0.31, 0.34]:
                if double_th >= triple_th - 0.05:
                    continue

                hits = 0
                total_mult = 0.0
                for ph, pd_, pa, real in zip(ph_arr, pd_arr, pa_arr, results_arr):
                    pick_type, covers = _simulate_pick(
                        ph, pd_, pa, triple_th, double_th, draw_b
                    )
                    if real in covers:
                        hits += 1
                    total_mult += {"simple": 1, "doble": 2, "triple": 3}[pick_type]

                accuracy = hits / len(df)
                avg_mult = total_mult / len(df)
                # Maximizar aciertos / coste medio  →  accuracy per unit of multiplier.
                # Más principiado que la penalización arbitraria anterior (×0.08):
                # un 85% de acierto con 1.5× comb (score=0.567) es mejor que
                # 86% con 2.1× (score=0.410), porque el boleto costaría 4× más.
                score = accuracy / max(avg_mult, 0.1)

                if score > best_score:
                    best_score  = score
                    best_triple = triple_th
                    best_double = double_th

        params["triple_threshold"] = round(best_triple, 3)
        params["double_threshold"] = round(best_double, 3)
        _log(
            f"  Thresholds óptimos: triple<{best_triple}  doble>={best_double}  "
            f"score={best_score:.4f}"
        )

        # Calibración en boletos
        params["calibration_source"] = "sp_history"
        return params

    # ── Calibración desde boletos verificados ─────────────────────────────────

    def _calibrate_from_boletos(
        self,
        params: dict,
        _log: Callable[[str], None],
    ) -> dict:
        """
        Ajusta thresholds usando el historial personal de boletos verificados.
        Solo actúa con ≥ 5 boletos verificados para evitar sobreajuste.
        """
        try:
            boletos  = self.storage.load_quinielas(limit=200)
            verified = [
                b for b in boletos
                if b.get("status") == "VERIFICADA"
                and b.get("aciertos") is not None
                and b.get("partidos")
                and b.get("resultados_reales")
            ]

            n = len(verified)
            _log(f"  {n} boletos verificados encontrados.")
            params["n_boletos"] = n

            if n < 5:
                _log("  (se necesitan ≥5 para ajuste personal)")
                return params

            # Acumular estadísticas por tipo de pick
            stats: dict[str, dict[str, int]] = {
                "simple": {"hits": 0, "total": 0},
                "doble":  {"hits": 0, "total": 0},
                "triple": {"hits": 0, "total": 0},
            }
            total_hits   = 0
            total_played = 0

            for b in verified:
                partidos   = b["partidos"]
                resultados = b["resultados_reales"] or []

                for i, p in enumerate(partidos[:14]):
                    pick = p.get("pick", "")
                    real = resultados[i] if i < len(resultados) else ""
                    if not real or not pick:
                        continue

                    hit = real in pick
                    total_played += 1
                    if hit:
                        total_hits += 1

                    ptype = (
                        "triple" if len(pick) >= 3
                        else "doble" if len(pick) == 2
                        else "simple"
                    )
                    stats[ptype]["total"] += 1
                    if hit:
                        stats[ptype]["hits"] += 1

            if total_played > 0:
                params["accuracy"] = round(total_hits / total_played, 4)

            # Tasa de acierto por tipo
            detail = {}
            for ptype, s in stats.items():
                if s["total"] > 0:
                    detail[ptype] = round(s["hits"] / s["total"], 4)
            params["accuracy_detail"] = detail

            _log(
                f"  Tasa acierto: "
                + "  ".join(f"{k}={v:.1%}" for k, v in detail.items())
            )

            # ── Ajuste fino de thresholds ────────────────────────────────────
            # Principio: si los triples aciertan demasiado (>0.93), significa
            # que podemos ser más agresivos (bajar threshold → más triples solo
            # cuando realmente son inciertos). Si aciertan poco (<0.78) los
            # estamos generando donde no hacen falta.

            ts = stats["triple"]
            if ts["total"] >= 15:
                triple_acc = ts["hits"] / ts["total"]
                if triple_acc < 0.78:
                    # Demasiados triples innecesarios → subir threshold
                    adj = +0.02
                elif triple_acc > 0.93:
                    # Triple casi siempre cubre → bajar threshold
                    adj = -0.02
                else:
                    adj = 0.0
                if adj != 0.0:
                    params["triple_threshold"] = round(
                        float(np.clip(params["triple_threshold"] + adj, 0.32, 0.55)), 3
                    )
                    _log(f"  Triple threshold ajustado a {params['triple_threshold']} (acc={triple_acc:.1%})")

            ds = stats["doble"]
            if ds["total"] >= 15:
                double_acc = ds["hits"] / ds["total"]
                if double_acc < 0.68:
                    adj = +0.02
                elif double_acc > 0.88:
                    adj = -0.02
                else:
                    adj = 0.0
                if adj != 0.0:
                    params["double_threshold"] = round(
                        float(np.clip(params["double_threshold"] + adj, 0.18, 0.40)), 3
                    )
                    _log(f"  Doble threshold ajustado a {params['double_threshold']} (acc={double_acc:.1%})")

            if params.get("calibration_source") == "sp_history":
                params["calibration_source"] = "sp_history+boletos"
            else:
                params["calibration_source"] = "boletos"

        except Exception as exc:
            _log(f"  ⚠  Error en calibración personal: {exc}")

        return params

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _save_params(self, params: dict) -> None:
        try:
            self.storage.set_setting(
                _SETTINGS_KEY,
                json.dumps(params, ensure_ascii=False),
            )
        except Exception as exc:
            logger.warning("No se pudieron guardar parámetros de calibración: %s", exc)


# ── Helpers independientes ────────────────────────────────────────────────────

def _simulate_pick(
    ph: float,
    pd_: float,
    pa: float,
    triple_th: float,
    double_th: float,
    draw_b: float,
) -> tuple[str, str]:
    """
    Simula el pick con los parámetros dados.
    Devuelve (tipo, string_de_resultados_cubiertos).
    tipo: "simple" | "doble" | "triple"
    cubiertos: "H", "D", "A", "HD", "DA", "HA", "HDA"
    """
    pd_adj = min(pd_ * draw_b, 1.0)
    total  = ph + pd_adj + pa
    if total <= 0:
        return "simple", "H"
    ph_, pd__, pa_ = ph / total, pd_adj / total, pa / total

    ranking = sorted(
        [("H", ph_), ("D", pd__), ("A", pa_)],
        key=lambda x: x[1], reverse=True,
    )
    best_p   = ranking[0][1]
    second_p = ranking[1][1]
    top2     = {ranking[0][0], ranking[1][0]}

    if best_p < triple_th:
        return "triple", "HDA"

    if second_p >= double_th:
        covers = "".join(sorted(top2))
        return "doble", covers

    return "simple", ranking[0][0]
