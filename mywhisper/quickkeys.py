"""Secondary global hotkeys (paste-last, copy-last, polish, scratchpad…).

Separate from the main dictation hotkey on purpose: that one is a poll-only
single-key state machine tuned for hold/tap/double-tap; these are plain
chord shortcuts, which pynput's GlobalHotKeys handles well. Combos use
pynput syntax: "<shift>+<alt>+z", "<cmd>+<alt>+p" (<cmd> = Win key).
Invalid combos are skipped with a warning — one bad line in config must not
take down every shortcut.
"""

import logging
import threading

log = logging.getLogger(__name__)


class QuickKeys:
    def __init__(self, shortcuts_cfg: dict | None, actions: dict):
        """actions: {name: zero-arg callable}. Only names present in both the
        config (with a non-empty combo) and actions get bound. Callbacks run
        on their own thread — pynput's hook thread must never block."""
        self._listener = None
        mapping = {}
        try:
            from pynput import keyboard
        except ImportError:
            log.warning("pynput unavailable — quick shortcuts disabled")
            return
        for name, combo in (shortcuts_cfg or {}).items():
            fn = actions.get(name)
            if not combo or not fn:
                continue
            try:
                keyboard.HotKey.parse(combo)  # validate before registering
            except ValueError:
                log.warning("shortcut %s: invalid combo %r — skipped (syntax: "
                            "<shift>+<alt>+z)", name, combo)
                continue
            mapping[combo] = self._dispatch(name, fn)
        if mapping:
            try:
                self._listener = keyboard.GlobalHotKeys(mapping)
            except Exception:  # noqa: BLE001
                log.warning("global shortcuts unavailable", exc_info=True)
                self._listener = None

    @staticmethod
    def _dispatch(name, fn):
        def run():
            threading.Thread(target=fn, daemon=True,
                             name=f"quickkey-{name}").start()
        return run

    def start(self):
        if self._listener:
            self._listener.start()
            log.info("quick shortcuts armed")

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:  # noqa: BLE001
                pass
