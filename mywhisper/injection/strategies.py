"""The concrete injection strategies."""

import logging
import re
import time

from ..injector import (paste_text, paste_text_shift_insert, type_text,
                        wait_modifiers_released)
from ..pipeline.base import UtteranceContext
from ..redact import E_INJ_SEND, shape
from .base import BaseStrategy

log = logging.getLogger(__name__)


class SendInputStrategy(BaseStrategy):
    """Win32 SendInput with KEYEVENTF_UNICODE — types into the focused control
    character-perfect and never touches the clipboard. The right default for
    normal text fields."""

    name = "type"

    def inject(self, text: str, ctx: UtteranceContext) -> int:  # noqa: ARG002
        wait_modifiers_released()
        try:
            type_text(text)
        except OSError:
            log.error("%s SendInput failed (%s)", E_INJ_SEND, shape(text),
                      exc_info=True)
            return 0
        return len(text)


class ClipboardPasteStrategy(BaseStrategy):
    """Clipboard + Ctrl+V. Fastest for long text; restores the previous
    clipboard afterwards when configured to."""

    name = "paste"

    def __init__(self, restore: bool = True):
        self.restore = restore

    def inject(self, text: str, ctx: UtteranceContext) -> int:  # noqa: ARG002
        wait_modifiers_released()
        paste_text(text, restore=self.restore)
        return len(text)


class ShiftInsertStrategy(BaseStrategy):
    """Clipboard + Shift+Insert — for targets that have claimed Ctrl+V."""

    name = "shift_insert"

    def __init__(self, restore: bool = True):
        self.restore = restore

    def inject(self, text: str, ctx: UtteranceContext) -> int:  # noqa: ARG002
        wait_modifiers_released()
        paste_text_shift_insert(text, restore=self.restore)
        return len(text)


# A line that looks like it would run something if it reached a shell prompt.
_RISKY = re.compile(
    r"^\s*(?:sudo|rm|del|rmdir|format|mkfs|dd|shutdown|reboot|kill|taskkill"
    r"|git\s+(?:push|reset|clean)|npm\s+publish|curl|wget|chmod|chown)\b",
    re.IGNORECASE)


class TerminalStrategy(BaseStrategy):
    """Terminals, shells, and TUI coding agents (Claude Code, Codex, Cursor's
    terminal, Windsurf).

    The whole job here is: **never submit anything the user didn't submit.**
    A newline at a shell prompt is the Enter key. So:

    - `newline: space` (default) — newlines become spaces. A dictated paragraph
      arrives as one editable line and the user presses Enter themselves. Safe
      everywhere, including a bare `cmd.exe`.
    - `newline: shift_enter` — newlines are sent as Shift+Enter, which modern
      TUI agents treat as a soft line break. Multi-line prompts work; nothing
      submits. Falls back to `space` in apps that don't support it.
    - `newline: literal` — opt-in, for people who know what they're asking for.

    Trailing whitespace and any trailing newline are stripped regardless — a
    trailing newline is the single most dangerous character this app can emit.

    Injection goes through the clipboard rather than per-character SendInput,
    because terminal emulators render synthesised keystrokes one PTY round-trip
    at a time and a long dictation visibly crawls.
    """

    name = "terminal"

    def __init__(self, newline: str = "space", restore: bool = True,
                 paste: bool = True, warn=None):
        self.newline = str(newline or "space").lower()
        self.restore = restore
        self.paste = paste
        self.warn = warn or (lambda *_: None)

    def prepare(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self.newline == "space":
            text = re.sub(r"\n+", " ", text)
        elif self.newline == "shift_enter":
            pass  # handled during injection
        # Strip the trailing newline in every mode. Nothing Svara does should
        # press Enter for you.
        text = text.rstrip("\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        return re.sub(r"[ \t]{2,}", " ", text).rstrip()

    def _warn_if_risky(self, text: str):
        for line in text.split("\n"):
            if _RISKY.match(line):
                self.warn("Heads up — that looks like a command. Svara typed "
                          "it but did not run it; press Enter yourself.")
                return

    def inject(self, text: str, ctx: UtteranceContext) -> int:
        text = self.prepare(text, ctx)
        if not text:
            return 0
        self._warn_if_risky(text)
        wait_modifiers_released()

        if self.newline == "shift_enter" and "\n" in text:
            from ..injector import (KEYEVENTF_KEYUP, VK_RETURN, VK_SHIFT,
                                    _key_event, _send)
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if line:
                    if self.paste:
                        paste_text_shift_insert(line, restore=False)
                        time.sleep(0.06)
                    else:
                        type_text(line)
                if i < len(lines) - 1:
                    _send([
                        _key_event(vk=VK_SHIFT),
                        _key_event(vk=VK_RETURN),
                        _key_event(vk=VK_RETURN, flags=KEYEVENTF_KEYUP),
                        _key_event(vk=VK_SHIFT, flags=KEYEVENTF_KEYUP),
                    ])
                    time.sleep(0.03)
            return len(text)

        if self.paste:
            paste_text_shift_insert(text, restore=self.restore)
        else:
            type_text(text)
        return len(text)
