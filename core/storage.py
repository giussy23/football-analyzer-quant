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
                "SELECT payload_json FROM combo_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

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

    def clear_combos(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM combo_history")
            con.commit()
        logger.info("Historial de combinadas eliminado.")
