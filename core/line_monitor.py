# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
line_monitor.py — Monitor de líneas en tiempo real con detección de steam.

Polling de Odds API cada N minutos → snapshots SQLite → detección de steam
(caída >2.5% de probabilidad implícita en un poll) → alerta UI + Telegram.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

STEAM_THRESHOLD    = 0.025   # ≥2.5% shift = steam (dinero sharp)
LINE_MOVE_THRESHOLD = 0.015  # ≥1.5% shift = movimiento notable
DEFAULT_POLL_SECS  = 300     # poll cada 5 minutos


@dataclass
class OddsSnapshot:
    match_id:      str
    home_team:     str
    away_team:     str
    div:           str
    commence_time: str
    bookmaker:     str
    home_odds:     float
    draw_odds:     float
    away_odds:     float
    over25_odds:   float
    under25_odds:  float
    timestamp:     str


@dataclass
class LineAlert:
    alert_type:  str        # STEAM | LINE_MOVE | VALUE_SHIFT
    match_id:    str
    home_team:   str
    away_team:   str
    div:         str
    direction:   str        # HOME | DRAW | AWAY
    old_prob:    float
    new_prob:    float
    prob_shift:  float      # positivo = equipo más probable ahora
    old_odds:    float
    new_odds:    float
    bookmaker:   str
    detected_at: str
    message:     str

    @property
    def emoji(self) -> str:
        return "🔴" if self.alert_type == "STEAM" else "🟡"


