"""Global hotkey listening — two styles, auto-detected from the config value.

Single key ("right ctrl", "f8", "num 0" — no "+"): Wispr-Flow-style long-press.
    - Key down        → recording starts instantly (pre-roll covers early words)
    - Hold ≥ long_press_ms, release → commit (transcribe + inject)
    - Quick tap       → cancel silently (so accidental taps do nothing)
    - Double-tap      → LOCK: hands-free recording; tap again to finish
    Implemented with pynput's low-level Win32 hook filter so the key can be
    suppressed (apps never see it) and our own injected keystrokes are ignored.

Combo ("ctrl+win", "ctrl+shift+space"): classic hold-to-record / press-to-toggle.
"""

import ctypes
import logging
import queue
import threading
import time

from pynput import keyboard

log = logging.getLogger(__name__)

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
LLKHF_INJECTED = 0x10  # event came from SendInput (i.e. from our own injector)

_MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}


# --------------------------------------------------------------------------
# Key-name → virtual-key-code resolution (single-key mode)
# --------------------------------------------------------------------------

def _build_vk_table() -> dict[str, set[int]]:
    t: dict[str, set[int]] = {
        "ctrl": {0xA2, 0xA3}, "leftctrl": {0xA2}, "rightctrl": {0xA3},
        "alt": {0xA4, 0xA5}, "leftalt": {0xA4}, "rightalt": {0xA5},
        "shift": {0xA0, 0xA1}, "leftshift": {0xA0}, "rightshift": {0xA1},
        "win": {0x5B, 0x5C}, "leftwin": {0x5B}, "rightwin": {0x5C},
        "apps": {0x5D}, "menu": {0x5D},
        "capslock": {0x14}, "scrolllock": {0x91}, "pause": {0x13},
        "space": {0x20}, "tab": {0x09}, "esc": {0x1B}, "escape": {0x1B},
        "insert": {0x2D}, "delete": {0x2E}, "home": {0x24}, "end": {0x23},
        "pageup": {0x21}, "pagedown": {0x22},
        "numlock": {0x90},
        "numplus": {0x6B}, "numminus": {0x6D}, "numstar": {0x6A},
        "nummultiply": {0x6A}, "numslash": {0x6F}, "numdivide": {0x6F},
        "numdot": {0x6E}, "numdecimal": {0x6E},
        # Fn: ONLY works on laptops whose firmware exposes it to Windows
        # (many don't — run `run.bat --probe` and press Fn to find out).
        "fn": {0xFF},
    }
    for i in range(1, 25):
        t[f"f{i}"] = {0x70 + i - 1}
    for i in range(10):
        t[f"num{i}"] = {0x60 + i}
        t[f"numpad{i}"] = {0x60 + i}
    for c in "abcdefghijklmnopqrstuvwxyz":
        t[c] = {ord(c.upper())}
    for c in "0123456789":
        t[c] = {ord(c)}
    return t


_VK_TABLE = _build_vk_table()


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def resolve_vks(spec: str) -> set[int]:
    key = _normalize(spec)
    if key.startswith("vk"):  # escape hatch: bind any raw code, e.g. "vk255" / "vk0xff"
        try:
            return {int(key[2:], 0)}
        except ValueError:
            pass
    if key not in _VK_TABLE:
        raise ValueError(
            f"Unknown hotkey {spec!r}. Examples: right ctrl, f8, caps lock, "
            f"num 0, scroll lock, pause, right alt, vk255"
        )
    return _VK_TABLE[key]


# --------------------------------------------------------------------------
# Long-press state machine (pure logic — unit-testable, no Windows deps)
# --------------------------------------------------------------------------

