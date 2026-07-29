"""Backwards-compatible façade over `mywhisper.context`.

Foreground detection grew from "exe name + title" into a package (integrity
levels, caret text, target classification), but the old import path still
resolves so existing callers and tests need no change.
"""

from .context.win import _NOISE, Foreground, foreground, foreground_full, title_hotwords

__all__ = ["_NOISE", "Foreground", "foreground", "foreground_full",
           "title_hotwords"]
