"""Inline preview at the caret: Svara as a Wayland input method.

A virtual keyboard can only append and delete at the end of a text field, so
every polished sentence meant backspacing and retyping. The input-method
protocol (zwp_input_method_v2, what fcitx/ibus use) lets the compositor hand
us the focused text field instead: we set *preedit* text, which the app draws
inline at the caret (usually underlined, in its own preview styling), replace
it silently as often as we like, and `commit_string` the final text once.

Only apps that implement text-input-v3 take part (GTK, Qt, kitty, Firefox,
Chromium/Electron with `--enable-wayland-ime`); for the rest `active` stays
False and the app falls back to the keystroke path. One input method per
seat: if fcitx5 or ibus runs, the compositor says `unavailable` and we step
aside.

Threading: libwayland is thread-safe for requests. One thread blocks in
`dispatch`; the streamer and worker call `preedit`/`commit` directly and
flush. Nothing here logs text.
"""

import logging
import os
import threading

log = logging.getLogger(__name__)


class ImePreview:
    def __init__(self):
        self.available = False
        self.active = False
        self._pending_active = False
        self._serial = 0
        self._display = None
        self._im = None
        self._lock = threading.Lock()
        if not os.environ.get("WAYLAND_DISPLAY"):
            return
        try:
            self._connect()
        except Exception as e:  # noqa: BLE001 — no IME is a fallback, not a failure
            log.info("inline preview unavailable (%s: %s) — keystroke path only",
                     type(e).__name__, e)
            self._display = None

    def _connect(self):
        from pywayland.client import Display
        from .wayland.protocols.input_method_unstable_v2 import ZwpInputMethodManagerV2
        from .wayland.protocols.wayland import WlSeat

        self._display = Display()
        self._display.connect()
        registry = self._display.get_registry()
        found = {}

        def on_global(reg, name, interface, version):
            if interface == "wl_seat" and "seat" not in found:
                found["seat"] = reg.bind(name, WlSeat, min(version, 7))
            elif interface == "zwp_input_method_manager_v2":
                found["mgr"] = reg.bind(name, ZwpInputMethodManagerV2, 1)

        registry.dispatcher["global"] = on_global
        self._display.roundtrip()
        if "seat" not in found or "mgr" not in found:
            raise RuntimeError("compositor offers no input-method manager")
        self._im = found["mgr"].get_input_method(found["seat"])
        self._im.dispatcher["activate"] = lambda im: self._set_pending(True)
        self._im.dispatcher["deactivate"] = lambda im: self._set_pending(False)
        self._im.dispatcher["done"] = lambda im: self._on_done()
        self._im.dispatcher["unavailable"] = lambda im: self._on_unavailable()
        self._display.roundtrip()
        self.available = self._im is not None
        threading.Thread(target=self._loop, daemon=True, name="ime").start()
        log.info("inline preview armed (Wayland input method)")

    # -- events (dispatch thread) ---------------------------------------------------

    def _set_pending(self, active: bool):
        self._pending_active = active

    def _on_done(self):
        # Per protocol the activate/deactivate state applies on `done`, and
        # every request batch we send must quote the number of `done`s seen.
        self._serial += 1
        self.active = self._pending_active

    def _on_unavailable(self):
        self.available = self.active = False
        log.warning("another input method owns the seat (fcitx/ibus?) — inline "
                    "preview off, keystroke path only")

    def _loop(self):
        try:
            while self._display is not None:
                self._display.dispatch(block=True)
        except Exception:  # noqa: BLE001 — a dead connection = no preview
            log.info("inline preview connection closed", exc_info=True)
            self.available = self.active = False

    # -- requests (any thread) ----------------------------------------------------

    def preedit(self, text: str) -> bool:
        """Show `text` inline at the caret, caret at its end. False when no
        text field is ours right now."""
        if not self.active:
            return False
        with self._lock:
            n = len(text.encode("utf-8"))
            self._im.set_preedit_string(text, n, n)
            self._im.commit(self._serial)
            self._display.flush()
        return True

    def commit(self, text: str) -> bool:
        """Replace the preview with final text."""
        if not self.active:
            return False
        with self._lock:
            self._im.set_preedit_string("", 0, 0)
            self._im.commit_string(text)
            self._im.commit(self._serial)
            self._display.flush()
        return True

    def clear(self) -> None:
        if self.active:
            with self._lock:
                self._im.set_preedit_string("", 0, 0)
                self._im.commit(self._serial)
                self._display.flush()
