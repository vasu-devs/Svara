"""The desktop windows' type, and how the bundled face gets to Tk.

Three roles, the same as the website:

- **Newsreader** sets the words - headlines and the live test box - because
  the product is named for a musical note and the site already speaks in this
  serif. It ships in ``assets/`` (OFL licence alongside) and is loaded into
  the process privately with ``AddFontResourceExW(FR_PRIVATE)``: Tk on Windows
  draws through GDI, so a privately registered face is available by name
  without touching the user's font folder. Georgia is the fallback.
- **Segoe UI** does the interface work: labels, buttons, dropdowns.
- **Cascadia Mono** (Windows 11) or **Consolas** carries keys, versions,
  timecodes and anything the user might copy.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

log = logging.getLogger(__name__)

SERIF_FALLBACK = "Georgia"
UI = "Segoe UI"
DEVANAGARI = "Nirmala UI"

_loaded: bool | None = None
_mono: str | None = None


def _asset(name: str) -> str | None:
    roots = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for base in roots:
        if base:
            p = os.path.join(base, "assets", name)
            if os.path.exists(p):
                return p
    return None


def load_private_fonts() -> bool:
    """Register the bundled serif with GDI for this process only. Idempotent;
    safe to call from any window builder. Returns True if Tk can use it."""
    global _loaded
    if _loaded is not None:
        return _loaded
    _loaded = False
    if not sys.platform.startswith("win"):
        return False
    path = _asset("Newsreader.ttf")
    if not path:
        return False
    try:
        FR_PRIVATE = 0x10
        added = ctypes.windll.gdi32.AddFontResourceExW(path, FR_PRIVATE, 0)
        _loaded = bool(added)
    except Exception:  # noqa: BLE001 - a missing GDI is not worth a crash
        log.debug("private font load failed", exc_info=True)
    return _loaded


def serif_family() -> str:
    return "Newsreader" if load_private_fonts() else SERIF_FALLBACK


def ui_family() -> str:
    return UI


def mono_family(root=None) -> str:
    """Cascadia Mono where Windows 11 has it, Consolas everywhere else. The
    check needs a Tk root; without one the safe answer is Consolas."""
    global _mono
    if _mono is not None:
        return _mono
    if root is None:
        return "Consolas"
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        _mono = "Cascadia Mono" if "Cascadia Mono" in fams else "Consolas"
    except Exception:  # noqa: BLE001
        _mono = "Consolas"
    return _mono
