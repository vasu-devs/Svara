"""Svara must still be there after a reboot.

The whole promise is: install once, then double-tap and talk, forever, without
thinking about it. The place that promise breaks is login. The HKCU Run entry
fires early in the session - routinely before the Windows Audio service has
finished enumerating endpoints, and later still for a USB or Bluetooth headset.

Before this, `Recorder.__init__` opened the input stream unguarded and `run()`
called `open()` unguarded, so a PortAudioError at that moment took the whole
process down. No tray, no hotkey, no dictation, and nothing on screen to
explain it. From the user's side: "it stopped working after I restarted."

These tests hold the line on the opposite behaviour - the app comes up, the
hotkey arms, and the microphone is picked up when it appears.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_startup_resilience -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import sounddevice  # noqa: F401
    HAVE_AUDIO = True
except Exception:  # noqa: BLE001
    HAVE_AUDIO = False

AUDIO_CFG = {"sample_rate": 16000, "block_size": 512, "input_device": None,
             "gain": 1.0, "device_policy": "preferred"}
REC_CFG = {"preroll_ms": 1000}


@unittest.skipUnless(HAVE_AUDIO, "sounddevice unavailable")
class TestRecorderSurvivesNoMicrophone(unittest.TestCase):
    """PortAudio raising at construction is a normal login-time event."""

    def _recorder(self, stream_factory):
        from mywhisper.audio import Recorder
        with mock.patch("sounddevice.InputStream", side_effect=stream_factory):
            return Recorder(dict(AUDIO_CFG), dict(REC_CFG))

    def test_construction_survives_a_missing_device(self):
        def boom(*a, **k):
            raise OSError("PortAudio: no default input device")

        recorder = self._recorder(boom)          # must not raise
        self.assertIsNone(recorder._stream)

    def test_open_reports_failure_instead_of_raising(self):
        def boom(*a, **k):
            raise OSError("PortAudio: device unavailable")

        recorder = self._recorder(boom)
        with mock.patch("sounddevice.InputStream", side_effect=boom):
            self.assertFalse(recorder.open())

    def test_open_succeeds_once_the_device_appears(self):
        # The real sequence: construction fails at login, then the audio
        # service finishes coming up and the retry works.
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("PortAudio: not ready")
            return mock.MagicMock(active=True, device=0)

        from mywhisper.audio import Recorder
        with mock.patch("sounddevice.InputStream", side_effect=flaky), \
                mock.patch("sounddevice.query_devices",
                           return_value={"name": "Test mic"}):
            recorder = Recorder(dict(AUDIO_CFG), dict(REC_CFG))
            self.assertIsNone(recorder._stream, "first attempt should fail")
            self.assertTrue(recorder.open(), "second attempt should succeed")
            self.assertIsNotNone(recorder._stream)

    @staticmethod
    def _query_devices(*args, **kwargs):
        """sounddevice.query_devices() returns a LIST of devices with no args,
        and a single device dict when given an index. Both are used here."""
        if args:
            return {"name": "Late mic", "max_input_channels": 1}
        return [{"name": "Late mic", "max_input_channels": 1}]

    def test_ensure_alive_recovers_from_a_null_stream(self):
        # The monitor calls this every 3 seconds; it is the thing that has to
        # rescue a bad start.
        def boom(*a, **k):
            raise OSError("PortAudio: no device")

        recorder = self._recorder(boom)
        good = mock.MagicMock(active=True, device=0)
        with mock.patch("sounddevice.InputStream", return_value=good), \
                mock.patch("sounddevice.query_devices",
                           side_effect=self._query_devices):
            self.assertTrue(recorder.ensure_alive())
        self.assertIsNotNone(recorder._stream)

    def test_repeated_failures_do_not_spam_warnings(self):
        # A machine with no microphone would otherwise log a warning every
        # 3 seconds for as long as it is switched on.
        def boom(*a, **k):
            raise OSError("PortAudio: no device")

        recorder = self._recorder(boom)
        with mock.patch("sounddevice.InputStream", side_effect=boom), \
                mock.patch("sounddevice.query_devices", side_effect=boom), \
                self.assertLogs("mywhisper.audio", level="WARNING") as caught:
            for _ in range(5):
                recorder.ensure_alive()
        warnings = [r for r in caught.records if r.levelname == "WARNING"]
        self.assertLessEqual(len(warnings), 2,
                             "should warn once, then drop to debug")


class TestTranscriberSurvivesAFailedLoad(unittest.TestCase):
    """Same failure class as the microphone, same login-time cause: no network
    yet, a half-written model cache, a GPU driver still initialising. An
    exception during construction used to take the whole app with it."""

    MCFG = {"name": "base.en", "device": "cpu", "compute_type": "int8",
            "language": "en", "beam_size": 2, "partial_beam_size": 2,
            "initial_prompt": None, "download_root": None}

    def _failing(self):
        from mywhisper.transcriber import Transcriber
        with mock.patch("mywhisper.asr.create",
                        side_effect=RuntimeError("no model cache")):
            return Transcriber(dict(self.MCFG))

    def test_construction_survives_and_reports_not_ready(self):
        t = self._failing()                    # must not raise
        self.assertFalse(t.ready)
        self.assertIsInstance(t.error, RuntimeError)

    def test_config_stays_usable_after_a_failed_load(self):
        # The app mutates transcriber.cfg constantly - hotwords, language,
        # per-utterance context. None of that may explode just because the
        # model is not up yet.
        t = self._failing()
        t.cfg["hotwords"] = "Svara, Kubernetes"
        t.cfg["context_hotwords"] = "Acme"
        t.cfg["language"] = "fr"
        self.assertEqual(t.cfg["language"], "fr")
        self.assertEqual(t.device_used, "loading")

    def test_decoding_raises_a_clear_error_until_ready(self):
        from mywhisper.transcriber import TranscriberNotReady
        t = self._failing()
        with self.assertRaises(TranscriberNotReady):
            t.transcribe(object())
        with self.assertRaises(TranscriberNotReady):
            t.transcribe_partial(object())

    def test_retry_recovers_once_the_model_is_available(self):
        t = self._failing()
        backend = mock.MagicMock(device_used="cpu", compute_used="int8")
        with mock.patch("mywhisper.asr.create", return_value=backend):
            self.assertTrue(t.retry(min_interval_s=0))
        self.assertTrue(t.ready)
        self.assertEqual(t.device_used, "cpu")

    def test_retry_is_rate_limited(self):
        # Reloading a model is expensive; a genuinely offline machine must not
        # burn every spare cycle rediscovering that.
        t = self._failing()
        with mock.patch("mywhisper.asr.create") as create:
            self.assertFalse(t.retry(min_interval_s=999))
            create.assert_not_called()

    def test_required_true_still_raises_for_callers_that_need_it(self):
        # Setup, --test and --bench have a human watching and must fail loudly;
        # a tray model-switch must raise so it keeps the WORKING model.
        from mywhisper.transcriber import Transcriber
        with mock.patch("mywhisper.asr.create",
                        side_effect=RuntimeError("nope")):
            with self.assertRaises(RuntimeError):
                Transcriber(dict(self.MCFG), required=True)


@unittest.skipUnless(HAVE_AUDIO, "sounddevice unavailable")
class TestHotkeyArmsWithoutAMicrophone(unittest.TestCase):
    """The point of all of the above: the hotkey still gets armed."""

    def test_run_arms_the_hotkey_even_when_open_fails(self):
        from mywhisper.app import MyWhisperApp

        app = MyWhisperApp.__new__(MyWhisperApp)   # skip __init__
        app.recorder = mock.MagicMock()
        app.recorder.open.return_value = False     # no mic at login
        app.hotkey = mock.MagicMock()
        app.quickkeys = mock.MagicMock()
        app.command_mode = None
        app.tray = None
        app.overlay = mock.MagicMock()
        app.updater = mock.MagicMock()
        app.cfg = {"update": {"check": False},
                   "recording": {"hotkey": "right alt", "mode": "hold_to_record"}}
        app.show_welcome = False
        app.quiet_start = True
        app._shutdown = mock.MagicMock()
        app._shutdown.is_set.return_value = True   # exit the idle loop at once
        app._recover_lost_dictation = lambda: None
        notes = []
        app._notify = notes.append
        app.shutdown = lambda: None

        with mock.patch("threading.Thread"):
            app.run()

        app.hotkey.start.assert_called_once()
        self.assertTrue(any("microphone" in n.lower() for n in notes),
                        f"user should be told why there is no mic yet: {notes}")


if __name__ == "__main__":
    unittest.main()
