"""Unit tests for the cleanup pipeline's personalization layer.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_cleanup -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.cleanup import CleanupPipeline, Personalizer, strip_fillers  # noqa: E402


def make_pipeline(dict_cfg=None):
    return CleanupPipeline(
        {"strip_fillers": True,
         "llm": {"enabled": False, "url": "", "model": "", "timeout_s": 1,
                 "prompt": ""}},
        dict_cfg)


class TestReplacements(unittest.TestCase):
    def test_case_insensitive_whole_word(self):
        p = Personalizer({"replacements": {"swara": "Svara"}})
        self.assertEqual(p.apply("I built swara and Swara, works"),
                         "I built Svara and Svara, works")

    def test_never_rewrites_inside_words(self):
        p = Personalizer({"replacements": {"cat": "dog"}})
        self.assertEqual(p.apply("concatenate the cat"), "concatenate the dog")

    def test_multiword_phrase(self):
        p = Personalizer({"replacements": {"get hub": "GitHub"}})
        self.assertEqual(p.apply("push it to get hub now"),
                         "push it to GitHub now")

    def test_backslashes_in_replacement_are_literal(self):
        p = Personalizer({"replacements": {"my folder": r"C:\Users\me"}})
        self.assertEqual(p.apply("open my folder please"),
                         r"open C:\Users\me please")


class TestSnippets(unittest.TestCase):
    def test_snippet_expands(self):
        p = Personalizer({"snippets": {"my email": "vasu@example.com"}})
        self.assertEqual(p.apply("send it to my email thanks"),
                         "send it to vasu@example.com thanks")

    def test_longer_trigger_wins_over_shorter_rule(self):
        p = Personalizer({
            "replacements": {"email": "e-mail"},
            "snippets": {"my email": "vasu@example.com"},
        })
        self.assertEqual(p.apply("my email is not just any email"),
                         "vasu@example.com is not just any e-mail")

    def test_multiline_snippet(self):
        p = Personalizer({"snippets": {"sign off": "Best,\nVasudev"}})
        self.assertEqual(p.apply("sign off"), "Best,\nVasudev")


class TestSpokenPunctuation(unittest.TestCase):
    def test_off_by_default(self):
        p = Personalizer({})
        self.assertEqual(p.apply("hello comma world"), "hello comma world")

    def test_basic_marks(self):
        p = Personalizer({"spoken_punctuation": True})
        self.assertEqual(p.apply("hello comma world period"), "hello, world.")
        self.assertEqual(p.apply("really question mark"), "really?")

    def test_whisper_punctuating_the_spoken_word(self):
        # Whisper often emits "hello, comma, world" — the mark it added to the
        # phrase itself must be swallowed too.
        p = Personalizer({"spoken_punctuation": True})
        self.assertEqual(p.apply("hello, comma, world"), "hello, world")

    def test_new_line_and_paragraph(self):
        p = Personalizer({"spoken_punctuation": True})
        self.assertEqual(p.apply("first item new line second item"),
                         "first item\nsecond item")
        self.assertEqual(p.apply("intro new paragraph body"), "intro\n\nbody")

    def test_multiword_before_subset_phrase(self):
        p = Personalizer({"spoken_punctuation": True})
        # "exclamation point" must not first match some shorter rule
        self.assertEqual(p.apply("wow exclamation point"), "wow!")


class TestPipelineOrder(unittest.TestCase):
    def test_fillers_then_personal_rules(self):
        pipe = make_pipeline({"replacements": {"swara": "Svara"}})
        self.assertEqual(pipe.run("um, swara uh works"), "Svara works")

    def test_personalizer_reload_swaps_rules_live(self):
        pipe = make_pipeline({"replacements": {"old": "OLD"}})
        pipe.personalizer.reload({"replacements": {"new": "NEW"}})
        self.assertEqual(pipe.run("old and new"), "old and NEW")

    def test_hotwords_property(self):
        p = Personalizer({"words": ["Svara", "CTranslate2"]})
        self.assertEqual(p.hotwords, "Svara, CTranslate2")
        self.assertIsNone(Personalizer({}).hotwords)

    def test_empty_config_is_identity(self):
        p = Personalizer(None)
        text = "leave me alone, please."
        self.assertEqual(p.apply(text), text)


class TestFillers(unittest.TestCase):
    def test_existing_behavior_unchanged(self):
        self.assertEqual(strip_fillers("um, hello uh world"), "hello world")


if __name__ == "__main__":
    unittest.main(verbosity=2)
