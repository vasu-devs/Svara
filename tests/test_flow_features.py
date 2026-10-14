"""Headless behavior tests for writing presets, snippets and developer syntax."""
import copy
import unittest
from unittest import mock

from mywhisper.config import DEFAULTS
from mywhisper.pipeline import CleanupPipeline
from mywhisper.pipeline.base import UtteranceContext
from mywhisper.pipeline.developer import developer_syntax
from mywhisper.pipeline.lists import numbered_lists
from mywhisper.pipeline.personal import Personalizer
from mywhisper.pipeline.writing_style import WritingStyleStage


class ExactSnippets(unittest.TestCase):
    def test_expansion_never_becomes_input_to_other_rules(self):
        p = Personalizer({"snippets": {"my signature": "Best,\nAlice at Example"},
                          "replacements": {"Alice": "Bob", "Example": "Elsewhere"}})
        self.assertEqual(p.apply("my signature"), "Best,\nAlice at Example")
        self.assertEqual(p.apply("Alice says my signature"), "Bob says Best,\nAlice at Example")

    def test_snippet_spacing_and_punctuation_are_literal(self):
        saved = "  code:\n    comma = 2\n\n"
        p = Personalizer({"snippets": {"my code": saved}, "spoken_punctuation": True})
        self.assertEqual(p.apply("my code."), saved)
        self.assertEqual(p.apply("my code"), saved)

    def test_nested_triggers_do_not_expand_recursively(self):
        p = Personalizer({"snippets": {"first trigger": "second trigger", "second trigger": "third"}})
        self.assertEqual(p.apply("first trigger, second trigger"), "second trigger, third")

    def test_replacement_overlap_uses_original_text(self):
        p = Personalizer({"replacements": {"a": "b", "b": "c"}})
        self.assertEqual(p.apply("a b"), "b c")

    def test_surrounding_spoken_marks_still_work(self):
        p = Personalizer({"snippets": {"my link": "https://example.com/comma"},
                          "spoken_punctuation": True})
        self.assertEqual(p.apply("see my link comma thanks period"),
                         "see https://example.com/comma, thanks.")


class WritingPresets(unittest.TestCase):
    def run_style(self, style, text, **ctx):
        stage = WritingStyleStage({"writing_style": style})
        context = UtteranceContext(**ctx)
        return stage.run(text, context) if stage.applies(context) else text

    def test_presets_do_not_rewrite_vocabulary(self):
        for style, expected in [("formal", "Thanks for the update."),
                                ("casual", "Thanks for the update"),
                                ("very_casual", "thanks for the update"),
                                ("excited", "Thanks for the update!")]:
            with self.subTest(style=style):
                self.assertEqual(self.run_style(style, "thanks for the update"), expected)

    def test_questions_and_ellipses_survive(self):
        for style in ("formal", "casual", "very_casual", "excited"):
            with self.subTest(style=style):
                self.assertTrue(self.run_style(style, "Really?").endswith("?"))
                self.assertTrue(self.run_style(style, "Maybe...").endswith("..."))

    def test_urls_code_and_quotations_remain_literal(self):
        for text in ("https://Example.com/Path", "User@Example.com", '`UserID`', '"Mixed Case"'):
            for style in ("formal", "casual", "very_casual", "excited"):
                with self.subTest(text=text, style=style):
                    self.assertEqual(self.run_style(style, text), text)

    def test_terminal_commands_and_non_english_are_unchanged(self):
        self.assertEqual(self.run_style("excited", "git status", is_terminal=True), "git status")
        self.assertEqual(self.run_style("excited", "bonjour", locale="fr-FR"), "bonjour")
        self.assertEqual(self.run_style("formal", "make it shorter", source="command"), "make it shorter")

    def test_exact_app_overrides_category_and_global(self):
        stage = WritingStyleStage({"writing_style": "formal",
                                   "formatting_styles": {"chat": "casual", "Slack.exe": "excited"}})
        self.assertEqual(stage.style_for(UtteranceContext(app="slack.exe", is_chat=True)), "excited")
        self.assertEqual(stage.style_for(UtteranceContext(app="signal.exe", is_chat=True)), "casual")
        self.assertEqual(stage.style_for(UtteranceContext(app="notepad.exe")), "formal")

    def test_invalid_overrides_are_identity(self):
        stage = WritingStyleStage({"formatting_styles": {"default": ["not a style"]}})
        self.assertFalse(stage.applies(UtteranceContext()))


