"""Double-tap Right Alt, with keystrokes the operating system actually
delivers.

Everything else about the hotkey is tested by feeding `LongPressMachine`
timestamps directly, which proves the state machine is right and proves
nothing about whether the key is ever seen. The gap between those two is the
entire feature: `PollingKeyListener` reads `GetAsyncKeyState` on its own
thread at ~60Hz, and a wrong virtual-key code, a missing extended-key flag or
a listener that never started would all pass the state-machine tests while the
product did nothing when you tapped the key.

So these synthesise input through `SendInput` - the same Win32 call Svara uses
to type - and assert the real listener reacts. Nothing is mocked.

Note: this genuinely presses Right Alt on the desktop. Right Alt on its own
activates no command in Windows, and each press is released in the same test,
so it cannot leave a modifier stuck.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_hotkey_real_keys -v
"""

import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    # Reuse the app's OWN SendInput plumbing rather than redeclaring it. A
    # hand-rolled INPUT struct here was silently the wrong size on x64 - the
    # union has to be as large as its biggest member, MOUSEINPUT, not just
    # KEYBDINPUT - and SendInput answers a bad cbSize by returning 0 and doing
    # nothing. Borrowing the shipped structs means the test cannot drift from
    # what the product actually sends.
    from mywhisper.injector import (KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP,
                                    _key_event, _send as _send_inputs)

    def _send(vk: int, up: bool) -> None:
        """One key event. The extended-key flag is what makes this RIGHT alt
        rather than left - without it the OS reports the wrong key and the
        listener, correctly, ignores it."""
        flags = KEYEVENTF_EXTENDEDKEY | (KEYEVENTF_KEYUP if up else 0)
        _send_inputs([_key_event(vk=vk, flags=flags)])


@unittest.skipUnless(IS_WINDOWS, "SendInput and GetAsyncKeyState are Win32")
class TestDoubleTapWithRealKeystrokes(unittest.TestCase):
    """Drives the shipped PollingKeyListener, not a stand-in."""

    def setUp(self):
        from mywhisper import config as config_mod
        from mywhisper.hotkey import PollingKeyListener

        self.cfg = config_mod.load(None)["recording"]
        self.events: list[str] = []
        self.seen = threading.Event()

        def record(name):
            def hook(*_a, **_k):
                self.events.append(name)
                self.seen.set()
            return hook

        self.listener = PollingKeyListener(
            self.cfg,
            on_start=record("start"), on_commit=record("commit"),
            on_cancel=record("cancel"), on_lock=record("lock"),
            is_recording=lambda: "start" in self.events
                                 and "commit" not in self.events,
        )
        self.listener.start()
        self.addCleanup(self.listener.stop)
        time.sleep(0.15)   # let the polling thread reach its loop

    def vk(self) -> int:
        vks = self.listener.vks   # a set: the hotkey may resolve to several
        self.assertTrue(vks, f"{self.cfg['hotkey']!r} resolved to no key code")
        return sorted(vks)[0]

    def tap(self, hold: float = 0.05) -> None:
        vk = self.vk()
        _send(vk, up=False)
        time.sleep(hold)
        _send(vk, up=True)
        time.sleep(0.05)

    def wait(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(0.03)

    def test_the_configured_hotkey_is_right_alt(self):
        # 0xA5 is VK_RMENU. If this ever silently became left alt (0xA4) the
        # key would still "work" in tests while stealing a real modifier.
        self.assertEqual(self.cfg["hotkey"], "right alt")
        self.assertIn(0xA5, self.listener.vks)

    def test_the_listener_sees_a_real_keypress_at_all(self):
        # The single most basic claim, and the one nothing else covers.
        self.tap()
        self.wait(0.5)
        self.assertTrue(
            self.events,
            "SendInput delivered Right Alt and the listener reacted to "
            "nothing — the key is not actually being observed")

    def test_a_double_tap_starts_and_locks_dictation(self):
        """The documented gesture: tap twice, Svara listens hands-free."""
        gap = self.cfg["double_tap_ms"] / 1000.0
        self.tap()
        time.sleep(min(0.08, gap / 3))   # comfortably inside the window
        self.tap()
        self.wait(0.6)

        self.assertIn("start", self.events,
                      f"recording never began; saw {self.events}")
        self.assertIn("lock", self.events,
                      "the second tap did not lock — dictation would stop the "
                      f"moment the key came up. Saw {self.events}")
        self.assertTrue(self.listener.locked,
                        "listener does not report itself locked after a "
                        "double-tap")

    def test_two_slow_taps_do_not_lock(self):
        # Otherwise any two unrelated presses minutes apart would start
        # hands-free recording.
        gap = self.cfg["double_tap_ms"] / 1000.0
        self.tap()
        time.sleep(gap + 0.25)
        self.tap()
        self.wait(0.4)
        self.assertNotIn("lock", self.events,
                         f"taps {gap + 0.25:.2f}s apart locked, but the "
                         f"double-tap window is only {gap:.2f}s")
        self.assertFalse(self.listener.locked)

    def test_a_press_while_locked_finishes_the_recording(self):
        # The other half of hands-free: one more tap must end it, or the user
        # has no way to stop without the mouse.
        gap = self.cfg["double_tap_ms"] / 1000.0
        self.tap()
        time.sleep(min(0.08, gap / 3))
        self.tap()
        self.wait(0.4)
        self.assertTrue(self.listener.locked, "precondition: never locked")

        self.events.clear()
        self.tap()
        self.wait(0.4)
        self.assertIn("commit", self.events,
                      f"a tap while locked did not finish dictation; "
                      f"saw {self.events}")
        self.assertFalse(self.listener.locked, "still locked after committing")

    def test_a_long_press_commits_rather_than_locking(self):
        # Push-to-talk: hold, speak, release.
        hold = self.cfg["long_press_ms"] / 1000.0 + 0.2
        self.tap(hold=hold)
        self.wait(0.4)
        self.assertIn("start", self.events)
        self.assertIn("commit", self.events,
                      f"holding for {hold:.2f}s did not commit; "
                      f"saw {self.events}")
        self.assertNotIn("lock", self.events, "a long press must not lock")


if __name__ == "__main__":
    unittest.main()
