"""Dictation history — a local SQLite log of what Svara typed, and where.

The safety net: dictated into a chat that ate the message, closed the window
too soon, crashed mid-flow — the text is still here. 100% local
(base_dir()/history.db); retention is the user's call: keep forever (default),
auto-expire after N hours, or disable entirely.
"""

import logging
import sqlite3
import threading
import time

log = logging.getLogger(__name__)


class History:
    def __init__(self, hist_cfg: dict | None):
        cfg = hist_cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.retention_hours = float(cfg.get("retention_hours", 0) or 0)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if not self.enabled:
            return
        try:
            from .paths import base_dir
            self._conn = sqlite3.connect(str(base_dir() / "history.db"),
                                         check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS dictations ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " ts REAL NOT NULL,"
                " app TEXT DEFAULT '',"
                " kind TEXT DEFAULT 'dictation',"
                " text TEXT NOT NULL)")
            self._conn.commit()
            self.prune()
        except sqlite3.Error:
            log.warning("history database unavailable — continuing without",
                        exc_info=True)
            self._conn = None

    def record(self, text: str, app: str = "", kind: str = "dictation"):
        if not self._conn or not (text or "").strip():
            return
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO dictations (ts, app, kind, text) VALUES (?,?,?,?)",
                    (time.time(), app or "", kind, text))
                self._conn.commit()
        except sqlite3.Error:
            log.debug("history record failed", exc_info=True)

    def last(self) -> str | None:
        """Most recent dictated text (not polish-originals/recoveries)."""
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT text FROM dictations WHERE kind='dictation' "
                    "ORDER BY id DESC LIMIT 1").fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def recent(self, n: int = 100, query: str | None = None) -> list[tuple]:
        """[(ts, app, kind, text), …] newest first, optionally filtered."""
        if not self._conn:
            return []
        try:
            with self._lock:
                if query:
                    rows = self._conn.execute(
                        "SELECT ts, app, kind, text FROM dictations "
                        "WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
                        (f"%{query}%", n)).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT ts, app, kind, text FROM dictations "
                        "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
            return rows
        except sqlite3.Error:
            return []

    def prune(self):
        """Apply the retention policy (0 = keep forever)."""
        if not self._conn or self.retention_hours <= 0:
            return
        try:
            cutoff = time.time() - self.retention_hours * 3600
            with self._lock:
                self._conn.execute("DELETE FROM dictations WHERE ts < ?",
                                   (cutoff,))
                self._conn.commit()
        except sqlite3.Error:
            log.debug("history prune failed", exc_info=True)

    def clear(self):
        if not self._conn:
            return
        try:
            with self._lock:
                self._conn.execute("DELETE FROM dictations")
                self._conn.commit()
            log.info("history cleared")
        except sqlite3.Error:
            log.debug("history clear failed", exc_info=True)

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
