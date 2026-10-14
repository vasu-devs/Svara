"""Dictation history — a local SQLite log of what Svara typed, and where.

The safety net: dictated into a chat that ate the message, closed the window
too soon, crashed mid-flow — the text is still here. 100% local
(base_dir()/history.db); retention is the user's call: keep forever (default),
auto-expire after N hours, or disable entirely.
"""

import logging
import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class History:
    def _retained_after(self) -> float:
        return time.time() - self.retention_hours * 3600 if self.retention_hours > 0 else -1e308

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
            self._conn.execute("CREATE INDEX IF NOT EXISTS history_kind_ts ON dictations(kind, ts)")
            self._conn.create_function("svara_words", 1, lambda text: len((text or "").split()))
            self._conn.commit()
            self.prune()
        except sqlite3.Error:
            log.warning("history database unavailable — continuing without",
                        exc_info=True)
            self._conn = None

    def record(self, text: str, app: str = "", kind: str = "dictation"):
        self.prune()
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
        self.prune()
        if not self._conn:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT text FROM dictations WHERE kind='dictation' AND ts>=? "
                    "ORDER BY id DESC LIMIT 1", (self._retained_after(),)).fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def recent(self, n: int = 100, query: str | None = None) -> list[tuple]:
        """[(ts, app, kind, text), …] newest first, optionally filtered."""
        self.prune()
        if not self._conn:
            return []
        try:
            with self._lock:
                if query:
                    rows = self._conn.execute(
                        "SELECT ts, app, kind, text FROM dictations "
                        "WHERE ts>=? AND instr(lower(text), lower(?)) > 0 ORDER BY id DESC LIMIT ?",
                        (self._retained_after(), query, max(0, min(int(n), 10000)))).fetchall()
                else:
                    rows = self._conn.execute(
                        "SELECT ts, app, kind, text FROM dictations "
                        "WHERE ts>=? ORDER BY id DESC LIMIT ?",
                        (self._retained_after(), max(0, min(int(n), 10000)))).fetchall()
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

    def usage(self, days: int = 30, *, now: float | None = None) -> dict:
        """Aggregate retained dictations only; no transcript text in the result.

        Day boundaries are UTC. Counts are whitespace-delimited words rather
        than a claim of language-independent tokenization or time saved.
        """
        days = max(1, min(int(days), 365))
        end = time.time() if now is None else now
        today = datetime.fromtimestamp(end, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)
        daily = { (start + timedelta(days=i)).strftime("%Y-%m-%d"):
                  {"dictations": 0, "words": 0} for i in range(days)}
        result = {"days": days, "timezone": "UTC", "dictations": 0, "words": 0,
                  "active_days": 0, "daily": daily, "apps": []}
        self.prune()
        if not self._conn:
            return result
        try:
            with self._lock:
                grouped = self._conn.execute(
                    "SELECT strftime('%Y-%m-%d', ts, 'unixepoch'), app, COUNT(*), "
                    "SUM(svara_words(text)) FROM dictations "
                    "WHERE kind='dictation' AND ts>=? AND ts<=? GROUP BY 1, 2",
                    (max(start.timestamp(), self._retained_after()), end)).fetchall()
            apps = {}
            for date, app, count, words in grouped:
                if date not in daily:
                    continue
                daily[date]["dictations"] += count
                daily[date]["words"] += words
                item = apps.setdefault(app or "Unknown app", {"dictations": 0, "words": 0})
                item["dictations"] += count
                item["words"] += words
                result["dictations"] += count
                result["words"] += words
            result["active_days"] = sum(bool(item["dictations"]) for item in daily.values())
            result["apps"] = [{"app": app, **counts} for app, counts in
                              sorted(apps.items(), key=lambda pair: (-pair[1]["words"], pair[0]))]
        except sqlite3.Error:
            log.debug("history usage unavailable", exc_info=True)
        return result

    def export_json(self, destination: str | Path) -> int:
        """User-requested, lossless export of retained entries; atomic and streamed."""
        self.prune()
        if not self._conn:
            raise ValueError("History is disabled or unavailable.")
        path = Path(destination)
        # An export must never overwrite its own database or SQLite sidecars.
        with self._lock:
            database = Path(self._conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
        if os.path.normcase(str(path.resolve())) in {
                os.path.normcase(str(database) + suffix) for suffix in ("", "-wal", "-shm", "-journal")}:
            raise ValueError("Choose an export file outside the history database.")
        fd, temporary = tempfile.mkstemp(prefix=".svara-history-", dir=path.parent)
        count = 0
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write('{"format":"svara-history","version":1,"entries":[\n')
                with self._lock:
                    cursor = self._conn.execute(
                        "SELECT ts, app, kind, text FROM dictations WHERE ts>=? ORDER BY id",
                        (self._retained_after(),))
                    for ts, app, kind, text in cursor:
                        if count:
                            stream.write(",\n")
                        json.dump({"timestamp": ts, "app": app, "kind": kind, "text": text},
                                  stream, ensure_ascii=False)
                        count += 1
                stream.write("\n]}\n")
            os.replace(temporary, path)
        except sqlite3.Error as exc:
            raise ValueError("Could not read history; the export was not replaced.") from exc
        finally:
            Path(temporary).unlink(missing_ok=True)
        return count

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
