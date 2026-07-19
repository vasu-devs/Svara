"""Unit tests for mywhisper.install — the self-install / autostart layer.

Simulates a frozen exe with a fake sys.executable + a temp LOCALAPPDATA, and
uses a throwaway registry value name so the real Svara registration is never
touched. Run:  .venv\\Scripts\\python.exe -m unittest tests.test_install -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import install  # noqa: E402
from mywhisper import __version__  # noqa: E402

TEST_RUN_NAME = "SvaraInstallSelfTest"  # never the real "Svara" value


class InstallTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-test-"))
        self.downloads = self.tmp / "Downloads"
        self.localappdata = self.tmp / "LocalAppData"
        self.downloads.mkdir()
        self.localappdata.mkdir()
        self.src_exe = self.downloads / "Svara-download.exe"
        self.src_exe.write_bytes(b"fake exe bytes v1")

        self._patches = [
            mock.patch.dict(os.environ,
                            {"LOCALAPPDATA": str(self.localappdata)}),
            mock.patch.object(sys, "executable", str(self.src_exe)),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(install, "APP_NAME", TEST_RUN_NAME),
        ]
        for p in self._patches:
            p.start()
        self.spawned: list[Path] = []
        sp = mock.patch.object(install, "_spawn",
                               side_effect=lambda exe: (self.spawned.append(exe)
                                                        or True))
        sp.start()
        self._patches.append(sp)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        install.set_autostart(False)  # in case a test registered the key
        self._delete_test_run_value()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _delete_test_run_value():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, install.RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, TEST_RUN_NAME)
        except OSError:
            pass

    @staticmethod
    def _read_test_run_value():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, install.RUN_KEY) as k:
                value, _ = winreg.QueryValueEx(k, TEST_RUN_NAME)
            return value
        except OSError:
            return None


class TestPaths(InstallTestBase):
    def test_install_dir_uses_localappdata(self):
        self.assertEqual(install.install_dir(),
                         self.localappdata / TEST_RUN_NAME)

    def test_downloaded_copy_is_not_installed_copy(self):
        self.assertFalse(install.is_installed_copy())

    def test_installed_copy_detected_case_insensitively(self):
        exe = install.installed_exe()
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"x")
        upper = str(exe).upper()
        with mock.patch.object(sys, "executable", upper):
            self.assertTrue(install.is_installed_copy())


class TestEnsureInstalled(InstallTestBase):
    def test_first_run_installs_migrates_and_hands_off(self):
        (self.downloads / "config.yaml").write_text("model: {name: base.en}\n",
                                                    encoding="utf-8")
        (self.downloads / "state.json").write_text('{"theme": "matrix"}',
                                                   encoding="utf-8")
        (self.downloads / ".svara_ready").write_text("stamp", encoding="utf-8")

        handed_off = install.ensure_installed()

        self.assertTrue(handed_off, "must hand off to the installed copy")
        dst = install.installed_exe()
        self.assertEqual(dst.read_bytes(), b"fake exe bytes v1")
        self.assertEqual(self.spawned, [dst])
        # migration
        self.assertEqual((dst.parent / "config.yaml").read_text(encoding="utf-8"),
                         "model: {name: base.en}\n")
        self.assertEqual(json.loads((dst.parent / "state.json")
                                    .read_text(encoding="utf-8"))["theme"],
                         "matrix")
        self.assertEqual((dst.parent / ".svara_ready").read_text(encoding="utf-8"),
                         "stamp")
        # exe stamp survives the copy (setup must not re-run after install)
        self.assertEqual(self.src_exe.stat().st_mtime_ns, dst.stat().st_mtime_ns)
        # manifest
        man = json.loads((dst.parent / install.MANIFEST)
                         .read_text(encoding="utf-8"))
        self.assertEqual(man["version"], __version__)

    def test_cuda_runtime_moves_not_copies(self):
        cuda = self.downloads / "cuda" / "nvidia" / "cublas" / "bin"
        cuda.mkdir(parents=True)
        (cuda / "cublas64_12.dll").write_bytes(b"dll")
        install.ensure_installed()
        dst = install.install_dir() / "cuda" / "nvidia" / "cublas" / "bin"
        self.assertTrue((dst / "cublas64_12.dll").is_file())
        self.assertFalse((self.downloads / "cuda").exists(),
                         "must MOVE the 1.9 GB runtime, not duplicate it")

    def test_migration_never_clobbers_installed_files(self):
        dst_dir = install.install_dir()
        dst_dir.mkdir(parents=True)
        (dst_dir / "config.yaml").write_text("installed config",
                                             encoding="utf-8")
        (self.downloads / "config.yaml").write_text("downloads config",
                                                    encoding="utf-8")
        install.ensure_installed()
        self.assertEqual((dst_dir / "config.yaml").read_text(encoding="utf-8"),
                         "installed config")

    def test_running_installed_copy_continues_without_handoff(self):
        exe = install.installed_exe()
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"installed")
        with mock.patch.object(sys, "executable", str(exe)):
            self.assertFalse(install.ensure_installed())
        self.assertEqual(self.spawned, [])

    def test_applied_updates_are_purged_newer_kept(self):
        exe = install.installed_exe()
        updates = exe.parent / "updates"
        updates.mkdir(parents=True)
        exe.write_bytes(b"installed")
        (updates / "Svara-0.0.1.exe").write_bytes(b"old staged")
        (updates / "Svara-99.0.0.exe").write_bytes(b"future staged")
        with mock.patch.object(sys, "executable", str(exe)):
            install.ensure_installed()
        self.assertFalse((updates / "Svara-0.0.1.exe").exists(),
                         "applied update must be cleaned up (107MB each)")
        self.assertTrue((updates / "Svara-99.0.0.exe").exists(),
                        "a not-yet-applied newer update must be kept")

    def test_old_download_does_not_replace_newer_install(self):
        exe = install.installed_exe()
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"NEWER installed bytes")
        install._write_manifest("99.0.0")

        handed_off = install.ensure_installed()

        self.assertTrue(handed_off, "must still hand off to the newer install")
        self.assertEqual(exe.read_bytes(), b"NEWER installed bytes",
                         "downgrade guard must not overwrite a newer version")
        self.assertEqual(self.spawned, [exe])

    def test_same_version_reinstall_overwrites(self):
        exe = install.installed_exe()
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"old bytes of same version")
        install._write_manifest(__version__)
        install.ensure_installed()
        self.assertEqual(exe.read_bytes(), b"fake exe bytes v1")

    def test_copy_failure_falls_back_to_portable(self):
        with mock.patch.object(shutil, "copy2",
                               side_effect=OSError("AV says no")):
            self.assertFalse(install.ensure_installed(),
                             "install failure must keep the app running here")
        self.assertEqual(self.spawned, [])

    def test_non_frozen_dev_run_is_untouched(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertFalse(install.ensure_installed())
        self.assertFalse(install.install_dir().exists())


class TestAutostart(InstallTestBase):
    def _install(self):
        exe = install.installed_exe()
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"installed")
        return exe

    def test_set_autostart_registers_installed_exe(self):
        exe = self._install()
        self.assertTrue(install.set_autostart(True))
        value = self._read_test_run_value()
        self.assertEqual(value, f'"{exe}" --autostart')
        self.assertTrue(install.autostart_registered())

    def test_set_autostart_false_removes_key(self):
        self._install()
        install.set_autostart(True)
        self.assertTrue(install.set_autostart(False))
        self.assertIsNone(self._read_test_run_value())
        self.assertFalse(install.autostart_registered())

    def test_disable_when_never_registered_is_fine(self):
        self.assertTrue(install.set_autostart(False))

    def test_ensure_autostart_defaults_on_for_installed_copy(self):
        exe = self._install()
        with mock.patch.object(sys, "executable", str(exe)):
            install.ensure_autostart()
        self.assertTrue(install.autostart_registered())

    def test_ensure_autostart_respects_user_opt_out(self):
        exe = self._install()
        install.set_autostart(True)
        (exe.parent / "state.json").write_text('{"autostart": false}',
                                               encoding="utf-8")
        with mock.patch.object(sys, "executable", str(exe)), \
                mock.patch("mywhisper.paths.state_path",
                           return_value=exe.parent / "state.json"):
            install.ensure_autostart()
        self.assertFalse(install.autostart_registered(),
                         "user's opt-out must survive the self-heal")

    def test_ensure_autostart_noop_for_non_installed_copy(self):
        self._install()
        install.ensure_autostart()  # sys.executable is the Downloads exe
        self.assertFalse(install.autostart_registered())

    def test_version_tuple_handles_junk(self):
        self.assertEqual(install._version_tuple("0.3.0"), (0, 3, 0))
        self.assertGreater(install._version_tuple("0.10.0"),
                           install._version_tuple("0.9.9"))
        self.assertEqual(install._version_tuple("1.2b.x"), (1, 2, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
