"""Reading, writing, importing and learning the personal dictionary.

Three jobs:

1. **File I/O** for `dictionary.yaml` — the machine-managed half of the
   dictionary (config.yaml holds the hand-written half; they merge at load).
2. **CSV import/export**, two columns, capped at 1,000 rows / 3 MB. Import
   never silently overwrites: conflicts are counted and reported, because a
   bulk import that quietly replaced a user's own corrections would be exactly
   the wrong behaviour for the one feature that exists to preserve them.
3. **The auto-learn review queue** — candidate entries observed from the user's
   own corrections, held *pending* until they click accept.

On (3): auto-learn is the most invasive idea in this codebase. It watches text
you typed that Svara did not produce. So it is off by default, thresholded, and
**never** writes to the dictionary on its own — it can only ever put a
suggestion in a queue. A dictation tool that silently rewrites your words based
on inferred intent is worse than one that occasionally gets a word wrong.
Nothing here is ever logged.
"""

import csv
import io
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .redact import E_DICT_IO

log = logging.getLogger(__name__)

MAX_CSV_ROWS = 1000
MAX_CSV_BYTES = 3 * 1024 * 1024

DICT_TEMPLATE = """\
# Svara's personal dictionary — YOUR words. Reload from the tray after editing.
# NOTE: Svara rewrites this file for quick-adds and the dictionary editor;
# hand-written comments here may not survive. Long-form notes belong in
# config.yaml.
words: []                   # names/jargon to recognize better, e.g. [Svara, Vasudev]
replacements: {}            # exact fixes, e.g. { "swara": "Svara", "get hub": "GitHub" }
snippets: {}                # say the trigger, type the block, e.g.
                            #   "my email": "you@example.com"
spoken_punctuation: false   # true -> "period"/"comma"/"new line" type . , newline
"""


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_dictionary() -> dict:
    """`dictionary.yaml` as a dict, always with the four expected keys."""
    from .paths import dictionary_path

    data: dict = {}
    path = dictionary_path()
    try:
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
    except (OSError, yaml.YAMLError) as e:
        log.error("%s could not read dictionary.yaml (%s) — starting empty",
                  E_DICT_IO, type(e).__name__)
    data.setdefault("words", [])
    data.setdefault("replacements", {})
    data.setdefault("snippets", {})
    data.setdefault("spoken_punctuation", False)
    return data


def save_dictionary(data: dict) -> bool:
    """Write atomically — a half-written dictionary would fail to parse on the
    next launch and take the user's whole vocabulary with it."""
    from .paths import dictionary_path

    path = dictionary_path()
    tmp = path.with_suffix(".yaml.tmp")
    try:
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        log.exception("%s could not write dictionary.yaml", E_DICT_IO)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def seed_dictionary_file() -> Path:
    from .paths import dictionary_path

    path = dictionary_path()
    try:
        if not path.is_file():
            path.write_text(DICT_TEMPLATE, encoding="utf-8")
    except OSError:
        log.debug("could not seed dictionary template", exc_info=True)
    return path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

@dataclass
class ImportReport:
    added: int = 0
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    skipped: int = 0
    truncated: bool = False

    def summary(self) -> str:
        bits = [f"Imported {self.added} entr{'y' if self.added == 1 else 'ies'}"]
        if self.conflicts:
            bits.append(f"{len(self.conflicts)} already existed and were kept "
                        "as-is")
        if self.skipped:
            bits.append(f"{self.skipped} malformed rows skipped")
        if self.truncated:
            bits.append(f"stopped at the {MAX_CSV_ROWS}-row limit")
        return " · ".join(bits) + "."


