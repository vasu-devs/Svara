"""Unit tests for LlmCleanup's dual-backend support (Ollama + OpenAI-compat),
with all HTTP mocked — no server needed.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_llm_backend -v
"""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.cleanup import LlmCleanup  # noqa: E402

CFG = {"enabled": False, "api": "auto", "url": "http://localhost:11434",
       "openai_url": "http://localhost:1234/v1", "openai_model": None,
       "model": "qwen2.5:3b-instruct", "timeout_s": 5, "keep_alive": "10m",
       "prompt": "clean it"}


def fake_urlopen(routes):
    """routes: {url_substring: dict-response or Exception}. Returns a patch
    target for urllib.request.urlopen."""
    def opener(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        for frag, resp in routes.items():
            if frag in url:
                if isinstance(resp, Exception):
                    raise resp
                body = io.BytesIO(json.dumps(resp).encode("utf-8"))
                body.__enter__ = lambda s=body: s
                body.__exit__ = lambda s, *a: False
                return body
        raise OSError(f"unrouted url {url}")
    return opener


class TestBackendDetection(unittest.TestCase):
    def test_auto_prefers_ollama(self):
        llm = LlmCleanup(dict(CFG))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "11434/api/tags": {"models": []},
                "1234/v1/models": {"data": [{"id": "qwen"}]}})):
            self.assertEqual(llm.backend(), "ollama")

    def test_auto_falls_back_to_openai(self):
        llm = LlmCleanup(dict(CFG))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "11434": OSError("refused"),
                "1234/v1/models": {"data": [{"id": "loaded-model"}]}})):
            self.assertEqual(llm.backend(), "openai")
            self.assertEqual(llm._openai_model, "loaded-model")

    def test_auto_neither_is_none_and_cached(self):
        llm = LlmCleanup(dict(CFG))
        calls = []

        def opener(req, timeout=None):
            calls.append(1)
            raise OSError("refused")

        with mock.patch("urllib.request.urlopen", side_effect=opener):
            self.assertIsNone(llm.backend())
            n = len(calls)
            self.assertIsNone(llm.backend())  # negative result must be cached
            self.assertEqual(len(calls), n, "re-probed inside the cache window")

    def test_openai_mode_without_models_is_unreachable(self):
        llm = LlmCleanup(dict(CFG, api="openai"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "1234/v1/models": {"data": []}})):
            self.assertFalse(llm.reachable())

    def test_pinned_openai_model_wins(self):
        llm = LlmCleanup(dict(CFG, api="openai", openai_model="pinned"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "1234/v1/models": {"data": [{"id": "other"}]}})):
            self.assertTrue(llm.reachable())
            self.assertEqual(llm._openai_model, "pinned")


class TestRunPrompt(unittest.TestCase):
    def test_openai_chat_completion_roundtrip(self):
        llm = LlmCleanup(dict(CFG, api="openai"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "1234/v1/models": {"data": [{"id": "m"}]},
                "1234/v1/chat/completions": {
                    "choices": [{"message": {"content": "Cleaned text."}}]}})):
            self.assertEqual(llm.run_prompt("sys", "raw dictated text"),
                             "Cleaned text.")

    def test_ollama_chat_roundtrip(self):
        llm = LlmCleanup(dict(CFG, api="ollama"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "11434/api/tags": {"models": []},
                "11434/api/chat": {"message": {"content": "Via Ollama."}}})):
            self.assertEqual(llm.run_prompt("sys", "raw dictated text"),
                             "Via Ollama.")

    def test_no_server_returns_none_and_run_falls_back(self):
        llm = LlmCleanup(dict(CFG))
        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("refused")):
            self.assertIsNone(llm.run_prompt("sys", "raw dictated text"))
            self.assertEqual(llm.run("raw dictated text"), "raw dictated text")

    def test_mid_call_failure_invalidates_backend(self):
        llm = LlmCleanup(dict(CFG, api="openai"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen({
                "1234/v1/models": {"data": [{"id": "m"}]},
                "1234/v1/chat/completions": OSError("server died")})):
            self.assertIsNone(llm.run_prompt("sys", "raw dictated text"))
        self.assertIsNone(llm._backend, "dead server must not stay cached as up")


if __name__ == "__main__":
    unittest.main(verbosity=2)
