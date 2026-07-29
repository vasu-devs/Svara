"""Text injection — the façade the app talks to."""

import logging

from ..pipeline.base import UtteranceContext
from ..redact import E_INJ_ELEVATED, shape
from .base import BaseStrategy, InjectionStrategy
from .resolver import (DEFAULT_SHIFT_INSERT, DEFAULT_TERMINALS, build, classify,
                       is_terminal_app, resolve)
from .strategies import (ClipboardPasteStrategy, SendInputStrategy,
                         ShiftInsertStrategy, TerminalStrategy)

log = logging.getLogger(__name__)

__all__ = [
    "BaseStrategy", "ClipboardPasteStrategy", "DEFAULT_SHIFT_INSERT",
    "DEFAULT_TERMINALS", "InjectionStrategy", "SendInputStrategy",
    "ShiftInsertStrategy", "TerminalStrategy", "TextInjector", "build",
    "classify", "is_terminal_app", "resolve",
]

_NEUTRAL = UtteranceContext()


class TextInjector:
    """Resolves a strategy per target and hands the text to it.

    Keeps the pre-0.5 surface (`inject`, `inject_stream`, `.method`,
    `.append_space`, `.restore_clipboard`) so nothing that already calls it
    needs to change; `ctx` is optional and defaults to the neutral context,
    which resolves to exactly the old behaviour.
    """

    def __init__(self, inj_cfg: dict, notify=None):
        self.cfg = inj_cfg
        self.method = inj_cfg.get("method", "type")
        self.append_space = bool(inj_cfg.get("append_space", True))
        self.restore_clipboard = bool(inj_cfg.get("restore_clipboard", True))
        self.notify = notify or (lambda *_: None)
        self._elevation_warned: set[str] = set()

    def strategy_for(self, ctx: UtteranceContext) -> InjectionStrategy:
        return resolve(ctx, self.cfg, warn=self.notify)

    def inject(self, text: str, ctx: UtteranceContext | None = None) -> int:
        if not text:
            return 0
        ctx = ctx or _NEUTRAL
        # Terminals run their own trailing-whitespace policy; a trailing space
        # elsewhere is what makes consecutive dictations join up nicely.
        if self.append_space and not ctx.is_terminal and not text.endswith((" ", "\n")):
            text += " "
        if ctx.is_elevated and self.cfg.get("warn_on_elevated", True):
            return self._deliver_to_elevated(ctx, text)
        return self.strategy_for(ctx).inject(text, ctx)

    def inject_stream(self, text: str, ctx: UtteranceContext | None = None) -> int:
        """Live-typing deltas.

        Always direct SendInput, whatever the target's strategy is: streaming
        through the clipboard would clobber it dozens of times per utterance,
        and Shift+Insert can't deliver a partial word without a visible flash.
        Terminals therefore get their text at finalisation instead — which is
        also the only correct answer, since a half-typed line at a shell prompt
        is a line the user can accidentally submit.
        """
        if not text:
            return 0
        ctx = ctx or _NEUTRAL
        if not self.streams_into(ctx):
            return 0
        from ..injector import type_text, wait_modifiers_released
        wait_modifiers_released()
        type_text(text)
        return len(text)

    def streams_into(self, ctx: UtteranceContext | None) -> bool:
        """Whether live streaming is safe for this target. The streamer asks
        before typing anything."""
        ctx = ctx or _NEUTRAL
        return not (ctx.is_terminal or ctx.is_elevated)

    def _deliver_to_elevated(self, ctx: UtteranceContext, text: str) -> int:
        """UIPI will discard synthetic input aimed at a higher-integrity
        window, and `SendInput` will still report success — so the dictation
        would vanish with no error anywhere. Put it on the clipboard instead
        and say why, once per app."""
        from ..injector import _clipboard_set
        app = ctx.app or "the focused app"
        _clipboard_set(text)
        log.warning("%s target %s runs elevated; delivered %s via clipboard",
                    E_INJ_ELEVATED, app, shape(text))
        if app not in self._elevation_warned:
            self._elevation_warned.add(app)
            self.notify(
                f"{app} is running as administrator — Windows blocks Svara "
                "from typing into it. Your dictation is on the clipboard, so "
                "press Ctrl+V. To fix this for good, run Svara as "
                "administrator too.")
        return 0
