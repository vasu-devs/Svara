"""Double-tap Right Alt, and the app starts listening.

That gesture is the entire product. Everything else is downstream of it, and
until now nothing tested it: `test_livepath` mocks `create_listener` outright,
so it proves the pipeline works while saying nothing about the key that starts
it.

These tests drive the REAL polling listener - its own thread, its own state
machine, its own dispatch - and only stub the one function that reads the
physical key. So the gesture logic, the timing thresholds and the callback
wiring are all exercised, without sending Alt keystrokes at whatever window
happens to be focused.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_hotkey_gesture -v
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.hotkey import LongPressMachine, create_listener  # noqa: E402

REC_CFG = {
    "hotkey": "right alt",
    "mode": "hold_to_record",
    "long_press_ms": 250,
    "double_tap_lock": True,
    "double_tap_ms": 400,
    "suppress_key": False,
    "preroll_ms": 1000,
    "max_seconds": 600,
    "auto_stop": {"enabled": False, "silence_ms": 900, "min_speech_ms": 300},
}


class Recorder:
    """Records which callbacks fired, in order."""

    def __init__(self):
        self.events: list[str] = []
        self.recording = False

    def start(self):
        self.events.append("start")
        self.recording = True

    def commit(self):
        self.events.append("commit")
        self.recording = False

    def cancel(self):
        self.events.append("cancel")
        self.recording = False

    def lock(self):
        self.events.append("lock")


class KeyScript:
    """A scripted physical key: a list of (hold_down, seconds) steps that the
    listener's poll loop reads instead of GetAsyncKeyState."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.started = None
        self._lock = threading.Lock()

    def pressed(self) -> bool:
        with self._lock:
            if self.started is None:
                self.started = time.monotonic()
            elapsed = time.monotonic() - self.started
            at = 0.0
            for down, dur in self.steps:
                at += dur
                if elapsed < at:
                    return down
            return False

    @property
    def total(self) -> float:
        return sum(d for _s, d in self.steps)


class GestureCase(unittest.TestCase):
    def drive(self, steps, mode="hold_to_record", settle=0.45):
        """Run the real listener against a scripted key and return the events."""
        rec = Recorder()
        cfg = dict(REC_CFG, mode=mode)
        listener = create_listener(cfg, rec.start, rec.commit, rec.cancel,
                                   rec.lock, is_recording=lambda: rec.recording)
        script = KeyScript(steps)
        with mock.patch.object(type(listener), "_pressed",
                               lambda _self: script.pressed()):
            listener.start()
            time.sleep(script.total + settle)
            listener.stop()
        time.sleep(0.05)
        return rec.events


class TestTheGesture(GestureCase):
    def test_double_tap_starts_and_locks(self):
        # THE gesture: tap, tap, and Svara is listening hands-free.
        events = self.drive([(True, 0.08), (False, 0.10),
                             (True, 0.08), (False, 0.20)])
        self.assertIn("start", events, f"never started: {events}")
        self.assertIn("lock", events,
                      f"double-tap did not lock hands-free: {events}")

    def test_a_tap_after_locking_finishes(self):
        events = self.drive([(True, 0.08), (False, 0.10),   # double-tap
                             (True, 0.08), (False, 0.25),   # -> locked
                             (True, 0.08), (False, 0.15)])  # tap to finish
        self.assertIn("lock", events, events)
        self.assertIn("commit", events,
                      f"a tap while locked must finish: {events}")
        self.assertLess(events.index("lock"), events.index("commit"), events)

    def test_hold_is_push_to_talk(self):
        # Held past long_press_ms, released -> commit, not cancel.
        events = self.drive([(True, 0.45), (False, 0.15)])
        self.assertEqual(events[0], "start", events)
        self.assertIn("commit", events, f"hold should commit: {events}")
        self.assertNotIn("lock", events, events)

    def test_a_single_quick_tap_cancels(self):
        # Shorter than long_press_ms and no second tap -> discard.
        events = self.drive([(True, 0.08), (False, 0.30)])
        self.assertEqual(events[0], "start", events)
        self.assertIn("cancel", events, f"a lone quick tap cancels: {events}")
        self.assertNotIn("commit", events, events)

    def test_two_taps_too_far_apart_do_not_lock(self):
        # Beyond double_tap_ms they are two separate cancels, not a lock.
        events = self.drive([(True, 0.07), (False, 0.60),
                             (True, 0.07), (False, 0.25)])
        self.assertNotIn("lock", events,
                         f"taps 600ms apart must not count as a double: {events}")

    def test_the_key_never_being_pressed_does_nothing(self):
        self.assertEqual(self.drive([(False, 0.30)]), [])

    def test_the_poll_thread_survives_a_failing_read(self):
        # GetAsyncKeyState can throw during session switches. The loop must
        # keep running, or the hotkey silently dies for the rest of the session.
        rec = Recorder()
        listener = create_listener(dict(REC_CFG), rec.start, rec.commit,
                                   rec.cancel, rec.lock,
                                   is_recording=lambda: rec.recording)
        calls = {"n": 0}

        def flaky(_self):
            calls["n"] += 1
            if calls["n"] < 4:
                raise OSError("transient")
            return False

        with mock.patch.object(type(listener), "_pressed", flaky):
            listener.start()
            time.sleep(0.35)
            alive = listener._thread.is_alive()
            listener.stop()
        self.assertTrue(alive, "poll thread died on a transient read error")
        self.assertGreater(calls["n"], 4, "loop stopped polling")


class TestToggleMode(GestureCase):
    def test_press_to_toggle_starts_then_stops(self):
        events = self.drive([(True, 0.06), (False, 0.15),
                             (True, 0.06), (False, 0.15)],
                            mode="press_to_toggle")
        self.assertEqual(events[:1], ["start"], events)
        self.assertIn("commit", events, f"second press should stop: {events}")


class TestMachineThresholds(unittest.TestCase):
    """The timing rules on their own, without threads."""

    def machine(self):
        return LongPressMachine(long_press_s=0.25, double_tap_s=0.40,
                          double_tap_lock=True)

    def test_hold_commits(self):
        m = self.machine()
        self.assertEqual(m.key_down(0.0), "start")
        self.assertEqual(m.key_up(0.9), "commit")

    def test_quick_tap_cancels(self):
        m = self.machine()
        m.key_down(0.0)
        self.assertEqual(m.key_up(0.05), "cancel")

    def test_second_quick_tap_locks(self):
        m = self.machine()
        m.key_down(0.0)
        m.key_up(0.05)
        m.key_down(0.10)
        self.assertEqual(m.key_up(0.15), "lock")
        self.assertTrue(m.locked)

    def test_press_while_locked_commits_on_the_way_down(self):
        m = self.machine()
        m.key_down(0.0)
        m.key_up(0.05)
        m.key_down(0.10)
        m.key_up(0.15)                       # locked
        self.assertEqual(m.key_down(1.0), "commit")
        self.assertFalse(m.locked)
        self.assertIsNone(m.key_up(1.05), "must not fire twice for one press")

    def test_autorepeat_is_ignored(self):
        m = self.machine()
        self.assertEqual(m.key_down(0.0), "start")
        self.assertIsNone(m.key_down(0.01), "held key must not restart")


if __name__ == "__main__":
    unittest.main()
