"""Unit tests for mouse-button push-to-talk: the Win32 message filter, the
gesture mapping onto LongPressMachine, and the factory's never-raise contract.
The pynput hook itself is constructed but never started — no real hook here.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_mouse_ptt -v
"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.hotkey import (MOUSE_BUTTONS, MouseButtonListener,  # noqa: E402
                              create_mouse_listener)

REC = {"mouse_button": "x2", "mouse_suppress": True, "long_press_ms": 250,
       "double_tap_ms": 400, "double_tap_lock": True, "hotkey": "right alt",
       "mode": "hold_to_record"}

WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C


class _Data:
    def __init__(self, xbutton=0):
        self.mouseData = xbutton << 16


class Harness:
    """A listener with recorded callbacks and synchronous dispatch."""

    def __init__(self, rec=None):
        self.actions = []
        rec = dict(REC, **(rec or {}))
        self.listener = MouseButtonListener(
            rec,
            on_start=lambda: self.actions.append("start"),
            on_commit=lambda: self.actions.append("commit"),
            on_cancel=lambda: self.actions.append("cancel"),
            on_lock=lambda: self.actions.append("lock"),
            is_recording=lambda: False)
        # dispatch synchronously — tests must not race a thread
        self.listener._dispatch = lambda a: self.actions.append(a)
        self.suppressed = []
        self.listener._listener = mock.MagicMock()
        self.listener._listener.suppress_event = \
            lambda: self.suppressed.append(1)

    def press(self, msg, xbtn=0):
        return self.listener._filter(msg, _Data(xbtn))


class TestFilter(unittest.TestCase):
    def test_hold_release_is_ptt(self):
        h = Harness()
        h.press(WM_XBUTTONDOWN, 2)
        h.listener.machine._t_down -= 0.5   # simulate a 500 ms hold
        h.press(WM_XBUTTONUP, 2)
        self.assertEqual(h.actions, ["start", "commit"])

    def test_quick_click_cancels(self):
        h = Harness()
        h.press(WM_XBUTTONDOWN, 2)
        h.press(WM_XBUTTONUP, 2)
        self.assertEqual(h.actions, ["start", "cancel"])

    def test_double_click_locks_hands_free(self):
        h = Harness()
        h.press(WM_XBUTTONDOWN, 2)
        h.press(WM_XBUTTONUP, 2)          # tap 1 → cancel
        h.press(WM_XBUTTONDOWN, 2)
        h.press(WM_XBUTTONUP, 2)          # tap 2 within window → lock
        self.assertEqual(h.actions, ["start", "cancel", "start", "lock"])
        self.assertTrue(h.listener.locked)
        h.press(WM_XBUTTONDOWN, 2)        # any press while locked finishes
        self.assertIn("commit", h.actions)
        self.assertFalse(h.listener.locked)

    def test_other_x_button_ignored(self):
        h = Harness()
        h.press(WM_XBUTTONDOWN, 1)        # x1 while bound to x2
        self.assertEqual(h.actions, [])
        self.assertEqual(h.suppressed, [])

    def test_unrelated_messages_ignored(self):
        h = Harness()
        h.press(WM_MBUTTONDOWN)
        self.assertEqual(h.actions, [])

    def test_middle_button_binding(self):
        h = Harness({"mouse_button": "middle"})
        h.press(WM_MBUTTONDOWN)
        h.listener.machine._t_down -= 0.5
        h.press(WM_MBUTTONUP)
        self.assertEqual(h.actions, ["start", "commit"])

    def test_suppression_on_bound_button_only(self):
        h = Harness()
        h.press(WM_XBUTTONDOWN, 2)
        h.press(WM_XBUTTONUP, 2)
        self.assertEqual(len(h.suppressed), 2)

    def test_suppression_can_be_disabled(self):
        h = Harness({"mouse_suppress": False})
        h.press(WM_XBUTTONDOWN, 2)
        self.assertEqual(h.suppressed, [])

    def test_held_is_always_false(self):
        # A held mouse button eats no keystrokes — live typing must continue.
        h = Harness()
        h.press(WM_XBUTTONDOWN, 2)
        self.assertFalse(h.listener.held)


class TestFactory(unittest.TestCase):
    def test_none_when_unconfigured(self):
        self.assertIsNone(create_mouse_listener(
            dict(REC, mouse_button=None), *([lambda: None] * 5)))

    def test_bad_button_never_raises(self):
        self.assertIsNone(create_mouse_listener(
            dict(REC, mouse_button="left"), *([lambda: None] * 5)))

    def test_known_buttons(self):
        self.assertEqual(set(MOUSE_BUTTONS), {"middle", "x1", "x2"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