def import_csv(path: str | Path, data: dict, *,
               target: str = "replacements") -> ImportReport:
    """Two-column CSV → dictionary entries.

    A single column is read as `words`. Two columns are read as
    heard → typed replacements. Existing entries are **never** overwritten;
    they are reported instead.
    """
    report = ImportReport()
    p = Path(path)
    try:
        if p.stat().st_size > MAX_CSV_BYTES:
            log.error("%s %s is larger than the %d MB import limit",
                      E_DICT_IO, p.name, MAX_CSV_BYTES // (1024 * 1024))
            report.skipped = -1
            return report
        raw = p.read_text(encoding="utf-8-sig")
    except OSError:
        log.exception("%s could not read %s", E_DICT_IO, p)
        report.skipped = -1
        return report

    words = list(data.setdefault("words", []))
    lower_words = {str(w).lower() for w in words}
    table = data.setdefault(target, {})

    for i, row in enumerate(csv.reader(io.StringIO(raw))):
        if i >= MAX_CSV_ROWS:
            report.truncated = True
            break
        cells = [c.strip() for c in row if c is not None]
        cells = [c for c in cells if c]
        if not cells:
            continue
        # Tolerate a header row without making the user delete it.
        if i == 0 and len(cells) >= 2 and cells[0].lower() in (
                "heard", "word", "from", "spoken", "wrong"):
            continue
        if len(cells) == 1:
            if cells[0].lower() in lower_words:
                report.conflicts.append(("words", cells[0], cells[0]))
                continue
            words.append(cells[0])
            lower_words.add(cells[0].lower())
            report.added += 1
        elif len(cells) >= 2:
            heard, typed = cells[0], cells[1]
            if heard in table and table[heard] != typed:
                report.conflicts.append((target, heard, str(table[heard])))
                continue
            if heard in table:
                continue
            table[heard] = typed
            report.added += 1
        else:
            report.skipped += 1

    data["words"] = words
    if report.conflicts:
        log.info("dictionary import: %d entries added, %d conflicts kept as-is",
                 report.added, len(report.conflicts))
    return report


def export_csv(path: str | Path, data: dict) -> int:
    """Everything as a two-column CSV. Round-trips through `import_csv`."""
    rows: list[tuple[str, str]] = []
    for w in data.get("words") or []:
        rows.append((str(w), ""))
    for heard, typed in (data.get("replacements") or {}).items():
        rows.append((str(heard), str(typed)))
    for trigger, text in (data.get("snippets") or {}).items():
        rows.append((str(trigger), str(text)))
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(("heard", "typed"))
            writer.writerows(rows)
    except OSError:
        log.exception("%s could not write %s", E_DICT_IO, path)
        return 0
    return len(rows)


# ---------------------------------------------------------------------------
# Auto-learn review queue
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    heard: str
    corrected: str
    count: int = 1
    sessions: int = 1
    first_seen: float = 0.0

    def ready(self, threshold: int) -> bool:
        # Two independent gates. Repetition alone can come from one frantic
        # editing session; distinct sessions prove it's a habit.
        return self.count >= threshold and self.sessions >= 2


class LearnQueue:
    """Pending dictionary suggestions, persisted next to the dictionary.

    Stored separately from `dictionary.yaml` on purpose: nothing in this queue
    is active, and a user opening their dictionary file should see only what
    they actually agreed to.
    """

    FILE = "learned.yaml"

    def __init__(self, session_id: float | None = None, threshold: int = 3):
        self.threshold = max(2, int(threshold))
        self.session_id = session_id if session_id is not None else time.time()
        self._items: dict[str, Candidate] = {}
        self._seen_this_session: set[str] = set()
        self._load()

    def _path(self) -> Path:
        from .paths import base_dir
        return base_dir() / self.FILE

    def _load(self):
        try:
            path = self._path()
            if not path.is_file():
                return
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for key, item in (raw.get("candidates") or {}).items():
                self._items[key] = Candidate(
                    heard=item.get("heard", key),
                    corrected=item.get("corrected", ""),
                    count=int(item.get("count", 1)),
                    sessions=int(item.get("sessions", 1)),
                    first_seen=float(item.get("first_seen", 0.0)))
        except (OSError, yaml.YAMLError, TypeError, ValueError):
            log.debug("learn queue unreadable — starting empty", exc_info=True)

    def save(self) -> bool:
        try:
            payload = {"candidates": {
                key: {"heard": c.heard, "corrected": c.corrected,
                      "count": c.count, "sessions": c.sessions,
                      "first_seen": c.first_seen}
                for key, c in self._items.items()}}
            self._path().write_text(
                yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                encoding="utf-8")
            return True
        except OSError:
            log.debug("%s could not write the learn queue", E_DICT_IO,
                      exc_info=True)
            return False

    def observe(self, heard: str, corrected: str) -> Candidate | None:
        """Record one observed correction. Returns the candidate if this
        observation pushed it over the threshold — i.e. if it is now worth
        *asking* about. Never writes to the dictionary."""
        heard, corrected = (heard or "").strip(), (corrected or "").strip()
        if not heard or not corrected or heard.lower() == corrected.lower():
            return None
        if len(heard) > 60 or len(corrected) > 60:
            return None
        key = heard.lower()
        item = self._items.get(key)
        if item is None:
            self._items[key] = Candidate(heard=heard, corrected=corrected,
                                         first_seen=self.session_id)
            self._seen_this_session.add(key)
            self.save()
            return None
        item.corrected = corrected
        item.count += 1
        if key not in self._seen_this_session:
            self._seen_this_session.add(key)
            item.sessions += 1
        was_ready = item.count - 1 >= self.threshold and item.sessions >= 2
        self.save()
        if item.ready(self.threshold) and not was_ready:
            return item
        return None

    def pending(self) -> list[Candidate]:
        return [c for c in self._items.values() if c.ready(self.threshold)]

    def accept(self, heard: str, data: dict) -> bool:
        """Promote a candidate into the real dictionary. Only ever called from
        an explicit user click."""
        item = self._items.pop((heard or "").lower(), None)
        if item is None:
            return False
        data.setdefault("replacements", {})[item.heard] = item.corrected
        self.save()
        return save_dictionary(data)

    def reject(self, heard: str) -> bool:
        if self._items.pop((heard or "").lower(), None) is None:
            return False
        self.save()
        return True

    def clear(self):
        self._items.clear()
        self.save()
