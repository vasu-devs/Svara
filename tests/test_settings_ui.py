"""The settings window: every control drives a real setter.

A settings screen that looks right and changes nothing is worse than no
settings screen, so these tests build each section for real and then drive the
widgets, asserting the app's live setters were called. They also cover the two
ways the old window misled people: a switch whose displayed state disagreed
with reality, and a privacy toggle that could be enabled without its
prerequisite.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_settings_ui -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import tkinter as tk

    _root = tk.Tk()
    _root.withdraw()
    HAVE_TK = True
except Exception:  # noqa: BLE001
    _root = None
    HAVE_TK = False

from mywhisper import config as config_mod  # noqa: E402


def make_app():
    cfg = config_mod.load(None)
    app = mock.MagicMock()
    app.cfg = cfg
    app.current_theme = "minimal-dark"
    app.model_label = "base.en on cpu (int8)"
    app.is_multilingual = True
    app.gpu_available = True
    app.autostart_enabled = False
    app.whisper_mode = False
    app.current_language = "en"
    app.english_variant = "en-US"
    app.romanize_mode = "never"
    app.cleanup.level = "light"
    app.transcriber.device_used = "cpu"
    app.auto_learner.enabled = False
    return app


def widgets(root):
    out = []

    def walk(w):
        out.append(w)
        for child in w.winfo_children():
            walk(child)

    walk(root)
    return out


@unittest.skipUnless(HAVE_TK, "no display available")
class TestSectionsBuild(unittest.TestCase):
    def test_every_section_builds(self):
        from mywhisper.settings_ui import SECTIONS

        for name, builder in SECTIONS:
            app = make_app()
            frame = tk.Frame(_root)
            try:
                built = builder(frame, app)
                self.assertIsNotNone(built, name)
            finally:
                frame.destroy()

    def test_nothing_overflows_its_column(self):
        # The old window clipped descriptions under the controls. Every
        # description wraps inside the column the grid actually gives it.
        from mywhisper.settings_ui import Section

        frame = tk.Frame(_root)
        self.addCleanup(frame.destroy)
        section = Section(frame, "Test", "A blurb")
        section.row("Label", "A description long enough that it must wrap "
                             "rather than run under the control beside it.")
        frame.update_idletasks()
        labels = [w for w in widgets(section.frame) if isinstance(w, tk.Label)]
        # cget returns a Tcl object, not an int.
        lengths = [int(str(w.cget("wraplength")) or 0) for w in labels]
        wrapped = [n for n in lengths if n > 0]
        self.assertTrue(wrapped, "descriptions must declare a wraplength")
        for n in wrapped:
            self.assertLessEqual(n, 520)


@unittest.skipUnless(HAVE_TK, "no display available")
class TestControlsDriveTheApp(unittest.TestCase):
    """Build a section, drive its widgets, assert the setter fired."""

    def _build(self, builder):
        app = make_app()
        frame = tk.Frame(_root)
        self.addCleanup(frame.destroy)
        builder(frame, app)
        frame.update_idletasks()
        return app, frame

    def _pick(self, frame, label_text):
        """Set a combobox to a given option and fire its handler."""
        from tkinter import ttk
        for w in widgets(frame):
            if isinstance(w, ttk.Combobox) and label_text in w.cget("values"):
                w.set(label_text)
                w.event_generate("<<ComboboxSelected>>")
                return True
        return False

    def test_model_picker_calls_set_model(self):
        from mywhisper.settings_ui import _speech
        app, frame = self._build(_speech)
        from mywhisper.setup_ui import MODELS
        label = MODELS[0][1]
        self.assertTrue(self._pick(frame, label), "model combo not found")
        app.set_model.assert_called_once_with(MODELS[0][0])

    def test_device_picker_calls_set_device(self):
        from mywhisper.settings_ui import _speech
        app, frame = self._build(_speech)
        self.assertTrue(self._pick(frame, "GPU (NVIDIA)"))
        app.set_device.assert_called_once_with("cuda")

    def test_streaming_picker_calls_set_streaming_mode(self):
        from mywhisper.settings_ui import _speech
        app, frame = self._build(_speech)
        self.assertTrue(self._pick(frame, "Type everything at the end"))
        app.set_streaming_mode.assert_called_once_with("off")

    def test_english_variant_calls_its_setter(self):
        from mywhisper.settings_ui import _writing
        app, frame = self._build(_writing)
        self.assertTrue(self._pick(frame, "British — colour, organise"))
        app.set_english_variant.assert_called_once_with("en-GB")

    def test_cleanup_level_calls_its_setter(self):
        from mywhisper.settings_ui import _writing
        app, frame = self._build(_writing)
        self.assertTrue(self._pick(frame, "High — rewrite with your local AI"))
        app.set_cleanup_level.assert_called_once_with("high")

    def test_hotkey_picker_rebinds(self):
        from mywhisper.settings_ui import _shortcuts
        app, frame = self._build(_shortcuts)
        self.assertTrue(self._pick(frame, "f8"))
        app.set_hotkey.assert_called_once_with("f8")

    def test_add_word_calls_the_dictionary(self):
        from mywhisper.settings_ui import _words
        app, frame = self._build(_words)
        entry = next(w for w in widgets(frame) if isinstance(w, tk.Entry))
        entry.insert(0, "Kubernetes")
        add = next(w for w in widgets(frame)
                   if isinstance(w, tk.Button) and w.cget("text") == "Add")
        add.invoke()
        app.add_dictionary_word.assert_called_once_with("Kubernetes")
        self.assertEqual(entry.get(), "", "the field should clear after adding")

    def test_add_word_ignores_an_empty_field(self):
        from mywhisper.settings_ui import _words
        app, frame = self._build(_words)
        add = next(w for w in widgets(frame)
                   if isinstance(w, tk.Button) and w.cget("text") == "Add")
        add.invoke()
        app.add_dictionary_word.assert_not_called()


@unittest.skipUnless(HAVE_TK, "no display available")
class TestPrivacyGates(unittest.TestCase):
    def test_learning_cannot_be_enabled_without_caret_reading(self):
        # It is built on reading text Svara did not produce, so it must not be
        # switchable on by itself.
        from mywhisper.settings_ui import _set_learn
        app = make_app()
        app.cfg["context"]["read_caret_text"] = False
        _set_learn(app, True)
        self.assertFalse(app.cfg["dictionary"]["auto_learn"])
        app._notify.assert_called_once()

    def test_learning_enables_once_caret_reading_is_on(self):
        from mywhisper.settings_ui import _set_learn
        app = make_app()
        app.cfg["context"]["read_caret_text"] = True
        _set_learn(app, True)
        self.assertTrue(app.cfg["dictionary"]["auto_learn"])
        self.assertTrue(app.auto_learner.enabled)

    def test_turning_caret_reading_off_also_turns_learning_off(self):
        # Otherwise learning would keep running on a permission the user just
        # withdrew.
        from mywhisper.settings_ui import _set_caret
        app = make_app()
        app.cfg["context"]["read_caret_text"] = True
        app.cfg["dictionary"]["auto_learn"] = True
        app.auto_learner.enabled = True
        _set_caret(app, False)
        self.assertFalse(app.cfg["context"]["read_caret_text"])
        self.assertFalse(app.auto_learner.enabled)
        self.assertFalse(app.cfg["dictionary"]["auto_learn"])

    def test_transcript_logging_round_trips(self):
        from mywhisper import redact
        from mywhisper.settings_ui import _set_transcripts, _transcripts_on
        app = make_app()
        try:
            _set_transcripts(app, True)
            self.assertTrue(_transcripts_on())
            _set_transcripts(app, False)
            self.assertFalse(_transcripts_on())
        finally:
            redact.configure({"debug_transcripts": False})


@unittest.skipUnless(HAVE_TK, "no display available")
class TestSwitchNeverDisagreesWithTheApp(unittest.TestCase):
    """The bug that started this: the Startup box showed ticked while autostart
    was in fact broken, so clicking it did the opposite of what the user
    wanted. `_switch` re-reads the app after every click, so the widget can
    never hold a state the app does not."""

    def test_switch_reflects_the_app_not_the_click(self):
        from mywhisper.settings_ui import _switch
        frame = tk.Frame(_root)
        self.addCleanup(frame.destroy)

        state = {"on": False}
        # A setter that refuses to change - the widget must snap back.
        var = _switch(frame, "Stubborn", lambda: state["on"], lambda _v: None)
        button = next(w for w in widgets(frame) if isinstance(w, tk.Checkbutton))
        button.invoke()
        self.assertFalse(var.get(), "widget kept a state the app rejected")

    def test_switch_follows_a_setter_that_works(self):
        from mywhisper.settings_ui import _switch
        frame = tk.Frame(_root)
        self.addCleanup(frame.destroy)

        state = {"on": False}

        def toggle(_v):
            state["on"] = not state["on"]

        var = _switch(frame, "Works", lambda: state["on"], toggle)
        button = next(w for w in widgets(frame) if isinstance(w, tk.Checkbutton))
        button.invoke()
        self.assertTrue(var.get())


if __name__ == "__main__":
    unittest.main()
