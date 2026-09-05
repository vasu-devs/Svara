"""Regression tests for invalid configuration and recording lifecycle races."""
import copy
import io
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from mywhisper import config


class ConfigValidation(unittest.TestCase):
    def load_text(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.yaml"
            path.write_text(text, encoding="utf-8")
            return config.load(path)

    def test_invalid_sections_keep_other_preferences(self):
        cfg = self.load_text("audio: null\nmodel: []\nui:\n  theme: sakura\n")
        self.assertEqual(cfg["audio"], config.DEFAULTS["audio"])
        self.assertEqual(cfg["model"], config.DEFAULTS["model"])
        self.assertEqual(cfg["ui"]["theme"], "sakura")

    def test_bad_numbers_and_privacy_strings_are_not_truthy_settings(self):
        cfg = self.load_text('audio:\n  sample_rate: 0\n  block_size: -1\n  gain: .nan\ncontext:\n  read_caret_text: "false"\n')
        self.assertEqual(cfg["audio"]["sample_rate"], 16000)
        self.assertEqual(cfg["audio"]["block_size"], 512)
        self.assertEqual(cfg["audio"]["gain"], 1)
        self.assertIs(cfg["context"]["read_caret_text"], False)

    def test_unknown_modes_fall_back_and_extensions_survive(self):
        cfg = self.load_text("streaming:\n  mode: typo\nmodel:\n  language: null\ndictionary:\n  replacements:\n    swara: Svara\n")
        self.assertEqual(cfg["streaming"]["mode"], "live")
        self.assertIsNone(cfg["model"]["language"])
        self.assertEqual(cfg["dictionary"]["replacements"]["swara"], "Svara")

    def test_defaults_are_not_mutated(self):
        before = copy.deepcopy(config.DEFAULTS)
        self.load_text("ui:\n  scale: 2\n")
        self.assertEqual(before, config.DEFAULTS)


class RecorderLifecycle(unittest.TestCase):
    def recorder(self, stream):
        from mywhisper.audio import Recorder
        with mock.patch("sounddevice.InputStream", return_value=stream):
            result = Recorder(config.DEFAULTS["audio"], config.DEFAULTS["recording"])
        self.addCleanup(result.close)
        return result

    def test_failed_start_closes_allocated_device(self):
        stream = mock.MagicMock()
        stream.start.side_effect = OSError("disconnected")
        recorder = self.recorder(stream)
        self.assertFalse(recorder.open())
        stream.close.assert_called_once()
        self.assertIsNone(recorder._stream)

    def test_close_releases_device_even_when_stop_raises(self):
        stream = mock.MagicMock()
        stream.stop.side_effect = OSError("lost device")
        recorder = self.recorder(stream)
        recorder.close()
        stream.close.assert_called_once()
        self.assertFalse(recorder._spill_thread.is_alive())
        self.assertFalse(recorder.available)
        self.assertFalse(recorder.ensure_alive())

    def test_failed_candidates_are_closed_before_retry(self):
        recorder = self.recorder(mock.MagicMock(active=False))
        bad = mock.MagicMock()
        bad.start.side_effect = OSError("busy")
        good = mock.MagicMock(active=True, device=1)
        with mock.patch.object(recorder, "_candidates", return_value=[0, 1]), \
             mock.patch.object(recorder, "_make_stream", side_effect=[bad, good]), \
             mock.patch("sounddevice._terminate"), mock.patch("sounddevice._initialize"), \
             mock.patch("sounddevice.query_devices", return_value={"name": "Working mic"}):
            self.assertTrue(recorder.ensure_alive())
        bad.close.assert_called_once()
        self.assertIs(recorder._stream, good)


class RecordingLifecycle(unittest.TestCase):
    def app(self):
        from mywhisper.app import MyWhisperApp
        from mywhisper.pipeline.base import UtteranceContext
        app = MyWhisperApp.__new__(MyWhisperApp)
        app.cfg = config.load(None)
        app.cfg["ui"]["sounds"] = False
        app.recorder = mock.MagicMock(sr=16000, recording=False, available=True)
        app.transcriber = mock.MagicMock(ready=True)
        app.overlay = mock.MagicMock()
        app.injector = mock.MagicMock()
        app.cleanup = mock.MagicMock()
        app.cleanup.run.side_effect = lambda text, **kwargs: text
        app.tray = None
        app.paused = False
        app._stopping = False
        app._processing_pending = False
        app._stop_lock = threading.Lock()
        app._shutdown = threading.Event()
        app._queue = queue.Queue()
        app._stream_ctx = None
        app._finalize_timer = None
        app._ctx = UtteranceContext(app="new-app.exe")
        app._notify = mock.MagicMock()
        app._record_history = mock.MagicMock()
        app._auto_transform = lambda t: t
        app._seg_caps_flags = lambda *a, **k: [False]
        app.session_words = 0
        return app

    def test_no_mic_does_not_show_a_fake_listening_state(self):
        app = self.app()
        app.recorder.available = False
        app.start_recording()
        app.recorder.start.assert_not_called()
        app.overlay.show.assert_not_called()
        app._notify.assert_called_once()
        app.on_lock()
        app.overlay.show.assert_not_called()

    def test_pending_dictation_does_not_get_overwritten(self):
        app = self.app()
        app._processing_pending = True
        app.start_recording()
        app.recorder.start.assert_not_called()

    def test_cancel_cannot_delete_processing_recovery(self):
        app = self.app()
        app._processing_pending = True
        app.cancel_recording()
        app.recorder.discard_recovery.assert_not_called()

    def test_old_stop_timer_cannot_stop_new_recording(self):
        app = self.app()
        old = {"mode": "off"}
        app._stream_ctx = {"mode": "live"}
        app._stopping = True
        app._finalize_stop(old)
        app.recorder.stop.assert_not_called()
        self.assertTrue(app._stopping)

    def test_worker_uses_queued_context_and_releases_busy_state(self):
        from mywhisper.pipeline.base import UtteranceContext
        app = self.app()
        original = UtteranceContext(app="wt.exe", is_terminal=True)
        app.transcriber.transcribe.return_value = [("hello", 0, 1)]
        app.injector.inject.return_value = 5
        app._record_history.side_effect = lambda text: app._shutdown.set()
        app._processing_pending = True
        app._queue.put((np.zeros(16000), {"utterance": original}))
        app._worker()
        app.injector.inject.assert_called_once_with("hello", original)
        self.assertFalse(app._processing_pending)
        self.assertEqual(app._queue.unfinished_tasks, 0)


class DoctorChecks(unittest.TestCase):
    def test_cpu_machine_is_healthy_without_cuda_and_downloads_nothing(self):
        from mywhisper.doctor import run_doctor
        sd = mock.MagicMock()
        sd.query_devices.return_value = {"name": "Test microphone"}
        ct = mock.MagicMock(__version__="test")
        ct.get_cuda_device_count.return_value = 0
        fw = mock.MagicMock()
        fw.WhisperModel.return_value.transcribe.return_value = ([], None)
        with mock.patch.dict("sys.modules", {"sounddevice": sd, "ctranslate2": ct, "faster_whisper": fw}), \
             mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(run_doctor(config.load(None), []), 0)
        self.assertTrue(fw.WhisperModel.call_args.kwargs["local_files_only"])
        self.assertEqual(fw.WhisperModel.call_args.args[0], "base.en")
        sd.check_input_settings.assert_called_once()


class OverlayRendering(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is optional in unit-test CI")

    def test_preview_expands_the_pill_and_renders_unicode_captions(self):
        from mywhisper.overlay import Overlay
        for text in ("A thought ready to become text.", "你好，世界。", "Bonjour à tous !"):
            overlay = Overlay({"overlay": False})
            compact = overlay._dims()
            overlay._preview = text
            w, h = overlay._dims()
            self.assertGreater(w, compact[0])
            self.assertGreater(h, compact[1])
            caption = overlay._render_frame(0, "listening", w, h)
            overlay._preview = " "
            blank = overlay._render_frame(0, "listening", w, h)
            self.assertNotEqual(caption.tobytes(), blank.tobytes())
            overlay._preview = ""
            self.assertEqual(overlay._dims(), compact)

    def test_new_visualizers_animate_and_reduced_motion_freezes_them(self):
        from mywhisper.overlay import Overlay
        for wave in ("orbit", "ribbon"):
            for scale in (0.5, 1, 2):
                with self.subTest(wave=wave, scale=scale):
                    overlay = Overlay({"overlay": False, "wave": wave, "scale": scale})
                    overlay._display_level = 0.6
                    w, h = overlay._dims()
                    first = overlay._render_frame(0, "listening", w, h)
                    later = overlay._render_frame(20, "listening", w, h)
                    self.assertNotEqual(first.tobytes(), later.tobytes())
                    overlay._reduced_motion = True
                    first = overlay._render_frame(0, "listening", w, h)
                    later = overlay._render_frame(20, "listening", w, h)
                    self.assertEqual(first.tobytes(), later.tobytes())


if __name__ == "__main__":
    unittest.main()
