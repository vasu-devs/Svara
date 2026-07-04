"""Registers Svara with Windows so it behaves like an installed app, even
though it's a single portable exe with no installer:

  - A Start Menu shortcut, so typing "Svara" into Windows Search finds it
    (a loose .exe sitting in Downloads is invisible to Search/Start — nothing
    indexes it as an app until something like this exists).

Safe to call on every launch: it no-ops once the shortcut already exists.
"""

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def _start_menu_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def ensure_start_menu_shortcut() -> None:
    """Create '<Start Menu>/Programs/Svara.lnk' pointing at the running exe,
    once. No-op on non-Windows, non-frozen (dev) runs, or if already done."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    programs = _start_menu_dir()
    if programs is None:
        return
    link_path = programs / "Svara.lnk"
    if link_path.exists():
        return
    try:
        programs.mkdir(parents=True, exist_ok=True)
        import comtypes.client

        target = sys.executable
        shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
        shortcut = shell.CreateShortcut(str(link_path))
        shortcut.TargetPath = target
        shortcut.WorkingDirectory = str(Path(target).parent)
        shortcut.IconLocation = target
        shortcut.Description = "Svara — private voice dictation"
        shortcut.Save()
        log.info("registered Start Menu shortcut so Windows Search finds Svara")
    except Exception:  # noqa: BLE001 — cosmetic OS integration, never fatal
        log.debug("Start Menu shortcut registration failed", exc_info=True)
