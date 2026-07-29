"""The cleanup pipeline: stage contract, ordering invariants, and the rules.

The ordering assertions here are the point of the whole refactor. "The
personalizer runs last" used to be a comment; now it fails a test if someone
reorders `build_chain`.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_pipeline -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.pipeline import (Chain, CleanupPipeline,  # noqa: E402
                                UtteranceContext, build_chain, cjk_spacing,
                                english_variant, french_spacing,
                                numbered_lists, resolve_locale, romanize)
from mywhisper.pipeline.app_rules import AppRulesStage, ContinuationStage  # noqa: E402
from mywhisper.pipeline.base import BaseStage  # noqa: E402
from mywhisper.pipeline.locale import NBSP, NNBSP, LocaleTypographyStage  # noqa: E402

LLM_OFF = {"enabled": False, "api": "auto", "url": "http://127.0.0.1:1",
           "openai_url": "http://127.0.0.1:1/v1", "openai_model": None,
           "model": "none", "timeout_s": 1, "keep_alive": "1m", "prompt": "p"}


def make_pipeline(dict_cfg=None, locale_cfg=None, level="light"):
    return CleanupPipeline(
        {"level": level, "strip_fillers": True, "llm": dict(LLM_OFF)},
        dict_cfg, locale_cfg=locale_cfg)


# ---------------------------------------------------------------------------
# Chain contract
# ---------------------------------------------------------------------------

class _Boom(BaseStage):
    name = "boom"

    def run(self, text, ctx):
        raise RuntimeError("stage exploded")


class _Eraser(BaseStage):
    name = "eraser"

    def run(self, text, ctx):
        return ""


class _Upper(BaseStage):
    name = "upper"

    def run(self, text, ctx):
        return text.upper()


class TestChainIsFailSafe(unittest.TestCase):
    def test_a_raising_stage_does_not_cost_the_utterance(self):
        chain = Chain([_Boom(), _Upper()])
        self.assertEqual(chain.run("keep me", UtteranceContext()), "KEEP ME")

    def test_a_stage_that_empties_text_is_refused(self):
        # Losing words is the worst failure this app has. Fail closed.
        chain = Chain([_Eraser()])
        self.assertEqual(chain.run("do not vanish", UtteranceContext()),
                         "do not vanish")

    def test_min_level_gates_stages(self):
        stage = _Upper()
        stage.min_level = 3
        chain = Chain([stage])
        self.assertEqual(chain.run("x y", UtteranceContext(level="light")), "x y")
        self.assertEqual(chain.run("x y", UtteranceContext(level="high")), "X Y")

    def test_empty_input_short_circuits(self):
        self.assertEqual(Chain([_Boom()]).run("", UtteranceContext()), "")


class TestStageOrder(unittest.TestCase):
    def test_declared_order(self):
        order = build_chain({"strip_fillers": True, "llm": dict(LLM_OFF)}).order
        self.assertEqual(order, [
            "fillers", "backtrack", "numbered_lists", "llm", "locale",
            "romanize", "app_rules", "continuation", "personalizer"])

    def test_personalizer_is_always_last(self):
        # The user's replacement table is the one thing here that is not a
        # guess. Nothing downstream may overrule it.
        self.assertEqual(
            build_chain({"strip_fillers": True, "llm": dict(LLM_OFF)}).order[-1],
            "personalizer")

    def test_typography_runs_after_the_llm(self):
        # French spacing has to see final punctuation, not a draft of it.
        order = build_chain({"strip_fillers": True, "llm": dict(LLM_OFF)}).order
        self.assertLess(order.index("llm"), order.index("locale"))


# ---------------------------------------------------------------------------
# French
# ---------------------------------------------------------------------------

class TestFrenchSpacing(unittest.TestCase):
    def test_narrow_nbsp_before_high_punctuation(self):
        self.assertEqual(french_spacing("Bonjour !"), f"Bonjour{NNBSP}!")
        self.assertEqual(french_spacing("Ça va ?"), f"Ça va{NNBSP}?")
        self.assertEqual(french_spacing("un ; deux"), f"un{NNBSP}; deux")

    def test_colon_takes_a_full_nbsp(self):
        # The colon is the Imprimerie nationale exception.
        self.assertEqual(french_spacing("Oui : bien"), f"Oui{NBSP}: bien")

    def test_guillemets(self):
        out = french_spacing("« mot »")
        self.assertEqual(out, f"«{NNBSP}mot{NNBSP}»")

    def test_existing_space_is_replaced_not_doubled(self):
        self.assertEqual(french_spacing("Quoi ?"), f"Quoi{NNBSP}?")
        self.assertNotIn(" " + NNBSP, french_spacing("Quoi ?"))

    def test_times_are_protected(self):
        self.assertEqual(french_spacing("à 12:30 précises"), "à 12:30 précises")

    def test_urls_are_protected(self):
        self.assertEqual(french_spacing("https://example.com/a?b=1"),
                         "https://example.com/a?b=1")

    def test_code_spans_are_protected(self):
        self.assertEqual(french_spacing("`ls -la; pwd`"), "`ls -la; pwd`")

    def test_idempotent(self):
        once = french_spacing("Bonjour ! Ça va ?")
        self.assertEqual(french_spacing(once), once)


class TestLocaleStageSuppression(unittest.TestCase):
    def test_never_runs_in_a_terminal(self):
        # An invisible U+202F in a shell command is an error message naming a
        # character the user cannot see.
        stage = LocaleTypographyStage()
        self.assertFalse(stage.applies(UtteranceContext(is_terminal=True,
                                                        locale="fr-FR")))

    def test_runs_in_a_normal_field(self):
        stage = LocaleTypographyStage()
        self.assertTrue(stage.applies(UtteranceContext(locale="fr-FR")))
        self.assertEqual(stage.run("Quoi ?", UtteranceContext(locale="fr-FR")),
                         f"Quoi{NNBSP}?")


# ---------------------------------------------------------------------------
# CJK
# ---------------------------------------------------------------------------

class TestCjkSpacing(unittest.TestCase):
    def test_strips_space_around_full_width_punctuation(self):
        self.assertEqual(cjk_spacing("你好 。 这是 测试 ！"), "你好。这是测试！")

    def test_keeps_the_space_between_cjk_and_latin(self):
        # This one is correct and is the classic over-correction.
        self.assertEqual(cjk_spacing("测试 hello"), "测试 hello")

    def test_latin_only_text_untouched(self):
        self.assertEqual(cjk_spacing("hello world!"), "hello world!")


# ---------------------------------------------------------------------------
# English variants
# ---------------------------------------------------------------------------

class TestEnglishVariants(unittest.TestCase):
    def test_us_to_gb(self):
        self.assertEqual(
            english_variant("The color of the theater organization", "en-GB"),
            "The colour of the theatre organisation")

    def test_gb_to_us(self):
        self.assertEqual(
            english_variant("The colour of the theatre organisation", "en-US"),
            "The color of the theater organization")

    def test_canadian_is_british_our_plus_american_ize(self):
        self.assertEqual(english_variant("color organisation", "en-CA"),
                         "colour organization")

    def test_ise_exceptions_are_never_converted(self):
        # "surprize" and "advertize" are the classic naive-converter bugs.
        out = english_variant("surprise advertise exercise compromise", "en-US")
        self.assertEqual(out, "surprise advertise exercise compromise")

    def test_always_ize_words_survive_gb(self):
        self.assertEqual(english_variant("capsize the prize", "en-GB"),
                         "capsize the prize")

    def test_yse_family(self):
        self.assertEqual(english_variant("analyse paralyse", "en-US"),
                         "analyze paralyze")
        self.assertEqual(english_variant("analyze", "en-GB"), "analyse")

    def test_case_is_preserved(self):
        self.assertEqual(english_variant("Color COLOR color", "en-GB"),
                         "Colour COLOUR colour")

    def test_never_fires_inside_a_longer_word(self):
        self.assertEqual(english_variant("Colorado", "en-GB"), "Colorado")

    def test_double_l_forms(self):
        self.assertEqual(english_variant("traveled and canceled", "en-GB"),
                         "travelled and cancelled")

    def test_unknown_variant_is_a_no_op(self):
        self.assertEqual(english_variant("color", "en-ZZ"), "color")


class TestLocaleResolution(unittest.TestCase):
    def test_english_uses_the_configured_variant(self):
        self.assertEqual(resolve_locale("en", "en-GB"), "en-GB")

    def test_auto_detect_falls_back_to_the_english_preference(self):
        # Guessing the language AND the dialect is guessing twice.
        self.assertEqual(resolve_locale(None, "en-CA"), "en-CA")

    def test_other_languages_map_to_a_region(self):
        self.assertEqual(resolve_locale("fr"), "fr-FR")
        self.assertEqual(resolve_locale("ja"), "ja-JP")

    def test_bad_english_variant_falls_back(self):
        self.assertEqual(resolve_locale("en", "nonsense"), "en-US")


# ---------------------------------------------------------------------------
# Hinglish
# ---------------------------------------------------------------------------

class TestRomanize(unittest.TestCase):
    def test_common_words(self):
        for source, expected in [
            ("नमस्ते", "namaste"), ("क्या", "kya"), ("कमल", "kamal"),
            ("मुंबई", "mumbai"), ("अच्छा", "achcha"), ("दिल्ली", "dilli"),
            ("ज्ञान", "gyan"), ("क्षमा", "kshama"),
        ]:
            self.assertEqual(romanize(source), expected, source)

    def test_sentence(self):
        self.assertEqual(romanize("आप ठीक है"), "aap thik hai")

    def test_latin_text_is_untouched(self):
        self.assertEqual(romanize("hello world 123"), "hello world 123")

    def test_code_mixed_keeps_the_english_half_exactly(self):
        self.assertIn("GitHub", romanize("मैं GitHub पर हूँ"))

    def test_anusvara_before_a_labial_is_m(self):
        self.assertTrue(romanize("मुंबई").startswith("mum"))

    def test_devanagari_digits(self):
        self.assertEqual(romanize("२०२६"), "2026")


class TestTransliterationGating(unittest.TestCase):
    def test_off_by_default(self):
        pipe = make_pipeline(locale_cfg={"romanize": "never"})
        self.assertEqual(pipe.run("नमस्ते"), "नमस्ते")

    def test_always_converts(self):
        pipe = make_pipeline(locale_cfg={"romanize": "always"})
        self.assertEqual(pipe.run("नमस्ते"), "namaste")

    def test_auto_only_in_chat_or_terminal(self):
        pipe = make_pipeline(locale_cfg={"romanize": "auto"})
        plain = pipe.context(locale="hi-IN")
        chat = pipe.context(locale="hi-IN", is_chat=True)
        self.assertEqual(pipe.run("नमस्ते", ctx=plain), "नमस्ते")
        self.assertEqual(pipe.run("नमस्ते", ctx=chat), "namaste")


# ---------------------------------------------------------------------------
# Numbered lists
# ---------------------------------------------------------------------------

class TestNumberedLists(unittest.TestCase):
    def test_ordinals_become_a_list(self):
        self.assertEqual(
            numbered_lists("First, set up the repo. Second, run the tests. "
                           "Third, ship it."),
            "1. Set up the repo.\n2. Run the tests.\n3. Ship it.")

    def test_punctuated_cardinals_become_a_list(self):
        self.assertEqual(
            numbered_lists("One, clone it. Two, build it. Three, run it."),
            "1. Clone it.\n2. Build it.\n3. Run it.")

    def test_bare_cardinals_are_left_alone(self):
        # "One of the things I like" must never become "1. of the things".
        text = "One of the things I like. Two people came. Three cheers."
        self.assertEqual(numbered_lists(text), text)

    def test_two_markers_are_not_enough(self):
        text = "First, do this. Second, do that."
        self.assertEqual(numbered_lists(text), text)

    def test_must_start_at_one(self):
        text = "Second, do that. Third, do this. Fourth, done."
        self.assertEqual(numbered_lists(text), text)

    def test_plain_prose_untouched(self):
        text = "I went to the shop and bought some milk."
        self.assertEqual(numbered_lists(text), text)

    def test_suppressed_in_terminals(self):
        pipe = make_pipeline(level="medium")
        ctx = pipe.context(is_terminal=True)
        text = "First, set up. Second, run. Third, ship."
        self.assertNotIn("1.", pipe.run(text, ctx=ctx))


# ---------------------------------------------------------------------------
# Per-app rules and continuation
# ---------------------------------------------------------------------------

class TestAppRules(unittest.TestCase):
    def test_chat_drops_the_trailing_period(self):
        stage = AppRulesStage()
        self.assertEqual(stage.run("ok.", UtteranceContext(is_chat=True)), "ok")

    def test_ellipsis_is_deliberate_and_kept(self):
        stage = AppRulesStage()
        self.assertEqual(stage.run("well...", UtteranceContext(is_chat=True)),
                         "well...")

    def test_non_chat_keeps_the_period(self):
        stage = AppRulesStage()
        self.assertEqual(stage.run("ok.", UtteranceContext()), "ok.")


class TestContinuation(unittest.TestCase):
    def test_lowercases_mid_sentence(self):
        stage = ContinuationStage()
        ctx = UtteranceContext(caret_prefix="and then we ")
        self.assertEqual(stage.run("Went to the shop", ctx),
                         "went to the shop")

    def test_keeps_the_capital_after_a_full_stop(self):
        stage = ContinuationStage()
        ctx = UtteranceContext(caret_prefix="That was that. ")
        self.assertEqual(stage.run("Then we left", ctx), "Then we left")

    def test_does_nothing_without_caret_context(self):
        stage = ContinuationStage()
        self.assertFalse(stage.applies(UtteranceContext()))

    def test_never_lowercases_i_or_acronyms(self):
        stage = ContinuationStage()
        ctx = UtteranceContext(caret_prefix="and then ")
        self.assertEqual(stage.run("I left", ctx), "I left")
        self.assertEqual(stage.run("NASA called", ctx), "NASA called")


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

class TestPipelineIntegration(unittest.TestCase):
    def test_personal_rules_beat_locale_rules(self):
        pipe = make_pipeline({"replacements": {"colour": "COLOUR"}},
                             locale_cfg={"english_variant": "en-GB"})
        ctx = pipe.context(locale="en-GB")
        self.assertEqual(pipe.run("the color", ctx=ctx), "the COLOUR")

    def test_level_none_still_applies_personal_rules(self):
        pipe = make_pipeline({"replacements": {"swara": "Svara"}}, level="none")
        self.assertEqual(pipe.run("um swara"), "um Svara")

    def test_level_light_strips_fillers(self):
        self.assertEqual(make_pipeline(level="light").run("um hello"), "hello")

    def test_locale_applies_at_light(self):
        pipe = make_pipeline(locale_cfg={"english_variant": "en-GB"})
        self.assertEqual(pipe.run("the color", ctx=pipe.context(locale="en-GB")),
                         "the colour")

    def test_toggling_strip_fillers_takes_effect_live(self):
        pipe = make_pipeline()
        pipe.strip_fillers_enabled = False
        self.assertEqual(pipe.run("um hello"), "um hello")
        pipe.strip_fillers_enabled = True
        self.assertEqual(pipe.run("um hello"), "hello")

    def test_set_locale_option_takes_effect_live(self):
        pipe = make_pipeline(locale_cfg={"romanize": "never"})
        self.assertEqual(pipe.run("नमस्ते"), "नमस्ते")
        pipe.set_locale_option("romanize", "always")
        self.assertEqual(pipe.run("नमस्ते"), "namaste")


if __name__ == "__main__":
    unittest.main()
