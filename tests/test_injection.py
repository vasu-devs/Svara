"""Injection strategy selection and the terminal-safety rules.

The tests that matter most here are the ones asserting Svara can never submit
something the user didn't submit. A dictated paragraph containing "and then run
the build" must not execute at a shell prompt.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_injection -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.injection import TextInjector, classify, is_terminal_app  # noqa: E402
from mywhisper.injection.resolver import build  # noqa: E402
from mywhisper.injection.strategies import TerminalStrategy  # noqa: E402
from mywhisper.pipeline import UtteranceContext  # noqa: E402

BASE = {"method": "type", "append_space": True, "restore_clipboard": True,
        "targets": {}, "terminal_newline": "space", "terminal_paste": True,
        "warn_on_elevated": True}


class TestClassification(unittest.TestCase):
    def test_ordinary_app_uses_the_configured_method(self):
        self.assertEqual(classify("notepad.exe", BASE), "type")
        self.assertEqual(classify("notepad.exe", {**BASE, "method": "paste"}),
                         "paste")

    def test_terminals_are_detected(self):
        for app in ("windowsterminal.exe", "wt.exe", "cmd.exe",
                    "powershell.exe", "alacritty.exe"):
            self.assertEqual(classify(app, BASE), "terminal", app)
            self.assertTrue(is_terminal_app(app, BASE), app)

    def test_editors_get_shift_insert_not_terminal(self):
        # Cursor's editor panes are ordinary text and want ordinary typography;
        # only its Ctrl+V is claimed.
        self.assertEqual(classify("cursor.exe", BASE), "shift_insert")
        self.assertFalse(is_terminal_app("cursor.exe", BASE))

    def test_explicit_target_overrides_the_builtin_list(self):
        cfg = {**BASE, "targets": {"windowsterminal.exe": "type"}}
        self.assertEqual(classify("windowsterminal.exe", cfg), "type")

    def test_unknown_strategy_in_targets_is_ignored_not_fatal(self):
        cfg = {**BASE, "targets": {"notepad.exe": "telepathy"}}
        self.assertEqual(classify("notepad.exe", cfg), "type")

    def test_no_focused_app_falls_back_to_the_default(self):
        self.assertEqual(classify("", BASE), "type")

    def test_case_insensitive(self):
        self.assertEqual(classify("WindowsTerminal.EXE", BASE), "terminal")


class TestTerminalSafety(unittest.TestCase):
    """Every assertion here is 'Svara did not press Enter for you'."""

    def setUp(self):
        self.ctx = UtteranceContext(app="cmd.exe", is_terminal=True)

    def test_newlines_become_spaces_by_default(self):
        strategy = TerminalStrategy(newline="space")
        out = strategy.prepare("git status\nthen run the build", self.ctx)
        self.assertNotIn("\n", out)
        self.assertEqual(out, "git status then run the build")

    def test_trailing_newline_is_always_stripped(self):
        for policy in ("space", "shift_enter", "literal"):
            out = TerminalStrategy(newline=policy).prepare("echo hi\n", self.ctx)
            self.assertFalse(out.endswith("\n"), policy)

    def test_literal_mode_keeps_interior_newlines(self):
        out = TerminalStrategy(newline="literal").prepare("a\nb", self.ctx)
        self.assertEqual(out, "a\nb")

    def test_trailing_whitespace_before_newline_is_removed(self):
        out = TerminalStrategy(newline="literal").prepare("a   \nb", self.ctx)
        self.assertEqual(out, "a\nb")

    def test_carriage_returns_are_normalised(self):
        out = TerminalStrategy(newline="space").prepare("a\r\nb", self.ctx)
        self.assertEqual(out, "a b")

    def test_risky_looking_text_warns(self):
        seen = []
        strategy = TerminalStrategy(newline="space", warn=seen.append)
        with mock.patch("mywhisper.injection.strategies.paste_text_shift_insert"), \
                mock.patch("mywhisper.injection.strategies.wait_modifiers_released"):
            strategy.inject("rm -rf the old build directory", self.ctx)
        self.assertTrue(seen)
        self.assertIn("did not run it", seen[0])

    def test_ordinary_prose_does_not_warn(self):
        seen = []
        strategy = TerminalStrategy(newline="space", warn=seen.append)
        with mock.patch("mywhisper.injection.strategies.paste_text_shift_insert"), \
                mock.patch("mywhisper.injection.strategies.wait_modifiers_released"):
            strategy.inject("please summarise this file for me", self.ctx)
        self.assertFalse(seen)


class TestInjectorFacade(unittest.TestCase):
    def test_append_space_off_in_terminals(self):
        # A trailing space at a shell prompt is noise; between two dictations
        # in a document it is what makes them join up.
        injector = TextInjector(dict(BASE))
        sent = []
        with mock.patch.object(injector, "strategy_for") as resolve:
            resolve.return_value = mock.MagicMock(
                inject=lambda t, c: sent.append(t) or len(t))
            injector.inject("hello", UtteranceContext(is_terminal=True))
            injector.inject("hello", UtteranceContext())
        self.assertEqual(sent, ["hello", "hello "])

    def test_streaming_is_refused_for_terminals(self):
        injector = TextInjector(dict(BASE))
        self.assertFalse(injector.streams_into(
            UtteranceContext(is_terminal=True)))
        self.assertEqual(
            injector.inject_stream("hi", UtteranceContext(is_terminal=True)), 0)

    def test_streaming_is_refused_for_elevated_targets(self):
        injector = TextInjector(dict(BASE))
        self.assertFalse(injector.streams_into(
            UtteranceContext(is_elevated=True)))

    def test_streaming_allowed_for_normal_windows(self):
        injector = TextInjector(dict(BASE))
        self.assertTrue(injector.streams_into(UtteranceContext(app="notepad.exe")))

    def test_elevated_target_goes_to_the_clipboard_and_warns_once(self):
        # UIPI discards the keystrokes AND reports success, so without this the
        # dictation vanishes with no error anywhere.
        notes, clips = [], []
        injector = TextInjector(dict(BASE), notify=notes.append)
        ctx = UtteranceContext(app="powershell.exe", is_elevated=True)
        with mock.patch("mywhisper.injector._clipboard_set",
                        side_effect=lambda t: clips.append(t) or True):
            self.assertEqual(injector.inject("sudo make me a sandwich", ctx), 0)
            injector.inject("again", ctx)
        self.assertEqual(len(notes), 1, "should warn once per app, not per word")
        self.assertEqual(len(clips), 2, "every attempt still reaches the clipboard")
        self.assertIn("administrator", notes[0])

    def test_elevation_warning_can_be_disabled(self):
        injector = TextInjector({**BASE, "warn_on_elevated": False})
        sent = []
        with mock.patch.object(injector, "strategy_for") as resolve:
            resolve.return_value = mock.MagicMock(
                inject=lambda t, c: sent.append(t) or len(t))
            injector.inject("x", UtteranceContext(is_elevated=True))
        self.assertEqual(sent, ["x "])

    def test_empty_text_is_a_no_op(self):
        self.assertEqual(TextInjector(dict(BASE)).inject(""), 0)


class TestStrategyBuild(unittest.TestCase):
    def test_each_key_builds_its_strategy(self):
        for key, name in (("type", "type"), ("paste", "paste"),
                          ("shift_insert", "shift_insert"),
                          ("terminal", "terminal")):
            self.assertEqual(build(key, BASE).name, name)

    def test_terminal_strategy_carries_the_newline_policy(self):
        strategy = build("terminal", {**BASE, "terminal_newline": "shift_enter"})
        self.assertEqual(strategy.newline, "shift_enter")


if __name__ == "__main__":
    unittest.main()
