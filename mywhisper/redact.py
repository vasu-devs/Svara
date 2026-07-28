"""Keeping what you dictate out of the log file.

Svara's promise is that your speech never leaves your machine. A log file on
that machine is still a leak: `logs/mywhisper.log` is plaintext, is read by
anyone who opens the folder, gets pasted verbatim into bug reports, and — the
part that actually bites — outlives `history.retention_hours`. A user who sets
history to expire after a day, then dictates a password or a medical note, has
every reason to expect it gone the next day. Before this module, it wasn't.

The rule here: **log the shape of an utterance, never its content.**
Duration, word count, timings, error codes — all fine, all diagnosable. The
words themselves only reach the log when the user explicitly turns on
`logging.debug_transcripts`, which the UI warns about.

Two layers, because one is not enough:

1. `redact()` at every call site that holds user text. Intent is explicit and
   greppable.
2. `RedactionFilter` on the root logger as a backstop, so a future `log.info(f"…
   {text}")` written by someone who never read this file still can't leak. It
   scrubs anything a call site marked with `sensitive()`, plus the shapes that
   are dangerous by construction (long quoted spans in transform prompts).

Error codes (`SVARA-xxx-nnn`) exist so a user can paste a log they've actually
read without feeling like they're handing over a diary.
"""

import logging
import os

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error codes — stable, greppable, safe to quote in a GitHub issue.
# Add here rather than inventing strings at call sites.
# ---------------------------------------------------------------------------

E_STT_LOAD = "SVARA-STT-001"        # model failed to load
E_STT_DECODE = "SVARA-STT-002"      # a transcription pass raised
E_STT_STREAM = "SVARA-STT-003"      # a streaming partial pass raised
E_INJ_SEND = "SVARA-INJ-001"        # SendInput failed / partial
E_INJ_CLIP = "SVARA-INJ-002"        # clipboard set/get failed
E_INJ_ELEVATED = "SVARA-INJ-003"    # target runs elevated, we don't
E_PIPE_STAGE = "SVARA-PIPE-001"     # a cleanup stage raised (text preserved)
E_LLM_UNREACHABLE = "SVARA-LLM-001"  # no local LLM server answering
E_LLM_CALL = "SVARA-LLM-002"        # the call failed mid-flight
E_CFG_PARSE = "SVARA-CFG-001"       # config.yaml / dictionary.yaml unparseable
E_DICT_IO = "SVARA-DICT-001"        # dictionary read/write failed
E_HIST_DB = "SVARA-HIST-001"        # history/scratchpad sqlite failure
E_AUDIO_DEV = "SVARA-AUD-001"       # microphone unavailable / changed
E_UI = "SVARA-UI-001"               # a window failed to open

# Module-level switch. Off means: no dictated text in logs, ever, at any level.
_ALLOW_TRANSCRIPTS = False

_PLACEHOLDER = "«redacted»"


def configure(logging_cfg: dict | None) -> bool:
    """Apply the `logging:` config section. Returns whether transcript logging
    ended up enabled, so the caller can warn the user about it."""
    global _ALLOW_TRANSCRIPTS
    cfg = logging_cfg or {}
    want = bool(cfg.get("debug_transcripts", False))
    # An env var is the escape hatch for debugging a packaged build where
    # editing config.yaml and restarting is a slow loop.
    if os.environ.get("SVARA_DEBUG_TRANSCRIPTS") == "1":
        want = True
    _ALLOW_TRANSCRIPTS = want
    return want


def transcripts_enabled() -> bool:
    return _ALLOW_TRANSCRIPTS


def redact(text: str | None, keep: int = 0) -> str:
    """Render user text for a log line.

    Default (`keep=0`): nothing but the shape — `«redacted» 12 words/68 chars`.
    That is enough to debug "did the pipeline eat my text?" without knowing what
    the text was, which is the question logs are actually asked.

    `keep=N` shows the first N characters and is used *only* where the content
    is structural rather than personal (a config value, a model id). It still
    respects the master switch.
    """
    if text is None:
        return "«none»"
    if _ALLOW_TRANSCRIPTS:
        return text
    n_chars = len(text)
    n_words = len(text.split())
    if keep > 0 and n_chars <= keep:
        return text
    return f"{_PLACEHOLDER} {n_words}w/{n_chars}c"


def shape(text: str | None) -> str:
    """Content-free description, ignoring the debug switch entirely. For lines
    that should stay safe even when a developer has transcripts turned on —
    high-frequency streaming logs, where a full transcript per pass would bloat
    the file into uselessness."""
    if text is None:
        return "«none»"
    return f"{len(text.split())}w/{len(text)}c"


def sensitive(text: str | None) -> str:
    """Mark a value as user content inside an f-string or %-arg.

    Prefer `redact()`. This exists for the cases where text is embedded in a
    larger message; the filter below scrubs the marked span if the message
    reaches a handler with transcripts disabled.
    """
    if text is None:
        return "«none»"
    if _ALLOW_TRANSCRIPTS:
        return text
    return f"\x00{text}\x00"


class RedactionFilter(logging.Filter):
    """Backstop on the root logger.

    Call-site discipline is the primary defence; this catches the line someone
    adds in six months without reading this module. It removes `sensitive()`
    spans and, when transcripts are off, refuses to emit records that a call
    site tagged `record.user_text = True`.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "user_text", False) and not _ALLOW_TRANSCRIPTS:
            return False
        if _ALLOW_TRANSCRIPTS:
            return True
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 — a bad format string must not crash logging
            return True
        if "\x00" not in msg:
            return True
        # Rebuild with marked spans collapsed. args are folded in already, so
        # replace the formatted message wholesale.
        out, keep = [], True
        for part in msg.split("\x00"):
            out.append(part if keep else _PLACEHOLDER)
            keep = not keep
        record.msg = "".join(out)
        record.args = ()
        return True


def install(logging_cfg: dict | None = None) -> bool:
    """Configure and attach the filter to every root handler. Idempotent —
    `--verbose` restarts and tray-driven reloads both call this."""
    enabled = configure(logging_cfg)
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(RedactionFilter())
    if enabled:
        log.warning(
            "logging.debug_transcripts is ON — everything you dictate is being "
            "written to logs/mywhisper.log in plain text. Turn it off when "
            "you're done debugging.")
    return enabled
