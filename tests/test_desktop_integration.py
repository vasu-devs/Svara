"""Svara has to behave like an installed app, not a loose exe.

Three things a user reasonably expects after downloading it, none of which
happen for free with a single portable binary:

- typing "Svara" into Windows Search finds it,
- clicking that result opens something,
- and the icon is the same mark everywhere - browser tab, Search result,
  taskbar - rather than a different logo per surface.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_desktop_integration -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import shortcuts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(os.name == "nt", "Windows shell integration")
class TestStartMenuEntry(unittest.TestCase):
    """Without a Start Menu shortcut, Windows Search cannot see the app at all:
    a loose .exe in Downloads is not indexed as an application."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-shortcut-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.programs = self.tmp / "Programs"
        self.programs.mkdir()
        self.exe = self.tmp / "Svara.exe"
        self.exe.write_bytes(b"stub")

    def _run(self, exe=None):
        with mock.patch.object(shortcuts, "_start_menu_dir",
                               return_value=self.programs), \
             mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", str(exe or self.exe)):
            shortcuts.ensure_start_menu_shortcut()

    def _target_of(self, lnk):
        import comtypes.client
        shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
        return str(shell.CreateShortcut(str(lnk)).TargetPath)

    def test_a_shortcut_is_created(self):
        self._run()
        lnk = self.programs / "Svara.lnk"
        self.assertTrue(lnk.is_file(), "Windows Search would never find Svara")
        self.assertEqual(Path(self._target_of(lnk)).resolve(), self.exe.resolve())

    def test_it_is_named_so_search_finds_it(self):
        # Search matches on the shortcut's file name.
        self._run()
        self.assertTrue((self.programs / "Svara.lnk").is_file())

    def test_a_stale_shortcut_is_retargeted(self):
        # The install moved, or the shortcut pointed at a since-deleted
        # Downloads copy. A dead Search result is worse than none.
        self._run(exe=self.tmp / "old" / "Svara.exe")
        moved = self.tmp / "Svara.exe"
        self._run(exe=moved)
        self.assertEqual(
            Path(self._target_of(self.programs / "Svara.lnk")).resolve(),
            moved.resolve())

    def test_nothing_happens_when_running_from_source(self):
        # A dev checkout must not scatter shortcuts into the real Start Menu.
        with mock.patch.object(shortcuts, "_start_menu_dir",
                               return_value=self.programs), \
             mock.patch.object(sys, "frozen", False, create=True):
            shortcuts.ensure_start_menu_shortcut()
        self.assertFalse((self.programs / "Svara.lnk").exists())

    def test_a_failure_is_never_fatal(self):
        # Shell integration is cosmetic; it must not stop the app starting.
        with mock.patch.object(shortcuts, "_start_menu_dir",
                               return_value=self.programs), \
             mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch("comtypes.client.CreateObject",
                        side_effect=OSError("COM unavailable")):
            shortcuts.ensure_start_menu_shortcut()   # must not raise


class TestOneMarkEverywhere(unittest.TestCase):
    """The icon in a browser tab, in Windows Search and on the taskbar should
    be the same mark. They were two different logos: the app carried warm
    sienna strings on a dark tile, the website a neon pink/cyan/violet
    waveform left over from an earlier identity."""

    APP_PALETTE = ("c1573a", "e08a5e", "e8a33d", "d0693f", "f0a878")
    RETIRED = ("22d3ee", "8b5cf6", "ff5fa2", "7ee7f5", "b39bf7", "ff8fc4")

    def favicon(self) -> str:
        path = ROOT / "web" / "public" / "favicon.svg"
        self.assertTrue(path.is_file(), "the site has no favicon")
        return path.read_text(encoding="utf-8").lower()

    def test_the_favicon_uses_the_app_palette(self):
        svg = self.favicon()
        used = [c for c in self.APP_PALETTE if c in svg]
        self.assertTrue(used, "favicon shares no colour with the app icon")

    def test_the_retired_neon_palette_is_gone(self):
        svg = self.favicon()
        leftovers = [c for c in self.RETIRED if c in svg]
        self.assertFalse(
            leftovers,
            f"favicon still uses the old identity: {leftovers}. The app, the "
            "setup window and the site are warm sienna; one product, one mark.")

    def test_the_app_icon_ships(self):
        # The exe embeds this, and the Start Menu shortcut inherits it via
        # IconLocation, so a missing file means a generic Windows icon in
        # Search results.
        for name in ("icon.ico", "icon.png"):
            self.assertTrue((ROOT / "assets" / name).is_file(),
                            f"assets/{name} is missing")

    def test_the_build_embeds_the_icon(self):
        spec = (ROOT / "MyWhisper.spec").read_text(encoding="utf-8")
        self.assertIn("icon.ico", spec, "the exe would ship iconless")
        self.assertIn("icon=_icon", spec, "EXE() never receives the icon")

    def test_the_site_references_the_favicon(self):
        layout = (ROOT / "web" / "app" / "layout.tsx").read_text(encoding="utf-8")
        self.assertIn("favicon.svg", layout,
                      "the site declares no icon, so browsers show a blank tab")


if __name__ == "__main__":
    unittest.main()


class TestStartsAfterAPowerOff(unittest.TestCase):
    """"It should work even after restart" is the whole point of a dictation
    key. These lock the default ON: a user who never opens Settings still gets
    Svara back after a reboot, and only an explicit opt-out stops it.

    set_autostart is mocked throughout - the real one writes HKCU\\Run, and a
    test suite has no business touching the machine's real startup entries."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-autostart-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.state = self.tmp / "state.json"

    def _ensure(self, installed=True):
        from mywhisper import install
        with mock.patch.object(install, "is_installed_copy", return_value=installed), \
             mock.patch("mywhisper.paths.state_path", return_value=self.state), \
             mock.patch.object(install, "set_autostart") as spy:
            install.ensure_autostart()
        return spy

    def test_it_is_on_by_default(self):
        # No state file at all: a fresh install, user has chosen nothing.
        spy = self._ensure()
        spy.assert_called_once_with(True)

    def test_a_state_file_without_the_key_still_means_on(self):
        self.state.write_text('{"model": "base.en"}', encoding="utf-8")
        self._ensure().assert_called_once_with(True)

    def test_an_explicit_opt_out_is_obeyed(self):
        self.state.write_text('{"autostart": false}', encoding="utf-8")
        self._ensure().assert_called_once_with(False)

    def test_it_reregisters_every_launch_to_heal_a_deleted_key(self):
        # Cleaners, "startup app" toggles in Task Manager and reinstalls all
        # drop the Run key. Rewriting it each launch is what makes it stick.
        self.state.write_text('{"autostart": true}', encoding="utf-8")
        for _ in range(3):
            self._ensure().assert_called_once_with(True)

    def test_a_corrupt_state_file_does_not_disable_it(self):
        # Falling back to OFF here would silently break startup for anyone
        # whose state.json got truncated by a bad shutdown.
        self.state.write_text("{not json", encoding="utf-8")
        self._ensure().assert_called_once_with(True)

    def test_a_dev_checkout_never_registers(self):
        self._ensure(installed=False).assert_not_called()
