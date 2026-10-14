"""System-wide text injection on Linux/Wayland.

Wayland lets no client type into another, so the keystrokes come from a
kernel-level virtual keyboard (`/dev/uinput`, via python-evdev) that the
compositor treats like real hardware, and the clipboard goes through
wl-clipboard (`wl-copy` / `wl-paste`). Same surface as `injector_win`:

- `type_text`  — per-key uinput events. Keycodes mean "US layout", so any
                 text outside printable ASCII rides the clipboard instead.
- `paste_text` — wl-copy + Ctrl+V, previous clipboard restored afterwards.

Requirements: the user can open /dev/uinput (an ACL or the `input` group) and
wl-clipboard is installed. Both failures surface as OSError to the strategies.
"""

import logging
import shutil
import subprocess
import threading
import time

from .redact import E_INJ_CLIP

log = logging.getLogger(__name__)

# Set by the Hyprland hotkey listener: cleared on key down, set on key up. The
# injector waits on it so the dictation key is never still held (as a live
# modifier) when the first synthetic key arrives.
hotkey_up = threading.Event()
hotkey_up.set()

_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6",
            "&": "7", "*": "8", "(": "9", ")": "0", "_": "MINUS", "+": "EQUAL",
            "{": "LEFTBRACE", "}": "RIGHTBRACE", "|": "BACKSLASH",
            ":": "SEMICOLON", '"': "APOSTROPHE", "<": "COMMA", ">": "DOT",
            "?": "SLASH", "~": "GRAVE"}
_PLAIN = {" ": "SPACE", "-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE",
          "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON",
          "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH",
          "`": "GRAVE", "\n": "ENTER", "\t": "TAB"}


def keycode(ch: str) -> tuple[str, bool] | None:
    """(evdev KEY_* name, needs_shift) for one printable-ASCII char, else None."""
    if ch.isascii() and ch.isalpha():
        return f"KEY_{ch.upper()}", ch.isupper()
    if ch.isascii() and ch.isdigit():
        return f"KEY_{ch}", False
    if ch in _PLAIN:
        return f"KEY_{_PLAIN[ch]}", False
    if ch in _SHIFTED:
        return f"KEY_{_SHIFTED[ch]}", True
    return None


_lock = threading.Lock()
_ui = None


def _keyboard():
    """The one virtual keyboard, created on first use."""
    global _ui
    with _lock:
        if _ui is None:
            from evdev import UInput

            _ui = UInput(name="svara-virtual-keyboard")
            # The compositor picks a new device up asynchronously; keys sent
            # before that are lost. One pause per process, not per dictation.
            time.sleep(0.6)
        return _ui


def _tap(ui, code: int, shift: bool = False):
    from evdev import ecodes as e

    if shift:
        ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
    ui.write(e.EV_KEY, code, 1)
    ui.write(e.EV_KEY, code, 0)
    if shift:
        ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
    ui.syn()


def _chord(mod: str, key: str):
    from evdev import ecodes as e

    ui = _keyboard()
    ui.write(e.EV_KEY, getattr(e, mod), 1)
    ui.write(e.EV_KEY, getattr(e, key), 1)
    ui.write(e.EV_KEY, getattr(e, key), 0)
    ui.write(e.EV_KEY, getattr(e, mod), 0)
    ui.syn()
    time.sleep(0.03)


def wait_modifiers_released(timeout: float = 2.0):
    """Block until the dictation key is up (or timeout). Wayland exposes no
    global modifier state, so this is the one key we can know about; a short
    grace period covers the other hand lifting off a combo."""
    if not hotkey_up.wait(timeout):
        log.warning("dictation key still held after %.1fs — injecting anyway", timeout)
    time.sleep(0.05)


def type_text(text: str):
    """Type text into the focused window through the virtual keyboard."""
    from evdev import ecodes as e

    text = text.replace("\r", "")
    if not text:
        return
    keys = [keycode(ch) for ch in text]
    if any(k is None for k in keys):
        # shortcut: uinput only speaks US-layout keycodes; non-ASCII text (or a
        # non-US layout) needs the clipboard. Upgrade: the virtual-keyboard
        # Wayland protocol with a per-text keymap, as wtype does.
        paste_text(text)
        return
    ui = _keyboard()
    for name, shift in keys:
        _tap(ui, getattr(e, name), shift)
        time.sleep(0.0005)


# --- Clipboard method -----------------------------------------------------------

def _clipboard_get() -> str | None:
    try:
        r = subprocess.run(["wl-paste", "-n", "-t", "text"], capture_output=True,
                           timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None  # empty, or not text
    return r.stdout.decode("utf-8", errors="replace")


def _clipboard_set(text: str) -> bool:
    if not shutil.which("wl-copy"):
        log.error("%s wl-clipboard is not installed (pacman -S wl-clipboard)", E_INJ_CLIP)
        return False
    try:
        # wl-copy forks a server for the selection and returns at once.
        r = subprocess.run(["wl-copy"], input=text.encode("utf-8"), timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        log.error("%s wl-copy failed", E_INJ_CLIP, exc_info=True)
        return False
    return r.returncode == 0


def _paste_with(mod: str, key: str, text: str, restore: bool):
    old = _clipboard_get() if restore else None
    if not _clipboard_set(text):
        log.warning("clipboard set failed — falling back to direct typing")
        type_text(text)
        return
    time.sleep(0.05)  # let wl-copy's server own the selection first
    _chord(mod, key)
    if restore and old is not None:
        def _restore():
            time.sleep(0.5)  # the target reads the clipboard first
            _clipboard_set(old)
        threading.Thread(target=_restore, daemon=True).start()


def paste_text(text: str, restore: bool = True):
    _paste_with("KEY_LEFTCTRL", "KEY_V", text, restore)


def paste_text_shift_insert(text: str, restore: bool = True):
    """Clipboard + Shift+Insert for terminals, where Ctrl+V is not paste."""
    _paste_with("KEY_LEFTSHIFT", "KEY_INSERT", text, restore)


def copy_selection():
    """Ctrl+C to the focused window — transforms read the selection this way."""
    wait_modifiers_released()
    _chord("KEY_LEFTCTRL", "KEY_C")


def backspace(n: int):
    """Erase the last n characters of the focused field."""
    from evdev import ecodes as e

    ui = _keyboard()
    for _ in range(max(0, n)):
        _tap(ui, e.KEY_BACKSPACE)
        time.sleep(0.0005)


def press_shift_enter():
    """Shift+Enter — the soft line break TUI agents understand."""
    _chord("KEY_LEFTSHIFT", "KEY_ENTER")
