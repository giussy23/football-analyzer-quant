# © 2026 Francesco Giuseppe Manolache. Todos los derechos reservados.
# AlphaBet v15.0 — Software de uso privado. Prohibida su distribución sin autorización expresa.
"""
storage.py — Persistencia SQLite: settings, historial de combinadas, simulaciones.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DB_FILE

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, db_file: str = DB_FILE) -> None:
        self.db_file = db_file
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_file)

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS combo_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at   TEXT,
                    payload_json TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS sim_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at   TEXT,
                    payload_json TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS model_picks (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    saved_at     TEXT,
                    date         TEXT,
                    home_team    TEXT,
                    away_team    TEXT,
                    league       TEXT,
                    pick         TEXT,
                    odds         REAL,
                    edge         REAL,
                    model_prob   REAL,
                    bankroll_pct REAL,
                    status       TEXT DEFAULT 'PENDING',
                    pnl          REAL DEFAULT 0.0,
                    settled_at   TEXT,
                    signal       TEXT DEFAULT 'VERDE'
                )
            """)
            # Migración silenciosa: añadir columnas si la tabla existía sin ellas
            for _col, _col_type, _default in [
                ("signal",       "TEXT", "DEFAULT 'VERDE'"),
                ("closing_odds", "REAL", ""),
                ("clv",          "REAL", ""),
            ]:
                try:
                    con.execute(
                        f"ALTER TABLE model_picks ADD COLUMN {_col} {_col_type} {_default}".strip()
                    )
                except Exception:
                    pass
            con.execute("""
                CREATE TABLE IF NOT EXISTS odds_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id     TEXT,
                    home_team    TEXT,
                    away_team    TEXT,
                    div          TEXT,
                    commence_time TEXT,
                    bookmaker    TEXT,
                    home_odds    REAL,
                    draw_odds    REAL,
                    away_odds    REAL,
                    over25_odds  REAL,
                    under25_odds REAL,
                    timestamp    TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS injury_overrides (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id     TEXT UNIQUE,
                    payload_json TEXT,
                    updated_at   TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS quiniela_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    saved_at    TEXT,
                    jornada     TEXT,
                    fecha       TEXT,
                    picks_json  TEXT,
                    coste       REAL,
                    prob        REAL,
                    status      TEXT DEFAULT 'PENDIENTE',
                    aciertos    INTEGER DEFAULT NULL
                )
            """)
            # ── Betfair Exchange — registro de apuestas colocadas ─────────────
            con.execute("""
                CREATE TABLE IF NOT EXISTS betfair_bets (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    placed_at      TEXT,
                    market_id      TEXT,
                    selection_id   INTEGER,
                    event_name     TEXT,
                    pick           TEXT,
                    stake          REAL,
                    requested_price REAL,
                    average_price  REAL,
                    size_matched   REAL,
                    bet_id         TEXT,
                    status         TEXT DEFAULT 'PLACED',
                    result         TEXT DEFAULT NULL,
                    pnl            REAL DEFAULT NULL,
                    settled_at     TEXT DEFAULT NULL
                )
            """)
            con.commit()
        logger.debug("Base de datos inicializada en %s", self.db_file)

    # ── Settings ───────────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO settings(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            con.commit()

    def get_all_settings(self) -> dict[str, str]:
        with self._connect() as con:
            rows = con.execute("SELECT key, value FROM settings").fetchall()
        return dict(rows)

    # ── Combo history ──────────────────────────────────────────────────────────

    def save_combo(self, payload: dict) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO combo_history(created_at, payload_json) VALUES(?, ?)",
                (payload.get("timestamp"), json.dumps(payload, ensure_ascii=False)),
            )
            con.commit()

    def load_combos(self, limit: int = 200) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, payload_json FROM combo_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for db_id, json_str in rows:
            d = json.loads(json_str)
            d["_db_id"] = db_id
            result.append(d)
        return result

    def update_combo_by_id(self, db_id: int, payload: dict) -> None:
        clean = {k: v for k, v in payload.items() if k != "_db_id"}
        with self._connect() as con:
            con.execute(
                "UPDATE combo_history SET payload_json = ? WHERE id = ?",
                (json.dumps(clean, ensure_ascii=False), db_id),
            )
            con.commit()

    def delete_combo_by_id(self, db_id: int) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM combo_history WHERE id = ?", (db_id,))
            con.commit()

    def replace_latest_combo(self, payload: dict) -> None:
        with self._connect() as con:
            row = con.execute(
                "SELECT id FROM combo_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                con.execute(
                    "UPDATE combo_history SET created_at = ?, payload_json = ? WHERE id = ?",
                    (
                        payload.get("timestamp"),
                        json.dumps(payload, ensure_ascii=False),
                        row[0],
                    ),
                )
            else:
                con.execute(
                    "INSERT INTO combo_history(created_at, payload_json) VALUES(?, ?)",
                    (payload.get("timestamp"), json.dumps(payload, ensure_ascii=False)),
                )
            con.commit()

    # ── Simulation history ─────────────────────────────────────────────────────

    def save_sim(self, payload: dict) -> int:
        """Guarda una simulación y devuelve su ID de base de datos."""
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO sim_history(created_at, payload_json) VALUES(?, ?)",
                (payload.get("timestamp"), json.dumps(payload, ensure_ascii=False)),
            )
            con.commit()
            return cur.lastrowid

    def load_sims(self, limit: int = 200) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, payload_json FROM sim_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for db_id, json_str in rows:
            d = json.loads(json_str)
            d["_db_id"] = db_id
            result.append(d)
        return result

    def update_sim_status(self, db_id: int, status: str, pnl: float) -> None:
        """Marca una simulación como WIN o LOSS y actualiza el PnL."""
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM sim_history WHERE id = ?", (db_id,)
            ).fetchone()
            if not row:
                return
            d = json.loads(row[0])
            d["status"]     = status
            d["pnl"]        = round(pnl, 2)
            d["settled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            con.execute(
                "UPDATE sim_history SET payload_json = ? WHERE id = ?",
                (json.dumps(d, ensure_ascii=False), db_id),
            )
            con.commit()

    def update_sim_full(self, db_id: int, payload: dict) -> None:
        """Reemplaza el payload completo de una simulación (útil para acumuladores)."""
        with self._connect() as con:
            # Nunca serializar el campo interno _db_id
            clean = {k: v for k, v in payload.items() if k != "_db_id"}
            con.execute(
                "UPDATE sim_history SET payload_json = ? WHERE id = ?",
                (json.dumps(clean, ensure_ascii=False), db_id),
            )
            con.commit()

    def clear_combos(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM combo_history")
            con.commit()
        logger.info("Historial de combinadas eliminado.")

    # ── Model picks ────────────────────────────────────────────────────────────

    def pick_exists(self, home_team: str, away_team: str, date, pick: str) -> bool:
        """Comprueba si ya existe un pick idéntico (deduplicación).

        Bug fix: extrae YYYY-MM-DD con regex para manejar pd.Timestamp,
        ISO 8601 con zona horaria, Unix timestamps, etc.
        """
        import re
        date_str = str(date)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", date_str)
        date_prefix = m.group(1) if m else date_str[:10]
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id FROM model_picks
                WHERE home_team = ? AND away_team = ?
                  AND date LIKE ? AND pick = ?
                LIMIT 1
                """,
                (home_team, away_team, date_prefix + "%", pick),
            ).fetchone()
        return row is not None

    def save_model_pick(self, data: dict) -> int:
        """Inserta un nuevo pick de modelo y devuelve su id."""
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO model_picks
                    (saved_at, date, home_team, away_team, league, pick,
                     odds, edge, model_prob, bankroll_pct, status, pnl, settled_at, signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("saved_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    data.get("date"),
                    data.get("home_team"),
                    data.get("away_team"),
                    data.get("league"),
                    data.get("pick"),
                    data.get("odds"),
                    data.get("edge"),
                    data.get("model_prob"),
                    data.get("bankroll_pct"),
                    data.get("status", "PENDING"),
                    data.get("pnl", 0.0),
                    data.get("settled_at"),
                    data.get("signal", "VERDE"),
                ),
            )
            con.commit()
            return cur.lastrowid

    def load_model_picks(self, limit: int = 500, status: str | None = None) -> list[dict]:
        """Carga picks del modelo (filtrado opcional por status)."""
        with self._connect() as con:
            if status is not None:
                rows = con.execute(
                    """
                    SELECT id, saved_at, date, home_team, away_team, league, pick,
                           odds, edge, model_prob, bankroll_pct, status, pnl, settled_at,
                           COALESCE(signal, 'VERDE') as signal,
                           closing_odds, clv
                    FROM model_picks
                    WHERE status = ?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT id, saved_at, date, home_team, away_team, league, pick,
                           odds, edge, model_prob, bankroll_pct, status, pnl, settled_at,
                           COALESCE(signal, 'VERDE') as signal,
                           closing_odds, clv
                    FROM model_picks
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        cols = (
            "id", "saved_at", "date", "home_team", "away_team", "league", "pick",
            "odds", "edge", "model_prob", "bankroll_pct", "status", "pnl", "settled_at",
            "signal", "closing_odds", "clv",
        )
        return [dict(zip(cols, row)) for row in rows]

    def update_pick_clv(self, pick_id: int, closing_odds: float, clv: float) -> None:
        """Actualiza closing_odds y CLV de un pick ya liquidado."""
        with self._connect() as con:
            con.execute(
                "UPDATE model_picks SET closing_odds=?, clv=? WHERE id=?",
                (closing_odds, clv, pick_id),
            )
            con.commit()

    def update_pick_result(self, pick_id: int, status: str, pnl: float) -> None:
        """Actualiza el status y pnl de un pick y marca la fecha de liquidación."""
        with self._connect() as con:
            con.execute(
                """
                UPDATE model_picks
                SET status = ?, pnl = ?, settled_at = ?
                WHERE id = ?
                """,
                (status, round(pnl, 4), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pick_id),
            )
            con.commit()

    def delete_model_pick(self, pick_id: int) -> None:
        """Borra un pick por id."""
        with self._connect() as con:
            con.execute("DELETE FROM model_picks WHERE id = ?", (pick_id,))
            con.commit()

    # ── Betfair Exchange bets ─────────────────────────────────────────────────

    def save_betfair_bet(self, bet: dict) -> int:
        """
        Persiste una apuesta colocada en Betfair.

        Campos esperados en ``bet``:
            market_id, selection_id, event_name, pick, stake,
            requested_price, average_price, size_matched, bet_id, status
        """
        from datetime import datetime as _dt
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO betfair_bets
                    (placed_at, market_id, selection_id, event_name, pick,
                     stake, requested_price, average_price, size_matched,
                     bet_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _dt.utcnow().isoformat(),
                    bet.get("market_id", ""),
                    bet.get("selection_id", 0),
                    bet.get("event_name", ""),
                    bet.get("pick", ""),
                    float(bet.get("stake", 0)),
                    float(bet.get("requested_price", 0)),
                    float(bet.get("average_price", 0)),
                    float(bet.get("size_matched", 0)),
                    str(bet.get("bet_id", "")),
                    bet.get("status", "PLACED"),
                ),
            )
            con.commit()
            return cur.lastrowid

    def load_betfair_bets(self, limit: int = 200) -> list[dict]:
        """Devuelve las apuestas Betfair más recientes (descendente)."""
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, placed_at, event_name, pick, stake,
                       requested_price, average_price, size_matched,
                       bet_id, status, result, pnl, settled_at, market_id, selection_id
                FROM betfair_bets
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            cols = ["id", "placed_at", "event_name", "pick", "stake",
                    "requested_price", "average_price", "size_matched",
                    "bet_id", "status", "result", "pnl", "settled_at",
                    "market_id", "selection_id"]
            return [dict(zip(cols, r)) for r in rows]

    def settle_betfair_bet(self, bet_id_str: str, result: str, pnl: float) -> None:
        """Liquida una apuesta por su bet_id de Betfair."""
        from datetime import datetime as _dt
        with self._connect() as con:
            con.execute(
                """
                UPDATE betfair_bets
                SET result=?, pnl=?, settled_at=?, status='SETTLED'
                WHERE bet_id=?
                """,
                (result, pnl, _dt.utcnow().isoformat(), bet_id_str),
            )
            con.commit()

    # ── Odds history (line monitor) ────────────────────────────────────────────

    def save_odds_snapshot(self, snap) -> None:
        """Guarda un snapshot de cuotas en la tabla odds_history."""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO odds_history
                    (match_id, home_team, away_team, div, commence_time, bookmaker,
                     home_odds, draw_odds, away_odds, over25_odds, under25_odds, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snap.match_id, snap.home_team, snap.away_team, snap.div,
                    snap.commence_time, snap.bookmaker,
                    snap.home_odds, snap.draw_odds, snap.away_odds,
                    snap.over25_odds, snap.under25_odds, snap.timestamp,
                ),
            )
            con.commit()

    def load_odds_history(
        self, match_id: str | None = None, limit: int = 200
    ) -> list[dict]:
        """Carga snapshots de odds (opcionalmente filtrado por match_id)."""
        cols = (
            "id", "match_id", "home_team", "away_team", "div", "commence_time",
            "bookmaker", "home_odds", "draw_odds", "away_odds",
            "over25_odds", "under25_odds", "timestamp",
        )
        with self._connect() as con:
            if match_id:
                rows = con.execute(
                    "SELECT " + ", ".join(cols) +
                    " FROM odds_history WHERE match_id = ? ORDER BY id DESC LIMIT ?",
                    (match_id, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT " + ", ".join(cols) +
                    " FROM odds_history ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def purge_old_odds_history(self, keep_days: int = 7) -> None:
        """Elimina snapshots de más de keep_days días para no crecer indefinidamente."""
        with self._connect() as con:
            con.execute(
                "DELETE FROM odds_history WHERE timestamp < datetime('now', ?)",
                (f"-{keep_days} days",),
            )
            con.commit()

    # ── Injury overrides ───────────────────────────────────────────────────────

    def save_injury_override(self, match_id: str, absences_json: str) -> None:
        """Guarda (o reemplaza) las bajas para un partido concreto."""
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO injury_overrides(match_id, payload_json, updated_at)
                VALUES(?, ?, datetime('now'))
                ON CONFLICT(match_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at   = excluded.updated_at
                """,
                (match_id, absences_json),
            )
            con.commit()

    def load_injury_override(self, match_id: str) -> str | None:
        """Carga el JSON de bajas de un partido o None si no existe."""
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM injury_overrides WHERE match_id = ?",
                (match_id,),
            ).fetchone()
        return row[0] if row else None

    def delete_injury_override(self, match_id: str) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM injury_overrides WHERE match_id = ?", (match_id,)
            )
            con.commit()

    # ── Quiniela history ───────────────────────────────────────────────────────

    def save_quiniela(self, payload: dict) -> int:
        """Guarda un boleto de quiniela y devuelve su ID de base de datos."""
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO quiniela_history(saved_at, jornada, fecha, picks_json, coste, prob, status)
                VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE')
                """,
                (
                    payload.get("saved_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    str(payload.get("jornada", "?")),
                    str(payload.get("fecha", "")),
                    json.dumps(payload, ensure_ascii=False),
                    float(payload.get("coste", 0.0)),
                    float(payload.get("prob", 0.0)),
                ),
            )
            con.commit()
            return cur.lastrowid

    def load_quinielas(self, limit: int = 50) -> list[dict]:
        """Carga boletos guardados (más recientes primero)."""
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, picks_json FROM quiniela_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for db_id, json_str in rows:
            try:
                d = json.loads(json_str)
            except Exception:
                d = {}
            d["_db_id"] = db_id
            result.append(d)
        return result

    def update_quiniela_result(
        self,
        qid: int,
        aciertos: int,
        categoria: str,
        resultados: list,
    ) -> None:
        """Actualiza el resultado de un boleto tras verificación."""
        with self._connect() as con:
            row = con.execute(
                "SELECT picks_json FROM quiniela_history WHERE id = ?", (qid,)
            ).fetchone()
            if not row:
                return
            try:
                d = json.loads(row[0])
            except Exception:
                d = {}
            d["aciertos"]        = aciertos
            d["categoria"]       = categoria
            d["resultados_reales"] = resultados
            d["status"]          = "VERIFICADA"
            con.execute(
                "UPDATE quiniela_history SET picks_json = ?, status = ?, aciertos = ? WHERE id = ?",
                (json.dumps(d, ensure_ascii=False), "VERIFICADA", aciertos, qid),
            )
            con.commit()

    def delete_quiniela(self, qid: int) -> None:
        """Elimina un boleto del historial."""
        with self._connect() as con:
            con.execute("DELETE FROM quiniela_history WHERE id = ?", (qid,))
            con.commit()