class LongPressMachine:
    """Feed key_down/key_up with timestamps; get back an action string."""

    def __init__(self, long_press_s: float, double_tap_s: float,
                 double_tap_lock: bool = True):
        self.long_press_s = long_press_s
        self.double_tap_s = double_tap_s
        self.double_tap_lock = double_tap_lock
        self.locked = False
        self._down = False
        self._t_down = 0.0
        self._last_tap = 0.0
        self._commit_on_down = False

    def key_down(self, now: float) -> str | None:
        if self._down:
            return None  # keyboard autorepeat
        self._down = True
        self._t_down = now
        if self.locked:
            # Any press while locked finishes the hands-free recording.
            self.locked = False
            self._commit_on_down = True
            self._last_tap = 0.0
            return "commit"
        return "start"

    def key_up(self, now: float) -> str | None:
        if not self._down:
            return None
        self._down = False
        if self._commit_on_down:
            self._commit_on_down = False
            return None  # already committed on the way down
        held = now - self._t_down
        if held >= self.long_press_s:
            self._last_tap = 0.0
            return "commit"
        # It was a tap.
        if (self.double_tap_lock and self._last_tap > 0
                and (now - self._last_tap) <= self.double_tap_s):
            self._last_tap = 0.0
            self.locked = True
            return "lock"  # keep recording, hands-free
        self._last_tap = now
        return "cancel"


# --------------------------------------------------------------------------
# Single-key listener (Win32 low-level hook via pynput)
# --------------------------------------------------------------------------

class PollingKeyListener:
    """Track ONE key by polling GetAsyncKeyState — installs NO system hook.

    This is the robust default: we never sit in the system keyboard input
    chain, so we cannot lag or break any other key (the low-level-hook design
    could). We just read our single key's live state ~60×/s on our own thread.

    Trade-off: the key is observed, not suppressed — but a dedicated key like
    Right Alt does nothing important, so that's fine and much safer.
    """

    def __init__(self, rec_cfg: dict, on_start, on_commit, on_cancel, on_lock,
                 is_recording):
        self.spec = rec_cfg["hotkey"]
        self.vks = resolve_vks(self.spec)
        self.mode = rec_cfg["mode"]
        self.on_start = on_start
        self.on_commit = on_commit
        self.on_cancel = on_cancel
        self.on_lock = on_lock
        self.is_recording = is_recording
        self.machine = LongPressMachine(
            long_press_s=rec_cfg["long_press_ms"] / 1000.0,
            double_tap_s=rec_cfg["double_tap_ms"] / 1000.0,
            double_tap_lock=bool(rec_cfg["double_tap_lock"]),
        )
        self._down = False
        self._run = False
        self._thread = None

    @property
    def locked(self) -> bool:
        return self.machine.locked

    @property
    def held(self) -> bool:
        return self._down

    def start(self):
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="hotkey-poll")
        self._thread.start()
        verb = ("press twice to talk (tap to stop)"
                if self.mode != "press_to_toggle" else "press to toggle")
        log.info("Hotkey armed: [%s] — %s · no system hook (poll-only)",
                 self.spec, verb)

    def stop(self):
        self._run = False

    def _pressed(self) -> bool:
        return any(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
                   for vk in self.vks)

    def _loop(self):
        while self._run:
            try:
                now = time.monotonic()
                down = self._pressed()
                action = None
                if down and not self._down:
                    self._down = True
                    if self.mode == "press_to_toggle":
                        action = "commit" if self.is_recording() else "start"
                    else:
                        action = self.machine.key_down(now)
                elif not down and self._down:
                    self._down = False
                    if self.mode != "press_to_toggle":
                        action = self.machine.key_up(now)
                if action:
                    self._dispatch(action)
            except Exception:  # noqa: BLE001 — poll loop must never die
                log.exception("hotkey poll failed")
            time.sleep(0.016)  # ~60 Hz

    def _dispatch(self, action: str):
        if action == "start":
            self.on_start()
        elif action == "commit":
            self.on_commit()
        elif action == "cancel":
            self.on_cancel()
        elif action == "lock":
            self.on_lock()


