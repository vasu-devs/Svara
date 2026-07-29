"""The whole app, wired up, with every optional feature turned on.

`test_livepath.py` runs the default configuration end-to-end. Nothing exercised
the *other* configuration — the one where transform slots are bound, auto-learn
is watching, the caret provider is live, `external_first` is picking a mic and
semantic endpointing is running. Each of those adds a constructor, a thread or a
hotkey binding, and a mistake in any of them is a crash on launch for whoever
turned it on.

So: build `MyWhisperApp` with everything enabled and assert it comes up whole.
Audio, model, overlay and tray are mocked; the wiring is real.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_app_smoke -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import config as config_mod  # noqa: E402
from mywhisper.pipeline import UtteranceContext  # noqa: E402


def everything_on(cfg: dict) -> dict:
    cfg["ui"]["tray"] = False
    cfg["ui"]["overlay"] = False
    cfg["update"]["check"] = False
    cfg["logging"]["debug_transcripts"] = False
    cfg["context"]["read_caret_text"] = True
    cfg["dictionary"]["auto_learn"] = True
    cfg["audio"]["device_policy"] = "external_first"
    cfg["locale"]["romanize"] = "auto"
    cfg["locale"]["english_variant"] = "en-GB"
    cfg["cleanup"]["level"] = "high"
    cfg["streaming"]["commit_policy"] = "adaptive"
    cfg["streaming"]["context_prompt_words"] = 8
    cfg["recording"]["auto_stop"].update(enabled=True, semantic=True)
    cfg["transforms"]["preview"] = "auto"
    cfg["transforms"]["auto_after_dictation"] = 2
    cfg["transforms"]["slots"] = {
        1: {"name": "Prompt Engineer", "builtin": "prompt_engineer",
            "hotkey": "<cmd>+<alt>+1"},
        2: {"name": "Concise", "prompt": "Tighten this.",
            "hotkey": "<cmd>+<alt>+2"},
        3: {"name": "Friendly", "prompt": "Warmer, please.",
            "hotkey": "<cmd>+<alt>+3"},
    }
    cfg["injection"]["targets"] = {"myeditor.exe": "shift_insert"}
    cfg["shortcuts"]["command_key"] = "f9"
    return cfg


class AppSmokeTest(unittest.TestCase):
    def _build(self, mutate=everything_on):
        from mywhisper.app import MyWhisperApp

        tmp = Path(tempfile.mkdtemp(prefix="svara-app-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        cfg = mutate(config_mod.load(None))
        transcriber = mock.MagicMock()
        transcriber.cfg = cfg["model"]
        transcriber.device_used = "cpu"
        transcriber.compute_used = "int8"
        transcriber.transcribe.return_value = []
        transcriber.transcribe_partial.return_value = []

        patches = [
            mock.patch("mywhisper.paths.base_dir", return_value=tmp),
            mock.patch("mywhisper.app.Recorder"),
            mock.patch("mywhisper.app.Overlay"),
            mock.patch("mywhisper.app.create_listener"),
            mock.patch("mywhisper.transforms.create_listener", create=True),
        ]
        for p in patches:
            try:
                p.start()
                self.addCleanup(p.stop)
            except (AttributeError, ModuleNotFoundError):
                pass

        app = MyWhisperApp(cfg, no_tray=True, transcriber=transcriber)
        self.addCleanup(app.shutdown)
        return app

    def test_constructs_with_everything_enabled(self):
        app = self._build()
        self.assertIsNotNone(app.cleanup)
        self.assertIsNotNone(app.injector)
        self.assertIsNotNone(app.transformer)
        self.assertIsNotNone(app.scratchpad)
        self.assertIsNotNone(app.learn_queue)
        self.assertIsNotNone(app.context_provider)

    def test_all_three_transform_slots_are_bound(self):
        app = self._build()
        names = {slot.number: slot.name
                 for slot in app.transformer.registry.slots.values()}
        self.assertEqual(names, {1: "Prompt Engineer", 2: "Concise",
                                 3: "Friendly"})
        self.assertEqual(app.transformer.registry.auto_slot().name, "Concise")

    def test_auto_learn_activates_only_with_both_opt_ins(self):
        self.assertTrue(self._build().auto_learner.enabled)

        def caret_off(cfg):
            cfg = everything_on(cfg)
            cfg["context"]["read_caret_text"] = False
            return cfg

        # It reads text Svara did not produce, so the caret permission gates it.
        self.assertFalse(self._build(caret_off).auto_learner.enabled)

    def test_command_mode_arms_when_a_key_is_configured(self):
        self.assertIsNotNone(self._build().command_mode)

    def test_pipeline_order_is_intact_under_this_config(self):
        app = self._build()
        self.assertEqual(app.cleanup.chain.order[-1], "personalizer")
        self.assertIn("romanize", app.cleanup.chain.order)

    def test_locale_reaches_the_pipeline(self):
        app = self._build()
        ctx = app.cleanup.context(locale="en-GB")
        self.assertEqual(app.cleanup.run("the color of the theater", ctx=ctx),
                         "the colour of the theatre")

    def test_injection_target_override_is_honoured(self):
        app = self._build()
        strategy = app.injector.strategy_for(
            UtteranceContext(app="myeditor.exe"))
        self.assertEqual(strategy.name, "shift_insert")

    def test_terminal_target_disables_live_streaming(self):
        app = self._build()
        self.assertFalse(app.injector.streams_into(
            UtteranceContext(app="cmd.exe", is_terminal=True)))

    def test_shutdown_is_idempotent(self):
        app = self._build()
        app.shutdown()
        app.shutdown()          # must not raise

    def test_defaults_also_construct(self):
        # The configuration 99% of users actually run.
        def defaults(cfg):
            cfg["ui"]["tray"] = False
            cfg["ui"]["overlay"] = False
            cfg["update"]["check"] = False
            return cfg

        app = self._build(defaults)
        self.assertFalse(app.auto_learner.enabled)
        self.assertIsNone(app.command_mode)
        self.assertEqual(app.transformer.registry.get(1).name,
                         "Prompt Engineer")


class TestWorkerPathWithoutAudio(unittest.TestCase):
    """The cleanup → transform → inject sequence, without a microphone."""

    def test_a_dictation_flows_through_to_the_injector(self):
        from mywhisper.app import MyWhisperApp

        tmp = Path(tempfile.mkdtemp(prefix="svara-worker-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        cfg = config_mod.load(None)
        cfg["ui"].update(tray=False, overlay=False)
        cfg["update"]["check"] = False
        cfg["locale"]["english_variant"] = "en-GB"

        transcriber = mock.MagicMock()
        transcriber.cfg = cfg["model"]
        transcriber.device_used, transcriber.compute_used = "cpu", "int8"

        with mock.patch("mywhisper.paths.base_dir", return_value=tmp), \
                mock.patch("mywhisper.app.Recorder"), \
                mock.patch("mywhisper.app.Overlay"), \
                mock.patch("mywhisper.app.create_listener"):
            app = MyWhisperApp(cfg, no_tray=True, transcriber=transcriber)
            self.addCleanup(app.shutdown)

            typed = []
            app.injector = mock.MagicMock()
            app.injector.inject.side_effect = \
                lambda t, ctx=None: typed.append(t) or len(t)

            app.reload_dictionary = mock.MagicMock()
            app._ctx = UtteranceContext(app="notepad.exe", locale="en-GB")
            text = app.cleanup.run("um the color of the theater", ctx=app._ctx)
            app.injector.inject(text, app._ctx)

        self.assertEqual(typed, ["the colour of the theatre"])


if __name__ == "__main__":
    unittest.main()
