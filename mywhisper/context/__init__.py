"""Building the `UtteranceContext` for one dictation.

Everything the pipeline and the injector need to know about *where* the text is
going, gathered once at the start of a recording so the rest of the run is a
pure function of it.

All local. The exe name and window title come from Win32; the integrity level
from our own token; the caret text (opt-in) from UI Automation. Nothing here
opens a socket.
"""

import logging

from ..injection.resolver import is_terminal_app
from ..pipeline.base import UtteranceContext
from ..pipeline.locale import resolve_locale
from . import caret, elevation
from .win import Foreground, foreground, foreground_full, title_hotwords

log = logging.getLogger(__name__)

__all__ = ["ContextProvider", "Foreground", "caret", "elevation", "foreground",
           "foreground_full", "title_hotwords"]


class ContextProvider:
    """Composes the per-utterance context from the individually-gated signals.

    Each signal degrades independently: if UIA is unavailable the caret prefix
    is None and everything else still works; if the process query fails the exe
    is "" and per-app rules simply don't fire. There is no configuration in
    which a context failure blocks dictation.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _ctx_cfg(self) -> dict:
        return self.cfg.get("context") or {}

    def _locale_cfg(self) -> dict:
        return self.cfg.get("locale") or {}

    def capture(self, source: str = "dictation") -> tuple[UtteranceContext, list[str]]:
        """(context, title_hotwords). Called once per recording start."""
        ctx_cfg = self._ctx_cfg()
        inj_cfg = self.cfg.get("injection") or {}
        loc_cfg = self._locale_cfg()

        locale = resolve_locale(
            (self.cfg.get("model") or {}).get("language"),
            str(loc_cfg.get("english_variant", "en-US")))

        if not ctx_cfg.get("enabled", True):
            return UtteranceContext(locale=locale, source=source), []

        fg = foreground_full()
        chat_apps = {a.lower() for a in (ctx_cfg.get("chat_apps") or [])}
        hotwords = (title_hotwords(fg.title)
                    if ctx_cfg.get("title_hotwords", True) else [])

        is_elevated = False
        if inj_cfg.get("warn_on_elevated", True) and fg.pid:
            is_elevated = elevation.target_is_higher(fg.pid)

        caret_prefix = None
        if ctx_cfg.get("read_caret_text", False):
            caret_prefix = caret.prefix(
                max_chars=int(ctx_cfg.get("caret_chars", 200) or 200))

        ctx = UtteranceContext(
            app=fg.exe,
            title=fg.title,
            locale=locale,
            style_hint=(ctx_cfg.get("styles") or {}).get(fg.exe),
            is_terminal=is_terminal_app(fg.exe, inj_cfg),
            is_chat=fg.exe in chat_apps,
            is_elevated=is_elevated,
            caret_prefix=caret_prefix,
            source=source,
            meta={"pid": fg.pid, "hwnd": fg.hwnd},
        )
        return ctx, hotwords