class SingleKeyListener:
    def __init__(self, rec_cfg: dict, on_start, on_commit, on_cancel, on_lock,
                 is_recording):
        self.spec = rec_cfg["hotkey"]
        self.vks = resolve_vks(self.spec)
        self.mode = rec_cfg["mode"]
        self.on_start = on_start
        self.on_commit = on_commit
        self.on_cancel = on_cancel
        self.on_lock = on_lock
        self.is_recording = is_recording

        self.machine = LongPressMachine(
            long_press_s=rec_cfg["long_press_ms"] / 1000.0,
            double_tap_s=rec_cfg["double_tap_ms"] / 1000.0,
            double_tap_lock=bool(rec_cfg["double_tap_lock"]),
        )

        sup = rec_cfg["suppress_key"]
        if sup == "auto" or sup is None:
            # Swallow keys that would otherwise do something in apps (F8,
            # CapsLock, numpad digits…); leave bare modifiers alone.
            self.suppress = not (self.vks <= _MODIFIER_VKS)
        else:
            self.suppress = bool(sup)

        self._listener = keyboard.Listener(win32_event_filter=self._filter)
        # CRITICAL: the win32 filter runs inside the SYSTEM INPUT CHAIN — every
        # keystroke on the machine waits for it. It must only flip the state
        # machine and enqueue; the actual work happens on this thread instead.
        self._actions: queue.Queue = queue.Queue()
        threading.Thread(target=self._action_loop, daemon=True,
                         name="hotkey-dispatch").start()
        self._prio_set = False

    def _action_loop(self):
        while True:
            action = self._actions.get()
            try:
                self._dispatch(action)
            except Exception:  # noqa: BLE001
                log.exception("hotkey action failed")

    @property
    def locked(self) -> bool:
        return self.machine.locked

    @property
    def held(self) -> bool:
        """True while the hotkey is physically down — synthetic keystrokes sent
        now would combine with it (Alt+…!) and get eaten by the focused app."""
        return self.machine._down

    def start(self):
        self._listener.start()
        log.info(
            "Hotkey armed: long-press [%s] to talk · tap = cancel · "
            "double-tap = hands-free lock%s",
            self.spec, " · key suppressed from apps" if self.suppress else "",
        )

    def stop(self):
        self._listener.stop()

    def _filter(self, msg, data):
        try:
            if not self._prio_set:
                # The hook thread gates ALL system keyboard input — make sure
                # the scheduler always runs it promptly.
                self._prio_set = True
                try:
                    ctypes.windll.kernel32.SetThreadPriority(
                        ctypes.windll.kernel32.GetCurrentThread(), 15)
                except Exception:  # noqa: BLE001
                    pass
            if data.vkCode not in self.vks:
                return True
            if data.flags & LLKHF_INJECTED:
                return True  # our own SendInput events — never react to these
            now = time.monotonic()
            action = None
            if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if self.mode == "press_to_toggle":
                    action = "commit" if self.is_recording() else "start"
                else:
                    action = self.machine.key_down(now)
            elif msg in (WM_KEYUP, WM_SYSKEYUP):
                if self.mode != "press_to_toggle":
                    action = self.machine.key_up(now)
            if action:
                self._actions.put(action)  # heavy work happens OFF this thread
        except Exception:  # noqa: BLE001 — never break the low-level hook
            log.exception("hotkey filter failed")
            return True
        if self.suppress:
            # Must be last: raises internally to swallow the event system-wide.
            self._listener.suppress_event()
        return True

    def _dispatch(self, action: str):
        if action == "start":
            self.on_start()
        elif action == "commit":
            self.on_commit()
        elif action == "cancel":
            self.on_cancel()
        elif action == "lock":
            self.on_lock()


# --------------------------------------------------------------------------
# Combo listener (ctrl+win etc.) — the original behavior
# --------------------------------------------------------------------------

_ALIASES = {
    "control": "ctrl",
    "windows": "win", "cmd": "win", "super": "win", "meta": "win",
    "option": "alt",
    "escape": "esc",
    "return": "enter",
    "spacebar": "space",
}


def parse_combo(spec: str) -> frozenset[str]:
    tokens = []
    for raw in spec.split("+"):
        t = raw.strip().lower()
        if t:
            tokens.append(_ALIASES.get(t, t))
    if not tokens:
        raise ValueError(f"Empty hotkey spec: {spec!r}")
    return frozenset(tokens)


