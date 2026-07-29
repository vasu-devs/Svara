"""Every window Svara can open, actually opened.

Unit tests cover the logic behind these windows and none of the windows
themselves, which is the wrong way round for Tk: a typo in a widget option, a
name referenced before assignment, a `ttk` style applied to a missing theme —
none of it fails at import, all of it fails the first time a user picks the menu
item. This suite builds each window against a real (hidden) root and asserts it
constructs and populates.

It skips itself where there is no display, so headless CI stays green.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_ui_smoke -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import tkinter as tk

    _root = tk.Tk()
    _root.withdraw()
    HAVE_TK = True
except Exception:  # noqa: BLE001 — no display, no tkinter, no problem
    _root = None
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "no display available")
class _WindowCase(unittest.TestCase):
    """Gives each test a hidden root and a stand-in app object."""

    @classmethod
    def setUpClass(cls):
        cls.root = _root

    def setUp(self):
        from mywhisper import config as config_mod
        from mywhisper.history import History
        from mywhisper.scratchpad import Scratchpad

        self.tmp = Path(tempfile.mkdtemp(prefix="svara-ui-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch("mywhisper.paths.base_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.cfg = config_mod.load(None)
        self.app = mock.MagicMock()
        self.app.cfg = self.cfg
        self.app.current_theme = "minimal-dark"
        self.app.history = History(self.cfg["history"])
        self.addCleanup(self.app.history.close)
        self.app.scratchpad = Scratchpad()
        self.addCleanup(self.app.scratchpad.close)

    def _children(self, widget) -> list:
        out = [widget]
        for child in widget.winfo_children():
            out.extend(self._children(child))
        return out

    def _last_toplevel(self, attr: str):
        win = getattr(self.root, attr, None)
        self.assertIsNotNone(win, f"{attr} was never created")
        self.addCleanup(lambda: win.winfo_exists() and win.destroy())
        return win


class TestDiffWindow(_WindowCase):
    def test_builds_and_renders_both_sides_of_the_diff(self):
        from mywhisper.howto_ui import _build_diff

        decision = {}
        _build_diff(self.root, self.app,
                    before="the quick brown fox jumps",
                    after="the slow brown fox leaps over",
                    label="Concise", decision=decision)
        win = self._last_toplevel("_svara_diff")
        self.root.update_idletasks()

        texts = [w for w in self._children(win) if isinstance(w, tk.Text)]
        self.assertTrue(texts, "diff window has no text area")
        body = texts[0].get("1.0", "end-1c")
        self.assertIn("quick", body, "deleted words must still be visible")
        self.assertIn("slow", body, "added words must be visible")
        self.assertIn("insert", texts[0].tag_names())
        self.assertIn("delete", texts[0].tag_names())

    def test_closing_the_window_rejects_and_releases_the_waiter(self):
        import threading

        from mywhisper.howto_ui import _build_diff

        decision, done = {}, threading.Event()
        _build_diff(self.root, self.app, before="a b", after="a c",
                    decision=decision, done=done)
        win = self._last_toplevel("_svara_diff")
        # protocol() returns the registered Tcl command NAME, not a callable —
        # invoking it through the interpreter is what the X button does.
        win.tk.call(win.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(done.is_set(), "a blocked transform thread would hang")
        self.assertFalse(decision["accept"], "closing must never mean 'apply'")

    def test_review_mode_relabels_the_buttons(self):
        from mywhisper.howto_ui import _build_diff

        _build_diff(self.root, self.app, before="a b", after="a c",
                    mode="review", decision={})
        win = self._last_toplevel("_svara_diff")
        labels = {w.cget("text") for w in self._children(win)
                  if isinstance(w, tk.Button)}
        self.assertIn("Close", labels)
        self.assertIn("Copy original", labels)

    def test_colors_come_from_the_active_theme(self):
        from mywhisper.howto_ui import _diff_colors
        from mywhisper.themes import theme_names

        for name in theme_names():
            self.app.current_theme = name
            add, delete = _diff_colors(self.app)
            self.assertRegex(add, r"^#[0-9a-fA-F]{6}$", name)
            self.assertRegex(delete, r"^#[0-9a-fA-F]{6}$", name)
            self.assertNotEqual(add, delete,
                                f"{name}: additions and deletions look alike")


class TestDictionaryWindow(_WindowCase):
    def test_builds_with_an_empty_dictionary(self):
        from mywhisper.howto_ui import _build_dictionary

        _build_dictionary(self.root, self.app)
        win = self._last_toplevel("_svara_dict")
        self.root.update_idletasks()
        boxes = [w for w in self._children(win) if isinstance(w, tk.Listbox)]
        self.assertEqual(len(boxes), 3, "words / replacements / snippets tabs")

    def test_populates_from_an_existing_dictionary(self):
        from mywhisper.dictionary_io import save_dictionary
        from mywhisper.howto_ui import _build_dictionary

        save_dictionary({"words": ["Svara", "CTranslate2"],
                         "replacements": {"swara": "Svara"},
                         "snippets": {"my email": "you@example.com"}})
        _build_dictionary(self.root, self.app)
        win = self._last_toplevel("_svara_dict")
        self.root.update_idletasks()
        boxes = [w for w in self._children(win) if isinstance(w, tk.Listbox)]
        rows = [boxes[i].get(0, "end") for i in range(3)]
        self.assertIn("Svara", rows[0])
        self.assertTrue(any("swara" in r for r in rows[1]))
        self.assertTrue(any("my email" in r for r in rows[2]))

    def test_rebuilding_does_not_leak_a_second_window(self):
        from mywhisper.howto_ui import _build_dictionary

        _build_dictionary(self.root, self.app)
        first = self.root._svara_dict
        _build_dictionary(self.root, self.app)
        self.addCleanup(lambda: self.root._svara_dict.winfo_exists()
                        and self.root._svara_dict.destroy())
        self.assertFalse(first.winfo_exists(), "the old window must be destroyed")


class TestScratchpadWindow(_WindowCase):
    def test_builds_and_creates_a_first_note(self):
        from mywhisper.howto_ui import _toggle_scratchpad

        _toggle_scratchpad(self.root, self.app)
        win = self._last_toplevel("_svara_scratch")
        self.root.update_idletasks()
        self.assertTrue(self.app.scratchpad.notes(), "no note was created")
        self.assertTrue([w for w in self._children(win)
                         if isinstance(w, tk.Text)])

    def test_reopens_existing_notes_as_tabs(self):
        from mywhisper.howto_ui import _toggle_scratchpad

        for title in ("Alpha", "Beta"):
            note_id = self.app.scratchpad.create(title)
            self.app.scratchpad.save(note_id, f"body of {title}")
        _toggle_scratchpad(self.root, self.app)
        win = self._last_toplevel("_svara_scratch")
        self.root.update_idletasks()
        bodies = [w.get("1.0", "end-1c") for w in self._children(win)
                  if isinstance(w, tk.Text)]
        self.assertIn("body of Alpha", bodies)
        self.assertIn("body of Beta", bodies)

    def test_second_call_toggles_it_hidden(self):
        from mywhisper.howto_ui import _toggle_scratchpad

        _toggle_scratchpad(self.root, self.app)
        win = self._last_toplevel("_svara_scratch")
        _toggle_scratchpad(self.root, self.app)
        self.assertEqual(win.state(), "withdrawn")


class TestHistoryWindow(_WindowCase):
    def test_builds_and_lists_entries(self):
        from mywhisper.howto_ui import _build_history

        self.app.history.record("hello from the past", app="notepad.exe")
        _build_history(self.root, self.app)
        win = self._last_toplevel("_svara_history")
        self.root.update_idletasks()
        boxes = [w for w in self._children(win) if isinstance(w, tk.Listbox)]
        self.assertTrue(any("hello from the past" in row
                            for row in boxes[0].get(0, "end")))


@unittest.skipUnless(HAVE_TK, "no display available")
class TestTrayMenu(unittest.TestCase):
    """The tray menu is built once at startup from ~25 lambdas over app state.
    A typo in any of them is a crash on launch, not a caught exception."""

    def test_menu_builds_and_every_item_resolves(self):
        try:
            import pystray  # noqa: F401
        except ImportError:
            self.skipTest("pystray not installed")
        from mywhisper import config as config_mod
        from mywhisper.tray import Tray

        cfg = config_mod.load(None)
        app = mock.MagicMock()
        app.cfg = cfg
        app.gpu_available = False
        app.is_multilingual = True
        app.english_variant = "en-US"
        app.romanize_mode = "never"
        app.current_theme = "minimal-dark"
        app.cleanup.level = "light"
        app.learn_queue.pending.return_value = []
        app.updater.staged = None

        tray = Tray(app)
        self.assertIsNotNone(tray.icon, "tray icon was not created")

        # Walk the whole menu: text callables, checked callables and visible
        # callables all execute here, which is where a bad attribute shows up.
        def walk(menu, depth=0):
            self.assertLess(depth, 5, "menu nested implausibly deep")
            count = 0
            for item in menu:
                str(item.text)
                if item.checked is not None:
                    bool(item.checked)
                bool(item.visible)
                if item.submenu is not None:
                    count += walk(item.submenu, depth + 1)
                count += 1
            return count

        self.assertGreater(walk(tray.icon.menu), 40)

    def test_writing_menu_reflects_app_state(self):
        try:
            import pystray  # noqa: F401
        except ImportError:
            self.skipTest("pystray not installed")
        from mywhisper import config as config_mod
        from mywhisper.tray import Tray

        cfg = config_mod.load(None)
        app = mock.MagicMock()
        app.cfg = cfg
        app.gpu_available = False
        app.is_multilingual = True
        app.english_variant = "en-GB"
        app.romanize_mode = "auto"
        app.current_theme = "minimal-dark"
        app.cleanup.level = "light"
        app.learn_queue.pending.return_value = []
        app.updater.staged = None

        tray = Tray(app)
        found = {}

        def walk(menu):
            for item in menu:
                if item.submenu is not None:
                    walk(item.submenu)
                elif item.checked:
                    found[str(item.text)] = True

        walk(tray.icon.menu)
        self.assertTrue(any("British" in k for k in found),
                        f"en-GB not reflected in the menu: {list(found)}")
        self.assertTrue(any("chat" in k.lower() for k in found),
                        f"romanize=auto not reflected: {list(found)}")


if __name__ == "__main__":
    unittest.main()