class LineMonitor:
    """
    Monitor de líneas en tiempo real.

    Uso básico:
        monitor = LineMonitor(api_key, div_codes, storage, on_alert=callback)
        monitor.start()
        ...
        monitor.stop()
    """

    def __init__(
        self,
        api_key:       str,
        div_codes:     list[str],
        storage,
        on_alert:      Optional[Callable[[LineAlert], None]] = None,
        poll_interval: int = DEFAULT_POLL_SECS,
    ) -> None:
        self.api_key       = api_key
        self.div_codes     = div_codes
        self.storage       = storage
        self.on_alert      = on_alert
        self.poll_interval = poll_interval

        self._running   = False
        self._thread:   Optional[threading.Thread] = None
        self._lock      = threading.Lock()
        self._alerts:   list[LineAlert] = []
        self._snapshots: dict[str, OddsSnapshot] = {}   # match_id → latest
        self._last_poll: Optional[str] = None

        self._seen_value_picks:    set[str] = set()
        self.value_alerts_enabled: bool     = False
        self.value_edge_threshold: float    = 0.05

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("LineMonitor iniciado (poll cada %ds).", self.poll_interval)

    def stop(self) -> None:
        self._running = False
        logger.info("LineMonitor detenido.")

    def is_running(self) -> bool:
        return self._running

    def last_poll_time(self) -> Optional[str]:
        return self._last_poll

    # ── Acceso a estado ───────────────────────────────────────────────────────

    def get_alerts(self, max_items: int = 100) -> list[LineAlert]:
        with self._lock:
            return list(self._alerts[-max_items:])

    def get_snapshots(self) -> dict[str, OddsSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    def poll_once(self) -> list[LineAlert]:
        """Poll manual sin iniciar el hilo de fondo."""
        return self._poll()

    # ── Alertas de valor ──────────────────────────────────────────────────────

    def check_value_alerts(
        self,
        picks: list[dict],
        edge_threshold: float = 0.05,
        notify_fn: Callable[[str], None] | None = None,
    ) -> list[dict]:
        """
        Compara picks actuales con los últimos conocidos.
        Si un pick NUEVO aparece con edge > edge_threshold → llama notify_fn.
        Retorna lista de picks que son "nuevos" con alto valor.
        """
        risk_icons = {"VERDE": "⚡ VERDE", "AMARILLO": "⚠️ AMARILLO", "ROJO": "🔴 ROJO"}
        new_high_value: list[dict] = []

        for pick in picks:
            edge = float(pick.get("edge", 0) or 0)
            if edge < edge_threshold:
                continue

            home = str(pick.get("home_team", "") or "").strip()
            away = str(pick.get("away_team", "") or "").strip()
            p    = str(pick.get("pick", "") or "").strip()
            key  = f"{home}_{away}_{p}"

            if key in self._seen_value_picks:
                continue

            self._seen_value_picks.add(key)
            new_high_value.append(pick)

            if notify_fn is not None:
                odds = float(pick.get("odds", 0) or 0)
                ev   = float(pick.get("ev", 0) or 0)
                rel  = int(pick.get("reliability_score", 0) or 0)
                risk = str(pick.get("risk_light", "") or "")

                msg = (
                    f"🎯 NUEVA OPORTUNIDAD DE VALOR\n\n"
                    f"{home} vs {away}\n"
                    f"  📌 Pick: {p} @ {odds:.2f}\n"
                    f"  📈 Edge: {edge:+.1%}  EV: {ev:+.1%}\n"
                    f"  🔒 Fiabilidad: {rel}/99  {risk_icons.get(risk, '')}"
                )
                try:
                    notify_fn(msg)
                except Exception as exc:
                    logger.warning("check_value_alerts notify_fn error: %s", exc)

        return new_high_value

    def reset_value_alerts(self) -> None:
        """Limpia el set de picks ya notificados (llamar al inicio de nuevo análisis)."""
        self._seen_value_picks.clear()

    # ── Bucle interno ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        self._poll()
        while self._running:
            time.sleep(self.poll_interval)
            if self._running:
                self._poll()

    def _poll(self) -> list[LineAlert]:
        from .odds_api import fetch_odds_fixtures

        try:
            df, _ = fetch_odds_fixtures(
                api_key=self.api_key,
                div_codes=self.div_codes,
                bookmaker="pinnacle",
                regions="eu",
            )
        except Exception as exc:
            logger.warning("LineMonitor poll error: %s", exc)
            return []

        if df.empty:
            return []

        ts        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_alerts: list[LineAlert] = []

        for _, row in df.iterrows():
            snap = _row_to_snapshot(row, ts)
            if snap is None:
                continue

            # Guardar en SQLite
            try:
                self.storage.save_odds_snapshot(snap)
            except Exception:
                pass

            # Detectar movimiento vs snapshot anterior
            with self._lock:
                prev = self._snapshots.get(snap.match_id)
                self._snapshots[snap.match_id] = snap

            if prev:
                alerts = _detect_movement(prev, snap)
                new_alerts.extend(alerts)

        with self._lock:
            self._last_poll = ts  # bug fix: bajo el lock, consistente con last_poll_time()

        if new_alerts:
            with self._lock:
                self._alerts.extend(new_alerts)
                if len(self._alerts) > 300:
                    self._alerts = self._alerts[-300:]

            for alert in new_alerts:
                logger.info(
                    "LineAlert [%s] %s vs %s — %s %+.1f%%",
                    alert.alert_type, alert.home_team, alert.away_team,
                    alert.direction, alert.prob_shift * 100,
                )
                if self.on_alert:
                    try:
                        self.on_alert(alert)
                    except Exception:
                        pass

        return new_alerts


# ── Funciones puras ───────────────────────────────────────────────────────────

def _row_to_snapshot(row: pd.Series, ts: str) -> Optional[OddsSnapshot]:
    home = str(row.get("HomeTeam") or "").strip()
    away = str(row.get("AwayTeam") or "").strip()
    div  = str(row.get("Div") or "").strip()
    if not home or not away:
        return None

    def _f(k: str) -> float:
        v = row.get(k)
        try:
            f = float(v)
            return f if f > 1.0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    return OddsSnapshot(
        match_id=f"{div}::{home}::{away}",
        home_team=home,
        away_team=away,
        div=div,
        commence_time=str(row.get("Date") or ""),
        bookmaker="pinnacle",
        home_odds=_f("B365H"),
        draw_odds=_f("B365D"),
        away_odds=_f("B365A"),
        over25_odds=_f("B365O25"),
        under25_odds=_f("B365U25"),
        timestamp=ts,
    )


def _fair_triple(h: float, d: float, a: float) -> tuple[float, float, float]:
    if h <= 1 or d <= 1 or a <= 1:
        return 0.0, 0.0, 0.0
    inv = [1 / h, 1 / d, 1 / a]
    s   = sum(inv)
    return inv[0] / s, inv[1] / s, inv[2] / s


def _detect_movement(prev: OddsSnapshot, curr: OddsSnapshot) -> list[LineAlert]:
    alerts: list[LineAlert] = []

    old_p = _fair_triple(prev.home_odds, prev.draw_odds, prev.away_odds)
    new_p = _fair_triple(curr.home_odds, curr.draw_odds, curr.away_odds)

    directions     = ["HOME", "DRAW", "AWAY"]
    old_odds_list  = [prev.home_odds, prev.draw_odds, prev.away_odds]
    new_odds_list  = [curr.home_odds, curr.draw_odds, curr.away_odds]

    for i, direction in enumerate(directions):
        if old_p[i] <= 0 or new_p[i] <= 0:
            continue
        shift     = new_p[i] - old_p[i]
        abs_shift = abs(shift)

        if abs_shift >= STEAM_THRESHOLD:
            atype = "STEAM"
        elif abs_shift >= LINE_MOVE_THRESHOLD:
            atype = "LINE_MOVE"
        else:
            continue

        emoji = "🔴" if atype == "STEAM" else "🟡"
        dir_emoji = {"HOME": "🏠", "DRAW": "➕", "AWAY": "✈️"}
        msg = (
            f"{emoji} {atype}: {curr.home_team} vs {curr.away_team} "
            f"{dir_emoji[direction]} {direction} "
            f"{old_odds_list[i]:.2f}→{new_odds_list[i]:.2f} "
            f"({shift * 100:+.1f}%)"
        )

        alerts.append(LineAlert(
            alert_type=atype,
            match_id=curr.match_id,
            home_team=curr.home_team,
            away_team=curr.away_team,
            div=curr.div,
            direction=direction,
            old_prob=old_p[i],
            new_prob=new_p[i],
            prob_shift=shift,
            old_odds=old_odds_list[i],
            new_odds=new_odds_list[i],
            bookmaker=curr.bookmaker,
            detected_at=curr.timestamp,
            message=msg,
        ))

    return alerts
