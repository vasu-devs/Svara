"""Behavioral corpus and end-to-end delivery tests for spoken repairs."""

import copy
import queue
import threading
import unittest
from unittest import mock

import numpy as np

from mywhisper.config import DEFAULTS
from mywhisper.pipeline import CleanupPipeline
from mywhisper.pipeline.base import UtteranceContext
from mywhisper.pipeline.corrections import resolve_corrections
from mywhisper.pipeline.llm import DICTATION_GUIDANCE, LlmCleanup
from mywhisper.pipeline.text_rules import strip_fillers


REPAIRS = [
    ("let's do the meeting at 5 no no no at 4", "let's do the meeting at 4"),
    ("Let's do the meeting at 5, no, no, no, at 4.", "Let's do the meeting at 4."),
    ("Meet at five, actually four.", "Meet at four."),
    ("Meet at 5 pm, no, 4.", "Meet at 4 pm."),
    ("Meet at 5 pm, no, 4 am.", "Meet at 4 am."),
    ("Meet at 5:30, I mean 4:30 tomorrow.", "Meet at 4:30 tomorrow."),
    ("Meet at 5, no 4, actually 3.", "Meet at 3."),
    ("Meet on Monday, sorry, Tuesday.", "Meet on Tuesday."),
    ("Meet in June, actually July.", "Meet in July."),
    ("Make it red, no, blue.", "Make it blue."),
    ("We need twenty five, I mean thirty two copies.", "We need thirty two copies."),
    ("Budget is $500, no, $400.", "Budget is $400."),
    ("Budget is $500, no, 400.", "Budget is $400."),
    ("Use version 1.2, no, 1.3.", "Use version 1.3."),
    ("Meet at 5 p.m., no, 4.", "Meet at 4 p.m."),
    ("I don't want 5, no no, 4 copies.", "I don't want 4 copies."),
    ("Wait five minutes, sorry ten.", "Wait ten minutes."),
    ("Send it to Alice, no no, to Bob before lunch.", "Send it to Bob before lunch."),
    ("Email Alice, I mean Bob, about the release.", "Email Bob, about the release."),
    ("Let's go to Boston, sorry to New York.", "Let's go to New York."),
    ("I want the blue one, no, I want the red one.", "I want the red one."),
    ("I can attend, actually I can't attend tomorrow.", "I can't attend tomorrow."),
    ("Keep the notes. Meet at 5. No no no, at 4.", "Keep the notes. Meet at 4."),
    ("Keep the notes.\nMeet at 5, no, 4.", "Keep the notes.\nMeet at 4."),
]
PRESERVE = [
    "No, no, no, don't cancel the meeting.",
    "I don't want to cancel the meeting.",
    "There are no meetings at 4.",
    "There is no time and no money.",
    "I mean what I say.",
    "Actually, I like this plan.",
    "The meeting at 5 actually works for me.",
    "I was sorry to hear that.",
    "I would rather meet at 5.",
    "No no no.",
    "Meet at 5, no no no",  # no replacement provided
    "Wear red, no blue was available.",
    "I want no red flags.",
    "There are 5 no more than 4 are ready.",
    "Meet on Monday, no, at four.",  # changing two different slots is ambiguous
    "Meet at 5.\nNo no, at 4.",
    'He said "at 5, no no, at 4" verbatim.',
    "Keep `at 5, no no, at 4` unchanged.",
    "Open https://example.com/no/5 and email no@example.com.",
    "That that person had had enough is very very clear.",
    "I like it, you know, like a song.",
    "Actually, no one was hurt.",
    "Meet at 5, I mean whenever you can.",  # broad semantic scope needs the LLM
]


def pipeline(**overrides):
    cfg = copy.deepcopy(DEFAULTS["cleanup"])
    cfg.update(overrides)
    return CleanupPipeline(cfg)


