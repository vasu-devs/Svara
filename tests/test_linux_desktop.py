"""Linux/Wayland desktop seams: the Hyprland hotkey transport and the uinput
typist. Headless — hyprctl and the virtual keyboard are mocked; the FIFO is a
real one in a temp dir.

Run:  .venv/bin/python -m unittest tests.test_linux_desktop -v
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import hotkey_hyprland as hh  # noqa: E402
from mywhisper import injector_wayland as iw  # noqa: E402

REC_CFG = {"hotkey": "right alt", "mode": "hold_to_record", "long_press_ms": 60,
           "double_tap_ms": 300, "double_tap_lock": True}


class TestCombos(unittest.TestCase):
    def test_lone_modifier_binds_with_and_without_its_mask(self):
        self.assertEqual(hh.combos("right alt"), ["Alt_R", "ALT + Alt_R"])

    def test_several_keys_share_the_gestures(self):
        self.assertEqual(hh.combos("right alt, super + shift + f23"),
                         ["Alt_R", "ALT + Alt_R", "SUPER + SHIFT + F23"])

    def test_combo_and_plain_key(self):
        self.assertEqual(hh.combos("ctrl+shift+space"), ["CTRL + SHIFT + space"])
        self.assertEqual(hh.combos("F8"), ["F8"])
        self.assertEqual(hh.combos("num 0"), ["KP_0"])

    def test_unknown_key_is_refused_up_front(self):
        with self.assertRaises(ValueError):
            hh.combos("hyperkey")


@unittest.skipIf(os.name == "nt", "FIFOs")
class TestFifoListener(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lua_calls: list[str] = []
        self.events: list[str] = []
        self.lua = lambda code: self.lua_calls.append(code) or True
        self.listener = hh.HyprlandKeyListener(
            REC_CFG, lambda: self.events.append("start"),
            lambda: self.events.append("commit"),
            lambda: self.events.append("cancel"),
            lambda: self.events.append("lock"),
            is_recording=lambda: "start" in self.events, lua=self.lua)
        self.listener.fifo = Path(self.tmp.name) / "hotkey.fifo"
        self.listener.start()

    def tearDown(self):
        self.listener.stop()
        self.tmp.cleanup()

    def send(self, tok: str):
        with open(self.listener.fifo, "w") as f:
            f.write(tok + "\n")

    def test_binds_press_and_release_for_every_combo_then_unbinds(self):
        binds = [c for c in self.lua_calls if c.startswith("hl.bind(")]
        self.assertEqual(len(binds), 4)  # 2 combos × (press, release)
        self.assertEqual(sum("release = true" in c for c in binds), 2)
        self.assertIn("echo down >", binds[0])
        self.assertIn(str(self.listener.fifo), binds[0])
        self.listener.stop()
        self.assertEqual(self.lua_calls[-2:],
                         ["hl.unbind([[Alt_R]])", "hl.unbind([[ALT + Alt_R]])"])

    def test_hold_then_release_commits_and_duplicates_are_ignored(self):
        self.send("down")
        self.send("down")  # the second mask variant firing too
        time.sleep(0.1)
        self.assertFalse(iw.hotkey_up.is_set())
        self.send("up")
        self.send("up")
        time.sleep(0.1)
        self.assertEqual(self.events, ["start", "commit"])
        self.assertTrue(iw.hotkey_up.is_set())

    def test_quick_tap_cancels(self):
        self.send("down")
        self.send("up")
        time.sleep(0.1)
        self.assertEqual(self.events, ["start", "cancel"])

    def test_binds_are_re_armed_when_hyprland_forgot_them(self):
        n = len(self.lua_calls)
        self.assertFalse(self.listener.ensure_bound('[{"key": "Alt_R"}]'))
        self.assertEqual(len(self.lua_calls), n)
        self.assertTrue(self.listener.ensure_bound("[]"))
        self.assertTrue(any("hl.bind([[Alt_R]]" in c for c in self.lua_calls[n:]))


@unittest.skipIf(os.name == "nt", "FIFOs")
class TestToggleDoubleTap(TestFifoListener):
    def setUp(self):
        global REC_CFG
        saved = REC_CFG
        REC_CFG = dict(REC_CFG, mode="press_to_toggle", toggle_taps=2)
        try:
            super().setUp()
        finally:
            REC_CFG = saved

    def test_a_lone_tap_does_nothing_a_double_tap_starts_one_tap_stops(self):
        self.send("down"); self.send("up")
        time.sleep(0.4)                      # past double_tap_ms: forgotten
        self.assertEqual(self.events, [])
        self.send("down"); self.send("up")
        self.send("down"); self.send("up")
        time.sleep(0.1)
        self.assertEqual(self.events, ["start"])
        self.send("down"); self.send("up")
        time.sleep(0.1)
        self.assertEqual(self.events, ["start", "commit"])

    def test_hold_then_release_commits_and_duplicates_are_ignored(self):
        pass   # hold semantics belong to the parent fixture's mode

    def test_quick_tap_cancels(self):
        pass


@unittest.skipUnless(importlib.util.find_spec("evdev"), "python-evdev (Linux only)")
class TestKeycodes(unittest.TestCase):
    def test_every_printable_ascii_has_a_keycode(self):
        from evdev import ecodes
        for n in range(32, 127):
            name, _shift = iw.keycode(chr(n))
            self.assertTrue(hasattr(ecodes, name), chr(n))
        self.assertEqual(iw.keycode("A"), ("KEY_A", True))
        self.assertEqual(iw.keycode("?"), ("KEY_SLASH", True))
        self.assertEqual(iw.keycode("\n"), ("KEY_ENTER", False))
        self.assertIsNone(iw.keycode("é"))

    def test_non_ascii_text_goes_through_the_clipboard(self):
        with mock.patch.object(iw, "paste_text") as paste, \
                mock.patch.object(iw, "_keyboard") as kb:
            iw.type_text("café")
        paste.assert_called_once_with("café")
        kb.assert_not_called()

    def test_ascii_text_is_typed_key_by_key(self):
        ui = mock.Mock()
        with mock.patch.object(iw, "_keyboard", return_value=ui):
            iw.type_text("Hi!")
        self.assertEqual(ui.syn.call_count, 3)
        # "H" and "!" need shift: 2 shift-down + 2 shift-up + 3×2 key events
        self.assertEqual(ui.write.call_count, 10)


class TestIslandFeed(unittest.TestCase):
    """The Quickshell island reads one JSON file; these pin its contract."""

    def setUp(self):
        import tempfile
        from mywhisper.overlay import _IslandFeed
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "svara-island.json")
        self.level = 0.0
        self.feed = _IslandFeed(self.path, lambda: self.level)

    def tearDown(self):
        self.feed.hide()
        self.dir.cleanup()

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_starts_hidden_and_streams_the_mic_level_while_listening(self):
        self.assertEqual(self.read()["state"], "hidden")
        self.level = 2.0                       # clamped to 1
        self.feed.show("listening")
        time.sleep(0.2)
        d = self.read()
        self.assertEqual((d["state"], d["level"]), ("listening", 1.0))

    def test_lock_keeps_the_words_and_done_lets_go_after_the_linger(self):
        self.feed.show("listening")
        self.feed.set(text="hello there")
        self.feed.show("locked")
        self.assertEqual(self.read(), {"state": "locked", "text": "hello there", "level": 0.0, "bands": []})
        self.feed.working()
        self.assertEqual(self.read()["text"], "hello there")
        self.feed.done("Hello there.", linger_s=0.05)
        self.assertEqual(self.read()["state"], "done")
        time.sleep(0.2)
        self.assertEqual(self.read(), {"state": "hidden", "text": "", "level": 0.0, "bands": []})

    def test_a_new_dictation_cancels_the_pending_hide(self):
        self.feed.done("first", linger_s=0.05)
        self.feed.show("listening")
        time.sleep(0.2)
        self.assertEqual(self.read()["state"], "listening")


if __name__ == "__main__":
    unittest.main()
