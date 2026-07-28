"""The cleanup pipeline.

`build_chain()` is the single place the stage order is declared. If you are
adding a text transformation, it goes in the list below and nowhere else.

Order is not arbitrary. Three constraints hold it together:

1. **Fillers and retractions first.** Everything downstream — the LLM, the
   typography rules — produces better output on text that isn't full of "um".
2. **Typography after the LLM.** The LLM rewrites punctuation; French spacing
   and CJK spacing have to see the *final* punctuation, not a draft of it.
3. **The personalizer last, always.** The user's replacement table is the one
   thing in this pipeline that isn't a guess, so nothing gets to overrule it.
   Asserted in `tests/test_pipeline.py`.
"""

from .app_rules import AppRulesStage, ContinuationStage
from .base import LEVELS, BaseStage, Chain, Stage, UtteranceContext, rank
from .lists import NumberedListStage, numbered_lists
from .llm import LlmCleanup, LlmStage
from .locale import (LocaleTypographyStage, cjk_spacing, english_variant,
                     french_spacing, resolve_locale)
from .personal import Personalizer, PersonalizerStage
from .text_rules import (BacktrackStage, FillerStage, apply_backtrack,
                         strip_fillers)
from .transliterate import TransliterationStage, romanize

__all__ = [
    "LEVELS", "BaseStage", "Chain", "CleanupPipeline", "LlmCleanup",
    "Personalizer", "Stage", "UtteranceContext", "apply_backtrack",
    "build_chain", "cjk_spacing", "english_variant", "french_spacing",
    "numbered_lists", "rank", "resolve_locale", "romanize", "strip_fillers",
]


def build_chain(cleanup_cfg: dict, dict_cfg: dict | None = None,
                locale_cfg: dict | None = None,
                context_cfg: dict | None = None,
                llm: LlmCleanup | None = None,
                personalizer: Personalizer | None = None) -> Chain:
    loc = locale_cfg or {}
    ctxc = context_cfg or {}
    return Chain([
        FillerStage(bool(cleanup_cfg.get("strip_fillers", True))),
        BacktrackStage(),
        NumberedListStage(bool(loc.get("numbered_lists", True))),
        LlmStage(llm or LlmCleanup(cleanup_cfg["llm"])),
        LocaleTypographyStage(str(loc.get("typography", "auto")) != "off"),
        TransliterationStage(loc.get("romanize", "never")),
        AppRulesStage(bool(ctxc.get("chat_no_period", True))),
        ContinuationStage(),
        PersonalizerStage(personalizer or Personalizer(dict_cfg)),
    ])


class CleanupPipeline:
    """Cleanup intensity is one dial (`none`/`light`/`medium`/`high`), not
    scattered toggles. The dial filters the chain by each stage's `min_level`:

    none   → verbatim (the personal dictionary still applies — those are the
             user's own words, not "cleanup")
    light  → + fillers, locale typography
    medium → + retractions, numbered lists
    high   → + LLM rewrite when a local server is reachable (else = medium)

    The legacy `strip_fillers` / `llm.enabled` keys keep their override
    semantics so configs written before the refactor behave identically.
    """

    def __init__(self, cleanup_cfg: dict, dict_cfg: dict | None = None,
                 locale_cfg: dict | None = None, context_cfg: dict | None = None):
        self.level = str(cleanup_cfg.get("level", "light")).lower()
        if self.level not in LEVELS:
            self.level = "light"
        self.strip_fillers_enabled = bool(cleanup_cfg.get("strip_fillers", True))
        self.llm = LlmCleanup(cleanup_cfg["llm"])
        self.personalizer = Personalizer(dict_cfg)
        self._locale_cfg = dict(locale_cfg or {})
        self.chain = build_chain(cleanup_cfg, dict_cfg, self._locale_cfg,
                                 context_cfg, llm=self.llm,
                                 personalizer=self.personalizer)

    # -- live reconfiguration (tray toggles, dictionary reload) --------------

    def set_level(self, level: str):
        if level in LEVELS:
            self.level = level

    @property
    def strip_fillers_enabled(self) -> bool:
        return self._strip_fillers

    @strip_fillers_enabled.setter
    def strip_fillers_enabled(self, value: bool):
        self._strip_fillers = bool(value)
        chain = getattr(self, "chain", None)
        if chain is not None:
            stage = chain.get("fillers")
            if stage is not None:
                stage.enabled = self._strip_fillers

    def set_locale_option(self, key: str, value):
        """Live update for `locale.*` without rebuilding the whole chain (which
        would drop the personalizer's compiled rules)."""
        self._locale_cfg[key] = value
        if key == "romanize":
            stage = self.chain.get("romanize")
            if stage is not None:
                stage.mode = str(value or "never").lower()
        elif key == "typography":
            stage = self.chain.get("locale")
            if stage is not None:
                stage.enabled = str(value) != "off"

    # -- running -------------------------------------------------------------

    def context(self, **kw) -> UtteranceContext:
        """Build a context carrying the current level. Callers override the
        fields they know (app, locale, is_terminal…)."""
        kw.setdefault("level", self.level)
        return UtteranceContext(**kw)

    def run(self, text: str, style_hint: str | None = None,
            ctx: UtteranceContext | None = None) -> str:
        if ctx is None:
            ctx = self.context(style_hint=style_hint,
                               locale=self._locale_cfg.get("english_variant",
                                                           "en-US"))
        elif style_hint and not ctx.style_hint:
            from dataclasses import replace
            ctx = replace(ctx, style_hint=style_hint)
        if ctx.level != self.level:
            ctx = ctx.with_level(self.level)
        return self.chain.run(text, ctx)
