"""Scratchpad storage — tabs, and a version log that remembers where text came from.

The v0.4 scratchpad was one text file with an 800 ms autosave. That is a good
notepad and a bad workspace: you cannot keep two thoughts apart, and an
overzealous transform silently eats the note.

So: multiple notes, and every save is a version tagged with its **source** —
`typed`, `dictated`, or `transform`. That provenance is the point. When a local
model rewrites a note, you can see exactly which version it replaced and go
back, which is the difference between trusting a transform and not using one.

Storage is SQLite next to `history.db`, following the same pattern. Migration
from `scratchpad.txt` runs once on first open and **keeps the original file** —
an auto-update that loses someone's notes is unrecoverable, and a stale text
file costs nothing.
"""

import logging
import sqlite3
import threading
import time

from .redact import E_HIST_DB

log = logging.getLogger(__name__)

SOURCE_TYPED = "typed"
SOURCE_DICTATED = "dictated"
SOURCE_TRANSFORM = "transform"

MAX_VERSIONS_PER_NOTE = 50   # keeps the file bounded on a note edited all day


class Scratchpad:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if not enabled:
            return
        try:
            from .paths import base_dir
            self._conn = sqlite3.connect(str(base_dir() / "scratchpad.db"),
                                         check_same_thread=False)
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT 'Note',
                    body TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    updated REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER NOT NULL,
                    ts REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'typed',
                    body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS versions_note
                    ON versions(note_id, id DESC);
            """)
            self._conn.commit()
            self._migrate_legacy()
        except sqlite3.Error:
            log.warning("%s scratchpad database unavailable — continuing "
                        "without", E_HIST_DB, exc_info=True)
            self._conn = None

    # -- migration -----------------------------------------------------------

    def _migrate_legacy(self):
        """Import scratchpad.txt once. The original file is left in place: if
        anything about this goes wrong the user's notes are still on disk."""
        from .paths import base_dir

        legacy = base_dir() / "scratchpad.txt"
        marker = base_dir() / ".scratchpad_migrated"
        if marker.exists() or not legacy.is_file():
            return
        try:
            body = legacy.read_text(encoding="utf-8")
        except OSError:
            log.warning("%s could not read scratchpad.txt for migration",
                        E_HIST_DB)
            return
        try:
            if body.strip():
                note_id = self.create("Scratchpad")
                self.save(note_id, body, source=SOURCE_TYPED)
                log.info("migrated scratchpad.txt into the notes database "
                         "(%d chars); the original file was kept",
                         len(body))
            marker.write_text(str(time.time()), encoding="utf-8")
        except (sqlite3.Error, OSError):
            log.warning("%s scratchpad migration failed — scratchpad.txt is "
                        "untouched and will be retried next launch", E_HIST_DB,
                        exc_info=True)

    # -- notes ---------------------------------------------------------------

    def notes(self) -> list[tuple[int, str, float]]:
        """[(id, title, updated)] in tab order.

        Named `notes`, not `list` — a method called `list` inside a class body
        shadows the builtin for every annotation that follows it.
        """
        if not self._conn:
            return []
        try:
            with self._lock:
                return self._conn.execute(
                    "SELECT id, title, updated FROM notes "
                    "ORDER BY position, id").fetchall()
        except sqlite3.Error:
            return []

    def create(self, title: str = "Note") -> int:
        if not self._conn:
            return 0
        try:
            with self._lock:
                cur = self._conn.execute(
                    "INSERT INTO notes (title, body, position, updated) "
                    "VALUES (?, '', (SELECT COALESCE(MAX(position), 0) + 1 "
                    "FROM notes), ?)", (title, time.time()))
                self._conn.commit()
                return int(cur.lastrowid)
        except sqlite3.Error:
            log.debug("scratchpad create failed", exc_info=True)
            return 0

    def body(self, note_id: int) -> str:
        if not self._conn:
            return ""
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT body FROM notes WHERE id=?", (note_id,)).fetchone()
            return row[0] if row else ""
        except sqlite3.Error:
            return ""

    def save(self, note_id: int, body: str, source: str = SOURCE_TYPED) -> bool:
        """Write the body and append a version — but only when the text
        actually changed. An autosave timer firing on an idle window must not
        fill the version log with identical entries."""
        if not self._conn or not note_id:
            return False
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT body FROM notes WHERE id=?", (note_id,)).fetchone()
                if row is None:
                    return False
                if row[0] == body:
                    return True
                self._conn.execute(
                    "UPDATE notes SET body=?, updated=? WHERE id=?",
                    (body, time.time(), note_id))
                self._conn.execute(
                    "INSERT INTO versions (note_id, ts, source, body) "
                    "VALUES (?,?,?,?)", (note_id, time.time(), source, row[0]))
                self._conn.execute(
                    "DELETE FROM versions WHERE note_id=? AND id NOT IN ("
                    "  SELECT id FROM versions WHERE note_id=? "
                    "  ORDER BY id DESC LIMIT ?)",
                    (note_id, note_id, MAX_VERSIONS_PER_NOTE))
                self._conn.commit()
            return True
        except sqlite3.Error:
            log.debug("%s scratchpad save failed", E_HIST_DB, exc_info=True)
            return False

    def rename(self, note_id: int, title: str) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute("UPDATE notes SET title=? WHERE id=?",
                                   (title, note_id))
                self._conn.commit()
            return True
        except sqlite3.Error:
            return False

    def delete(self, note_id: int) -> bool:
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
                self._conn.execute("DELETE FROM versions WHERE note_id=?",
                                   (note_id,))
                self._conn.commit()
            return True
        except sqlite3.Error:
            return False

    # -- versions ------------------------------------------------------------

    def versions(self, note_id: int, limit: int = 30) -> list[tuple]:
        """[(id, ts, source, body)] newest first — the provenance log."""
        if not self._conn:
            return []
        try:
            with self._lock:
                return self._conn.execute(
                    "SELECT id, ts, source, body FROM versions "
                    "WHERE note_id=? ORDER BY id DESC LIMIT ?",
                    (note_id, limit)).fetchall()
        except sqlite3.Error:
            return []

    def restore(self, note_id: int, version_id: int) -> bool:
        """Roll a note back. The current body is itself versioned first, so
        'undo the undo' works."""
        if not self._conn:
            return False
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT body FROM versions WHERE id=? AND note_id=?",
                    (version_id, note_id)).fetchone()
            if row is None:
                return False
            return self.save(note_id, row[0], source="restore")
        except sqlite3.Error:
            return False

    def ensure_one(self) -> int:
        """Id of the first note, creating one if the database is empty."""
        rows = self.notes()
        return rows[0][0] if rows else self.create("Scratchpad")

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