def _canon(key) -> str | None:
    if isinstance(key, keyboard.Key):
        n = key.name
        if n.startswith("ctrl"):
            return "ctrl"
        if n.startswith("alt"):
            return "alt"
        if n.startswith("shift"):
            return "shift"
        if n.startswith("cmd"):
            return "win"
        return n
    if isinstance(key, keyboard.KeyCode):
        vk = getattr(key, "vk", None)
        if vk is not None:
            if 0x41 <= vk <= 0x5A:
                return chr(vk).lower()
            if 0x30 <= vk <= 0x39:
                return chr(vk)
        if key.char:
            return key.char.lower()
    return None


class ComboListener:
    locked = False  # combos have no hands-free lock mode

    @property
    def held(self) -> bool:
        return self._satisfied

    def __init__(self, rec_cfg: dict, on_start, on_commit, on_cancel, on_lock,
                 is_recording):
        self.combo = parse_combo(rec_cfg["hotkey"])
        self.mode = rec_cfg["mode"]
        self.on_start = on_start
        self.on_commit = on_commit
        self.is_recording = is_recording
        self._down: set[str] = set()
        self._satisfied = False
        self._listener = keyboard.Listener(
            on_press=self._press, on_release=self._release
        )

    def start(self):
        self._listener.start()
        log.info(
            "Hotkey armed: %s (%s)",
            "+".join(sorted(self.combo)),
            "hold to talk" if self.mode == "hold_to_record" else "press to toggle",
        )

    def stop(self):
        self._listener.stop()

    def _press(self, key):
        try:
            c = _canon(key)
            if c is None or c not in self.combo:
                return
            self._down.add(c)
            if self._satisfied or self._down < self.combo:
                return
            self._satisfied = True
            if self.mode == "hold_to_record":
                self.on_start()
            elif self.is_recording():
                self.on_commit()
            else:
                self.on_start()
        except Exception:  # noqa: BLE001
            log.exception("hotkey press handler failed")

    def _release(self, key):
        try:
            c = _canon(key)
            if c is None or c not in self.combo:
                return
            self._down.discard(c)
            if self._satisfied:
                self._satisfied = False
                if self.mode == "hold_to_record":
                    self.on_commit()
        except Exception:  # noqa: BLE001
            log.exception("hotkey release handler failed")


def create_listener(rec_cfg: dict, on_start, on_commit, on_cancel, on_lock,
                    is_recording):
    """Pick the transport for the configured hotkey.

    Single key → PollingKeyListener (no system hook; robust default). Only if
    the user explicitly sets `suppress_key: true` AND wants the key hidden from
    other apps do we fall back to the low-level hook (SingleKeyListener).
    Combos always use the hook-based ComboListener.
    """
    if "+" in rec_cfg["hotkey"]:
        cls = ComboListener
    elif rec_cfg.get("suppress_key") is True:
        cls = SingleKeyListener   # opt-in: needs the hook to swallow the key
    else:
        cls = PollingKeyListener  # default: safe, no global hook
    return cls(rec_cfg, on_start, on_commit, on_cancel, on_lock, is_recording)


def run_probe(seconds: int = 20):
    """`--probe`: press keys and see what Windows receives — find your Fn key.

    If pressing Fn prints NOTHING, your laptop handles Fn entirely in firmware
    and no Windows app can use it as a hotkey (pick another key instead).
    """
    print(f"Key probe — press keys to identify them (watching {seconds}s, Esc quits).")
    print("Press the key you want as your dictation key — e.g. Fn — and watch:\n")

    def on_press(key):
        if isinstance(key, keyboard.Key):
            vk = key.value.vk
            print(f"  {key.name:<16} vk={vk:<4} → use hotkey name: '{key.name}'")
            if key == keyboard.Key.esc:
                return False
        else:
            vk = getattr(key, "vk", None)
            label = repr(key.char) if key.char else "(no char)"
            print(f"  {label:<16} vk={vk:<4} → use hotkey: 'vk{vk}'")
        return True

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    listener.join(seconds)
    listener.stop()
    print("\nDone. If Fn printed nothing, it is firmware-only on this laptop —")
    print("good alternatives with the same long-press behavior: caps lock, f8, num 0.")