class SpokenRepairCorpus(unittest.TestCase):
    def test_explicit_repairs(self):
        for source, expected in REPAIRS:
            with self.subTest(source=source):
                self.assertEqual(resolve_corrections(source), expected)

    def test_meaning_and_literals_survive(self):
        for source in PRESERVE:
            with self.subTest(source=source):
                self.assertEqual(resolve_corrections(source), source)

    def test_fillers_and_stutters(self):
        cases = [
            ("ummm, aahhh, let's meet uh at four.", "let's meet at four."),
            ("Ummm... I I I want th-th-the report.", "I want the report."),
            ("we, we need it", "we need it"),
            ("Um. Uh! Aahhh...", ""),
            ('Write "umm aahhh" and `uh` literally.', 'Write "umm aahhh" and `uh` literally.'),
            ("Ah, that explains it. Aha!", "Ah, that explains it. Aha!"),
            ("That that person had had enough is very very clear.",
             "That that person had had enough is very very clear."),
            ("Email um@example.com and open https://example.com/uh.",
             "Email um@example.com and open https://example.com/uh."),
            ("a state-of-the-art design", "a state-of-the-art design"),
            ("Use a t-test on re-releases.", "Use a t-test on re-releases."),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(strip_fillers(source), expected)

    def test_cleanup_is_idempotent(self):
        pipe = pipeline()
        for source in [a for a, _ in REPAIRS] + PRESERVE:
            with self.subTest(source=source):
                result = pipe.run(source)
                self.assertEqual(pipe.run(result), result)

    def test_default_pipeline_example_and_filler_only(self):
        pipe = pipeline()
        self.assertEqual(pipe.run("umm let's do the meeting at 5 no no no at 4"),
                         "let's do the meeting at 4")
        self.assertEqual(pipe.run("umm aahhh uh"), "")

    def test_verbatim_and_disable_switch(self):
        source = "umm meet at 5 no no at 4"
        self.assertEqual(pipeline(level="none").run(source), source)
        self.assertEqual(pipeline(self_corrections=False).run(source), "meet at 5 no no at 4")

    def test_preview_never_calls_ai_or_expands_dictionary(self):
        pipe = pipeline(level="high")
        with mock.patch.object(pipe.llm, "backend", side_effect=AssertionError("network")):
            self.assertEqual(pipe.preview("umm at 5 no no at 4"), "at 4")

    def test_full_utterance_delivery_policy(self):
        self.assertTrue(pipeline().requires_final_cleanup)
        self.assertFalse(pipeline(self_corrections=False).requires_final_cleanup)
        self.assertFalse(pipeline(level="none").requires_final_cleanup)
        self.assertTrue(pipeline(level="medium", self_corrections=False).requires_final_cleanup)
        self.assertTrue(pipeline(level="high").requires_final_cleanup)

    def test_model_prompt_retains_negation_and_has_user_example(self):
        llm = LlmCleanup(copy.deepcopy(DEFAULTS["cleanup"]["llm"]))
        with mock.patch.object(llm, "run_prompt", return_value="I can't attend.") as call:
            self.assertEqual(llm.run("I can attend, actually I can't attend."), "I can't attend.")
        self.assertIn(DICTATION_GUIDANCE, call.call_args.args[0])
        self.assertIn("no no no", call.call_args.args[0])
        self.assertIn("negation", call.call_args.args[0])


class CorrectionDelivery(unittest.TestCase):
    def make_app(self):
        from mywhisper.app import MyWhisperApp
        app = MyWhisperApp.__new__(MyWhisperApp)
        app.cfg = copy.deepcopy(DEFAULTS)
        app.cfg["ui"]["sounds"] = False
        app.cleanup = pipeline()
        app.recorder = mock.MagicMock(sr=16000, recording=False, available=True)
        app.transcriber = mock.MagicMock(ready=True)
        app.overlay = mock.MagicMock()
        app.injector = mock.MagicMock()
        app.injector.streams_into.return_value = True
        app.context_provider = mock.Mock()
        app.context_provider.capture.return_value = (UtteranceContext(app="editor.exe"), [])
        app._ctx = UtteranceContext(app="editor.exe")
        app.tray = None
        app.paused = app._stopping = app._processing_pending = False
        app._stream_ctx = None
        app._stop_lock = threading.Lock()
        app._shutdown = threading.Event()
        app._queue = queue.Queue()
        app._seg_caps_flags = lambda *a, **kw: [False]
        app._auto_transform = lambda text: text
        app.session_words = 0
        app._record_history = mock.Mock(side_effect=lambda text: app._shutdown.set())
        return app

    def test_live_preference_previews_until_correction_is_known(self):
        app = self.make_app()
        with mock.patch("mywhisper.app.threading.Thread"):
            app.start_recording()
        self.assertEqual(app._stream_ctx["mode"], "preview")
        self.assertEqual(app.cfg["streaming"]["mode"], "live")
        app.injector.inject_stream.assert_not_called()

    def test_disabled_corrections_allow_live_mode(self):
        app = self.make_app()
        app.cleanup.self_corrections_enabled = False
        with mock.patch("mywhisper.app.threading.Thread"):
            app.start_recording()
        self.assertEqual(app._stream_ctx["mode"], "live")

    def test_setting_persists_the_explicit_false_value(self):
        app = self.make_app()
        app._save_state = mock.Mock()
        app._refresh_tray = mock.Mock()
        app.set_self_corrections(False)
        self.assertFalse(app.cleanup.self_corrections_enabled)
        self.assertFalse(app.cfg["cleanup"]["self_corrections"])
        app._save_state.assert_called_once_with(self_corrections=False)

    def test_worker_inserts_and_records_only_the_final_wording(self):
        app = self.make_app()
        app.transcriber.transcribe.return_value = [
            ("Ummm let's do the meeting at 5 no no no at 4", 0, 5)]
        app._queue.put((np.zeros(80000), {"mode": "preview", "utterance": app._ctx}))
        app._worker()
        expected = "let's do the meeting at 4"
        app.injector.inject.assert_called_once_with(expected, app._ctx)
        app._record_history.assert_called_once_with(expected)
        app.injector.inject_stream.assert_not_called()
        self.assertEqual(app.session_words, 6)

    def test_filler_only_never_injects_records_or_transforms(self):
        app = self.make_app()
        app.transcriber.transcribe.return_value = [("Ummm aahhh", 0, 2)]
        app.recorder.discard_recovery.side_effect = lambda: app._shutdown.set()
        app._auto_transform = mock.Mock()
        app._queue.put((np.zeros(32000), {"mode": "preview", "utterance": app._ctx}))
        app._worker()
        app.injector.inject.assert_not_called()
        app._record_history.assert_not_called()
        app._auto_transform.assert_not_called()

    def test_preview_supplies_semantic_endpoint_text(self):
        app = self.make_app()
        app._stream_ctx = {"preview_text": "we need to"}
        self.assertEqual(app._committed_so_far(), "we need to")


if __name__ == "__main__":
    unittest.main()
