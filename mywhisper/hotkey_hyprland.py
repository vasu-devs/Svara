"""The dictation key on Hyprland (Wayland).

No process can hook the keyboard on Wayland, so the compositor does it for
us: Svara registers a press bind and a release bind for the configured key
through `hyprctl eval` (Hyprland's Lua config API). Each one `exec`s a
one-line write of "down" / "up" into a FIFO under $XDG_RUNTIME_DIR, and the
reader thread feeds the same LongPressMachine the Windows poller uses — hold,
tap, double-tap and press-to-toggle behave identically. The binds are removed
again on shutdown. Like Windows' `suppress_key`, the key is consumed: a
dedicated key such as Right Alt no longer reaches other apps while Svara runs.

Try it without a key: `echo down > $XDG_RUNTIME_DIR/svara-hotkey.fifo`.
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from . import injector_wayland
from .hotkey import PollingKeyListener, _normalize

log = logging.getLogger(__name__)

_MODS = {"ctrl": "CTRL", "control": "CTRL", "shift": "SHIFT", "alt": "ALT",
         "win": "SUPER", "super": "SUPER", "cmd": "SUPER"}

# normalized config name → (xkb keysym, the modifier mask it carries while held)
_KEYS: dict[str, tuple[str, str | None]] = {
    "rightalt": ("Alt_R", "ALT"), "leftalt": ("Alt_L", "ALT"),
    "rightctrl": ("Control_R", "CTRL"), "leftctrl": ("Control_L", "CTRL"),
    "rightshift": ("Shift_R", "SHIFT"), "leftshift": ("Shift_L", "SHIFT"),
    "rightwin": ("Super_R", "SUPER"), "leftwin": ("Super_L", "SUPER"),
    "capslock": ("Caps_Lock", None), "scrolllock": ("Scroll_Lock", None),
    "pause": ("Pause", None), "space": ("space", None), "tab": ("Tab", None),
    "esc": ("Escape", None), "escape": ("Escape", None),
    "insert": ("Insert", None), "delete": ("Delete", None),
    "home": ("Home", None), "end": ("End", None),
    "pageup": ("Prior", None), "pagedown": ("Next", None),
    "numlock": ("Num_Lock", None), "menu": ("Menu", None), "apps": ("Menu", None),
}
for _i in range(1, 25):
    _KEYS[f"f{_i}"] = (f"F{_i}", None)
for _i in range(10):
    _KEYS[f"num{_i}"] = _KEYS[f"numpad{_i}"] = (f"KP_{_i}", None)
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    _KEYS[_c] = (_c, None)
_EITHER = {"alt": ("leftalt", "rightalt"), "ctrl": ("leftctrl", "rightctrl"),
           "shift": ("leftshift", "rightshift"), "win": ("leftwin", "rightwin")}


def combos(spec: str) -> list[str]:
    """Hyprland bind strings for a config hotkey ("right alt", "ctrl+shift+space").

    A lone modifier gets two entries: by the time Hyprland matches the bind
    the key's own mask is active, so "Alt_R" and "ALT + Alt_R" both describe
    the same press depending on timing. Duplicate events are harmless: the
    edge detector acts on changes only."""
    if "," in spec:   # several keys, each with the same gestures
        return [c for part in spec.split(",") if part.strip() for c in combos(part)]
    parts = [_normalize(p) for p in spec.split("+")]
    if len(parts) > 1:
        try:
            mods = [_MODS[p] for p in parts[:-1]]
            key, _ = _KEYS[parts[-1]]
        except KeyError as e:
            raise ValueError(f"unknown key in hotkey {spec!r}: {e}") from None
        return [" + ".join(mods + [key])]
    names = _EITHER.get(parts[0], (parts[0],))
    out = []
    for name in names:
        if name not in _KEYS:
            raise ValueError(f"unknown hotkey {spec!r}")
        key, mask = _KEYS[name]
        out.append(key)
        if mask:
            out.append(f"{mask} + {key}")
    return out


def fifo_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "svara-hotkey.fifo"


class HyprlandKeyListener(PollingKeyListener):
    """Same gestures as the Windows poller; the edges arrive from Hyprland."""

    def __init__(self, rec_cfg: dict, on_start, on_commit, on_cancel, on_lock,
                 is_recording, lua=None):
        super().__init__(rec_cfg, on_start, on_commit, on_cancel, on_lock,
                         is_recording)
        self.combos = combos(self.spec)
        self.fifo = fifo_path()
        self._lua = lua or _hyprctl_eval
        self._fd = -1

    def start(self):
        if not self.fifo.exists():
            os.mkfifo(self.fifo, 0o600)
        # Holding our own writer end keeps reads blocking instead of EOF-ing
        # between the compositor's one-shot writers.
        self._fd = os.open(self.fifo, os.O_RDWR)
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="hotkey-fifo")
        self._thread.start()
        self._bind()
        verb = ("press twice to talk (tap to stop)"
                if self.mode != "press_to_toggle" else "press to toggle")
        log.info("Hotkey armed: [%s] — %s · Hyprland binds %s", self.spec, verb,
                 ", ".join(self.combos))

    def stop(self):
        if not self._run:
            return
        self._run = False
        self._unbind()
        try:
            os.write(self._fd, b"quit\n")
        except OSError:
            pass

    def _bind(self):
        # `timeout` so a writer never hangs if Svara is gone; the FIFO blocks
        # writers without a reader.
        cmd = f"timeout 1 sh -c 'echo {{}} > {self.fifo}'"
        for combo in self.combos:
            self._lua(f"hl.unbind([[{combo}]])")  # a crashed run's leftovers
            self._lua(f"hl.bind([[{combo}]], hl.dsp.exec_cmd([[{cmd.format('down')}]]))")
            self._lua(f"hl.bind([[{combo}]], hl.dsp.exec_cmd([[{cmd.format('up')}]]), "
                      "{ release = true })")

    def _unbind(self):
        for combo in self.combos:
            self._lua(f"hl.unbind([[{combo}]])")

    def ensure_bound(self, listing: str | None = None) -> bool:
        """Runtime binds die with every Hyprland config reload (a theme
        change is enough). Called from the app's idle health loop: if the key
        is no longer in `hyprctl binds`, register again. Returns True when it
        had to."""
        if not self._run:
            return False
        if listing is None:
            try:
                listing = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True,
                                         text=True, timeout=3).stdout
            except (OSError, subprocess.SubprocessError):
                return False
        key = self.combos[0].split(" + ")[-1]
        if f'"key": "{key}"' in listing:
            return False
        log.warning("Hyprland dropped the dictation key binds (config reload?) — re-arming")
        self._bind()
        return True

    def _loop(self):
        buf = b""
        while self._run:
            try:
                chunk = os.read(self._fd, 256)
            except OSError:
                log.exception("hotkey fifo read failed")
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                tok = line.strip().decode("ascii", errors="replace")
                if tok == "quit":
                    os.close(self._fd)
                    return
                if tok == "stop":   # the island's stop button
                    if self.is_recording():
                        try:
                            self.on_commit()
                        except Exception:  # noqa: BLE001
                            log.exception("stop dispatch failed")
                    continue
                if tok == "skip":      # the onboarding page's "Skip this line"
                    cb = getattr(self, "on_skip", None)
                    if cb is not None:
                        try:
                            cb()
                        except Exception:  # noqa: BLE001
                            log.exception("skip dispatch failed")
                    continue
                if tok == "onboard":   # `./run.sh --onboard`: toggle the voice session
                    cb = getattr(self, "on_onboard", None)
                    if cb is not None:   # hands-free sessions are always recording: pause must still work
                        try:
                            cb()
                        except Exception:  # noqa: BLE001
                            log.exception("onboard dispatch failed")
                    continue
                if tok not in ("down", "up"):
                    continue
                down = tok == "down"
                (injector_wayland.hotkey_up.clear if down
                 else injector_wayland.hotkey_up.set)()
                try:
                    self._edge(down, time.monotonic())
                except Exception:  # noqa: BLE001 — the reader must never die
                    log.exception("hotkey dispatch failed")


def _hyprctl_eval(code: str) -> bool:
    try:
        r = subprocess.run(["hyprctl", "eval", code], capture_output=True,
                           text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        log.error("hyprctl unavailable — the dictation key is not bound. "
                  "Is this a Hyprland session?", exc_info=True)
        return False
    if r.stdout.strip() != "ok":
        log.error("hyprctl eval rejected %r: %s", code, (r.stdout + r.stderr).strip())
        return False
    return True
