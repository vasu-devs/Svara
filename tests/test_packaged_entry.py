"""The release executable must preserve diagnostic failure exit codes."""
import unittest
from unittest import mock
import app_entry


class PackagedEntry(unittest.TestCase):
    def test_diagnostic_exit_code_is_preserved(self):
        for result in (0, 1, 2, 3):
            with self.subTest(result=result), mock.patch.object(app_entry, "_run_once", return_value=result):
                self.assertEqual(app_entry.main(), result)

    def test_argument_errors_do_not_restart_the_app(self):
        with mock.patch.object(app_entry, "_run_once", side_effect=SystemExit(2)) as run:
            self.assertEqual(app_entry.main(), 2)
            run.assert_called_once()

    def test_windowless_doctor_results_reach_the_log(self):
        from mywhisper import doctor
        with mock.patch("sys.stdout", None), self.assertLogs("mywhisper.doctor", level="INFO") as captured:
            doctor._ok("model ready")
            doctor._fail("microphone unavailable")
        self.assertIn("[OK] model ready", captured.output[0])
        self.assertIn("[FAIL] microphone unavailable", captured.output[1])
