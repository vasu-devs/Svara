"""The privacy guarantee: what you dictate must not reach the log file.

This is the test suite for the one bug in v0.4.1 that mattered most — an 80
character preview of every dictation written to `logs/mywhisper.log`, plaintext,
outliving the history retention the user configured.

The last test is the important one: it runs real text through the real pipeline
with logging captured, and asserts none of it comes out.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_redact -v
"""

import io
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import redact  # noqa: E402

SECRET = "my bank password is hunter2 and my address is 14 Elm Street"


class _Capture:
    """Attach a stream handler with the redaction filter, like __main__ does."""

    def __init__(self, level=logging.DEBUG):
        self.buffer = io.StringIO()
        self.handler = logging.StreamHandler(self.buffer)
        self.handler.setLevel(level)
        self.handler.addFilter(redact.RedactionFilter())

    def __enter__(self):
        root = logging.getLogger()
        self._old_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self.handler)
        return self

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self.handler)
        root.setLevel(self._old_level)

    @property
    def text(self) -> str:
        return self.buffer.getvalue()


class TestRedactDefaults(unittest.TestCase):
    def setUp(self):
        redact.configure({"debug_transcripts": False})

    def test_redact_hides_content_but_keeps_the_shape(self):
        out = redact.redact(SECRET)
        self.assertNotIn("hunter2", out)
        self.assertNotIn("Elm", out)
        # shape survives — it's what makes "did the pipeline eat my text?"
        # answerable without knowing what the text was
        self.assertIn(f"{len(SECRET.split())}w", out)
        self.assertIn(f"{len(SECRET)}c", out)

    def test_shape_never_reveals_content(self):
        self.assertNotIn("hunter2", redact.shape(SECRET))

    def test_none_is_handled(self):
        self.assertEqual(redact.redact(None), "«none»")
        self.assertEqual(redact.shape(None), "«none»")

    def test_keep_shows_only_short_structural_values(self):
        self.assertEqual(redact.redact("base.en", keep=32), "base.en")
        self.assertNotIn("hunter2", redact.redact(SECRET, keep=32))


class TestRedactEnabled(unittest.TestCase):
    def tearDown(self):
        redact.configure({"debug_transcripts": False})

    def test_opt_in_lets_transcripts_through(self):
        redact.configure({"debug_transcripts": True})
        self.assertEqual(redact.redact(SECRET), SECRET)

    def test_shape_stays_content_free_even_when_enabled(self):
        # High-frequency streaming logs must not become a transcript dump.
        redact.configure({"debug_transcripts": True})
        self.assertNotIn("hunter2", redact.shape(SECRET))

    def test_env_var_enables_it(self):
        import os
        os.environ["SVARA_DEBUG_TRANSCRIPTS"] = "1"
        try:
            self.assertTrue(redact.configure({"debug_transcripts": False}))
        finally:
            os.environ.pop("SVARA_DEBUG_TRANSCRIPTS", None)


class TestFilterBackstop(unittest.TestCase):
    """Call-site discipline is the primary defence; this catches the line
    someone adds in six months without reading redact.py."""

    def setUp(self):
        redact.configure({"debug_transcripts": False})

    def test_sensitive_spans_are_scrubbed(self):
        with _Capture() as cap:
            logging.getLogger("t").info("typed: %s", redact.sensitive(SECRET))
        self.assertNotIn("hunter2", cap.text)
        self.assertIn("redacted", cap.text)

    def test_records_tagged_user_text_are_dropped_entirely(self):
        with _Capture() as cap:
            logging.getLogger("t").info(SECRET, extra={"user_text": True})
        self.assertNotIn("hunter2", cap.text)

    def test_ordinary_messages_pass_through_untouched(self):
        with _Capture() as cap:
            logging.getLogger("t").info("model ready on cuda")
        self.assertIn("model ready on cuda", cap.text)

    def test_install_is_idempotent(self):
        handler = logging.StreamHandler(io.StringIO())
        logging.getLogger().addHandler(handler)
        try:
            redact.install(None)
            redact.install(None)
            filters = [f for f in handler.filters
                       if isinstance(f, redact.RedactionFilter)]
            self.assertEqual(len(filters), 1)
        finally:
            logging.getLogger().removeHandler(handler)


class TestNoTranscriptEscapesThePipeline(unittest.TestCase):
    """End-to-end: real text, real pipeline, logging captured."""

    def test_pipeline_run_logs_nothing_quotable(self):
        redact.configure({"debug_transcripts": False})
        from mywhisper.pipeline import CleanupPipeline

        pipe = CleanupPipeline(
            {"level": "high", "strip_fillers": True,
             "llm": {"enabled": False, "api": "auto",
                     "url": "http://127.0.0.1:1",
                     "openai_url": "http://127.0.0.1:1/v1",
                     "openai_model": None, "model": "none", "timeout_s": 1,
                     "keep_alive": "1m", "prompt": "p"}},
            {"replacements": {"hunter2": "hunter2"}})
        with _Capture() as cap:
            pipe.run("um " + SECRET)
        for fragment in ("hunter2", "Elm Street", "bank password"):
            self.assertNotIn(fragment, cap.text,
                             f"{fragment!r} leaked into the log")

    def test_failing_stage_logs_shape_not_content(self):
        redact.configure({"debug_transcripts": False})
        from mywhisper.pipeline.base import BaseStage, Chain, UtteranceContext

        class Boom(BaseStage):
            name = "boom"

            def run(self, text, ctx):
                raise RuntimeError("nope")

        with _Capture() as cap:
            Chain([Boom()]).run(SECRET, UtteranceContext())
        self.assertNotIn("hunter2", cap.text)
        self.assertIn("SVARA-PIPE-001", cap.text)


class TestErrorCodes(unittest.TestCase):
    def test_codes_are_unique_and_well_formed(self):
        codes = [v for k, v in vars(redact).items()
                 if k.startswith("E_") and isinstance(v, str)]
        self.assertTrue(codes)
        self.assertEqual(len(codes), len(set(codes)), "duplicate error code")
        for code in codes:
            self.assertRegex(code, r"^SVARA-[A-Z]+-\d{3}$")


if __name__ == "__main__":
    unittest.main()
