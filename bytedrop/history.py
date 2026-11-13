"""SQLite transfer history store in %APPDATA%\\ByteDrop\\bytedrop_history.db."""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("bytedrop.history")


class HistoryStore:
    """Thread-safe SQLite history repository storing filename, category, size, direction, duration, and avg_speed."""

    def __init__(self, appdata_dir: Path) -> None:
        self.db_path = appdata_dir / "bytedrop_history.db"
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    category TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    expected_size INTEGER NOT NULL DEFAULT 0,
                    is_folder INTEGER NOT NULL DEFAULT 0,
                    direction TEXT NOT NULL,
                    duration_sec REAL NOT NULL DEFAULT 0.0,
                    avg_speed REAL NOT NULL DEFAULT 0.0,
                    timestamp TEXT NOT NULL
                )"""
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(transfers);").fetchall()}
            if "duration_sec" not in cols:
                conn.execute("ALTER TABLE transfers ADD COLUMN duration_sec REAL NOT NULL DEFAULT 0.0;")
            if "avg_speed" not in cols:
                conn.execute("ALTER TABLE transfers ADD COLUMN avg_speed REAL NOT NULL DEFAULT 0.0;")
            if "expected_size" not in cols:
                conn.execute("ALTER TABLE transfers ADD COLUMN expected_size INTEGER NOT NULL DEFAULT 0;")
            if "is_folder" not in cols:
                conn.execute("ALTER TABLE transfers ADD COLUMN is_folder INTEGER NOT NULL DEFAULT 0;")

            # G6 & H4: One-time schema migration guarded by PRAGMA user_version
            ver_row = conn.execute("PRAGMA user_version;").fetchone()
            user_version = int(ver_row[0]) if ver_row else 0
            if user_version < 2:
                conn.execute(
                    """DELETE FROM transfers
                       WHERE size <= 0
                         AND (
                             expected_size > 0
                             OR is_folder = 1
                             OR category = 'Archives'
                             OR filename LIKE '%.zip'
                         )"""
                )
            if user_version < 3:
                conn.execute("PRAGMA user_version = 3;")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_transfers_id_desc ON transfers(id DESC);")
            conn.commit()

    def record(
        self,
        filename: str,
        category: str,
        size: int,
        direction: str,
        duration_sec: float = 0.0,
        avg_speed: float = 0.0,
        expected_size: int | None = None,
        state: str = "done",
        is_folder: bool = False,
    ) -> dict[str, Any] | None:
        actual_size = int(size)
        exp_size = actual_size if expected_size is None else int(expected_size)
        norm_state = str(state or "done").lower()

        # G6 & H4: Never record a history entry for cancelled, expired, failed, or 0-byte-by-error transfers.
        # Real 0-byte files (expected_size == 0 and is_folder is False), even if named .zip or in Archives, are recorded.
        if norm_state not in ("done", "completed"):
            logger.debug("Skipping history record for non-completed transfer %s (state=%s)", filename, state)
            return None
        if actual_size < 0 or (exp_size > 0 and actual_size < exp_size):
            logger.warning(
                "Skipping incomplete history record for %s (size=%d, expected=%d)",
                filename,
                actual_size,
                exp_size,
            )
            return None
        if actual_size == 0 and (exp_size > 0 or bool(is_folder)):
            logger.warning("Skipping bogus 0-byte folder/expected-nonzero history record for %s", filename)
            return None

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dur = round(max(0.0, float(duration_sec)), 2)
        spd = round(max(0.0, float(avg_speed)), 1)
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO transfers (filename, category, size, expected_size, is_folder, direction, duration_sec, avg_speed, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, category, actual_size, exp_size, 1 if is_folder else 0, direction, dur, spd, ts),
            )
            row_id = cur.lastrowid or 0
            conn.commit()
        return {
            "id": row_id,
            "filename": filename,
            "category": category,
            "size": actual_size,
            "expected_size": exp_size,
            "is_folder": bool(is_folder),
            "direction": direction,
            "duration_sec": dur,
            "avg_speed": spd,
            "timestamp": ts,
        }

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, filename, category, size, expected_size, is_folder, direction, duration_sec, avg_speed, timestamp
                   FROM transfers ORDER BY id DESC LIMIT ?""",
                (max(1, min(limit, 500)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM transfers;")
            conn.commit()