class DeveloperDictation(unittest.TestCase):
    def test_explicit_identifier_forms(self):
        for phrase, expected in [("camel case", "userAccountId"), ("snake case", "user_account_id"),
                                 ("pascal case", "UserAccountId"), ("kebab case", "user-account-id"),
                                 ("constant case", "USER_ACCOUNT_ID")]:
            with self.subTest(phrase=phrase):
                self.assertEqual(developer_syntax(f"Use {phrase} user account id end name here."),
                                 f"Use {expected} here.")

    def test_explicit_filenames_and_paths(self):
        for source, expected in [("file name main dot py end file", "main.py"),
                                 ("file name Main dot tsx end file", "Main.tsx"),
                                 ("file name dot env end file", ".env"),
                                 ("file name src slash my underscore file dot tsx end file", "src/my_file.tsx")]:
            with self.subTest(source=source):
                self.assertEqual(developer_syntax(source), expected)

    def test_ambiguous_incomplete_or_literal_commands_are_preserved(self):
        for text in ("Let's discuss camel case today.", "snake case user name",
                     "snake case 123 item end name", "file name my file dot py end file",
                     '"snake case user name end name"', '`camel case user id end name`',
                     "file name dot dot slash secrets end file"):
            with self.subTest(text=text):
                self.assertEqual(developer_syntax(text), text)


class ListFormatting(unittest.TestCase):
    def test_digit_lists_with_intro(self):
        self.assertEqual(numbered_lists("Going to the store for 1. apples 2. bananas 3. oranges"),
                         "Going to the store for\n1. Apples\n2. Bananas\n3. Oranges")

    def test_parenthesized_markers_and_idempotence(self):
        text = "Steps: 1) clone 2) build 3) run"
        expected = "Steps:\n1. Clone\n2. Build\n3. Run"
        self.assertEqual(numbered_lists(text), expected)
        self.assertEqual(numbered_lists(expected), expected)

    def test_numbers_are_not_always_lists(self):
        for text in ("Versions 1.2, 2.3 and 3.4", "1. first 3. third 5. fifth",
                     "1. one 2. two", 'He said "1. one 2. two 3. three"',
                     "Read chapter 1. Then chapter 2. Then chapter 3."):
            with self.subTest(text=text):
                self.assertEqual(numbered_lists(text), text)


class PipelineIntegration(unittest.TestCase):
    def pipe(self, **kwargs):
        cfg = copy.deepcopy(DEFAULTS["cleanup"])
        cfg.update(kwargs.pop("cleanup", {}))
        return CleanupPipeline(cfg, **kwargs)

    def test_user_dictionary_wins_over_lowercase_style(self):
        pipe = self.pipe(context_cfg={"writing_style": "very_casual"},
                         dict_cfg={"replacements": {"svara": "Svara"}})
        self.assertEqual(pipe.run("Hello Svara."), "hello Svara")

    def test_formal_override_wins_over_old_chat_period_rule(self):
        pipe = self.pipe(context_cfg={"writing_style": "formal"})
        self.assertEqual(pipe.run("Thank you.", ctx=pipe.context(is_chat=True)), "Thank you.")

    def test_styles_and_syntax_work_without_a_model(self):
        pipe = self.pipe(cleanup={"developer_syntax": True})
        with mock.patch.object(pipe.llm, "backend", side_effect=AssertionError("network")):
            self.assertEqual(pipe.run("Use snake case user id end name."), "Use user_id.")
            pipe.set_writing_style("formal")
            self.assertEqual(pipe.run("thanks for your help"), "Thanks for your help.")

    def test_verbatim_disables_generated_syntax_and_style(self):
        pipe = self.pipe(cleanup={"level": "none", "developer_syntax": True},
                         context_cfg={"writing_style": "excited"})
        text = "snake case user id end name"
        self.assertEqual(pipe.run(text), text)

    def test_rich_features_are_not_bypassed_by_live_typing(self):
        for kwargs in ({"dict_cfg": {"snippets": {"my link": "https://example.com"}}},
                       {"context_cfg": {"writing_style": "formal"}},
                       {"cleanup": {"developer_syntax": True}}):
            with self.subTest(kwargs=kwargs):
                pipe = self.pipe(**kwargs)
                pipe.self_corrections_enabled = False
                self.assertTrue(pipe.requires_final_cleanup)


if __name__ == "__main__":
    unittest.main()
