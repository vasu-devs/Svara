"""How text gets from Svara into the app you're looking at.

`injector.py` holds the Win32 primitives (SendInput, clipboard, Shift+Insert).
This package decides *which* primitive to use, per target, which turns out to
matter more than it sounds:

- A paragraph typed into a shell prompt with embedded newlines **executes every
  line**. That is not a formatting bug, it is a "Svara just ran `rm` because I
  said the word" bug.
- `Ctrl+V` in a terminal is readline's quoted-insert, not paste.
- Character-by-character `SendInput` into a terminal emulator is visibly slow,
  because each keystroke round-trips through the PTY.
- Injecting into an elevated window from a non-elevated process silently does
  nothing at all — Windows' UIPI drops the input, `SendInput` reports success,
  and the user concludes Svara is broken.

One global `injection.method` setting cannot express any of that. A strategy
per target can.
"""

import logging
from typing import Protocol, runtime_checkable

from ..pipeline.base import UtteranceContext

log = logging.getLogger(__name__)


@runtime_checkable
class InjectionStrategy(Protocol):
    name: str

    def inject(self, text: str, ctx: UtteranceContext) -> int: ...


class BaseStrategy:
    name = "base"

    def prepare(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        """Last-chance text shaping specific to this target."""
        return text

    def inject(self, text: str, ctx: UtteranceContext) -> int:
        raise NotImplementedError
