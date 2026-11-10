"""Portable vocabulary libraries: local JSON data, never executable settings."""
import copy
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

FORMAT = "svara-vocabulary"
VERSION = 1
MAX_BYTES = 3 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_TRIGGER = 200
MAX_EXPANSION = 16000


@dataclass
class MergeReport:
    added: int = 0
    duplicates: int = 0
    conflicts: int = 0

    def summary(self) -> str:
        return (f"Added {self.added} entries; {self.duplicates} duplicates skipped; "
                f"{self.conflicts} conflicts kept unchanged.")


def _clean(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Library entries must be an object.")
    clean = {"words": [], "replacements": {}, "snippets": {}}
    count = 0
    for key in clean:
        entries = data.get(key, [] if key == "words" else {})
        if not isinstance(entries, list if key == "words" else dict):
            raise ValueError(f"Invalid {key} section.")
        count += len(entries)
        if count > MAX_ENTRIES:
            raise ValueError(f"Library exceeds {MAX_ENTRIES} entries.")
        seen = set()
        for trigger in entries:
            if (not isinstance(trigger, str) or not trigger.strip()
                    or len(trigger) > MAX_TRIGGER or any(c in trigger for c in "\r\n\x00")):
                raise ValueError("Library contains an invalid word or trigger.")
            name = trigger.strip()
            folded = name.casefold()
            if folded in seen:
                raise ValueError("Library has duplicate triggers with different casing.")
            seen.add(folded)
            if key == "words":
                clean[key].append(name)
            else:
                value = entries[trigger]
                if (not isinstance(value, str) or not value.strip()
                        or len(value) > MAX_EXPANSION or "\x00" in value):
                    raise ValueError("Library contains an invalid expansion.")
                clean[key][name] = value  # whitespace in saved text is literal
    return clean


def load_library(path: str | Path) -> dict:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Library exceeds the 3 MB size limit.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Library is not valid UTF-8 JSON.") from exc
    if (not isinstance(payload, dict) or payload.get("format") != FORMAT
            or type(payload.get("version")) is not int or payload["version"] != VERSION):
        raise ValueError("Unsupported Svara library format or version.")
    return _clean(payload.get("entries"))


def export_library(path: str | Path, data: dict) -> int:
    entries = _clean(data)
    payload = json.dumps({"format": FORMAT, "version": VERSION, "entries": entries},
                         ensure_ascii=False, indent=2).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("Library exceeds the 3 MB size limit.")
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".svara-library-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return sum(len(value) for value in entries.values())


def merge_library(target: dict, incoming: dict) -> MergeReport:
    """Validate everything first; keep existing local entries on any conflict."""
    clean = _clean(incoming)
    work = copy.deepcopy(target)
    report = MergeReport()
    known_words = {str(w).casefold() for w in work.setdefault("words", [])}
    for word in clean["words"]:
        if word.casefold() in known_words:
            report.duplicates += 1
        else:
            work["words"].append(word)
            known_words.add(word.casefold())
            report.added += 1
    for key in ("replacements", "snippets"):
        work.setdefault(key, {})
    # A snippet and a replacement using the same trigger also conflict: the
    # pipeline cannot apply both faithfully, even though the sections differ.
    known = {str(trigger).casefold(): value for key in ("replacements", "snippets")
             for trigger, value in work[key].items()}
    for key in ("snippets", "replacements"):
        for trigger, value in clean[key].items():
            folded = trigger.casefold()
            if folded in known:
                if known[folded] == value:
                    report.duplicates += 1
                else:
                    report.conflicts += 1
            else:
                work[key][trigger] = value
                known[folded] = value
                report.added += 1
    target.clear()
    target.update(work)
    return report


def merge_configured(data: dict) -> dict:
    """Personal entries win; shared libraries fill gaps in configured order."""
    from .paths import base_dir
    paths = data.get("libraries") or []
    if not isinstance(paths, list):
        return data
    for entry in paths[:16]:
        try:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError("Invalid library path.")
            path = Path(entry)
            if not path.is_absolute():
                path = base_dir() / path
            merge_library(data, load_library(path))
        except (OSError, ValueError, TypeError, AttributeError):
            # Do not put vocabulary, expansion text or a private path in logs.
            logging.getLogger(__name__).warning("A configured vocabulary library could not be loaded; personal entries are unchanged.")
    return data
