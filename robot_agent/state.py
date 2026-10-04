from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RobotState:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS deliveries (
                    order_number TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    pdf_path TEXT NOT NULL DEFAULT '',
                    sha256 TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def mark(self, order_number: str, status: str, *, pdf_path: str = "", sha256: str = "", error: str = ""):
        with self._connect() as con:
            current = con.execute(
                "SELECT attempts FROM deliveries WHERE order_number = ?",
                (order_number,),
            ).fetchone()
            attempts = (int(current["attempts"]) if current else 0) + (1 if status in {"EXPORTANDO", "ENVIANDO"} else 0)
            con.execute("""
                INSERT INTO deliveries(order_number,status,pdf_path,sha256,attempts,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(order_number) DO UPDATE SET
                    status=excluded.status,
                    pdf_path=CASE WHEN excluded.pdf_path <> '' THEN excluded.pdf_path ELSE deliveries.pdf_path END,
                    sha256=CASE WHEN excluded.sha256 <> '' THEN excluded.sha256 ELSE deliveries.sha256 END,
                    attempts=excluded.attempts,
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
            """, (order_number, status, pdf_path, sha256, attempts, error, utc_now()))
            con.commit()
