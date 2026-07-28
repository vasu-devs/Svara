"""The cleanup pipeline's spine: a context object, a stage contract, a chain.

Before this, cleanup was a fixed ladder of `if rank >= N` inside one method.
That worked for three transformations. It does not work for ten, because the
ordering constraints stop being obvious — "personal replacements must run after
the LLM" and "French spacing must run after punctuation exists but before the
user's literal fixes" are real invariants that deserve to be tested, not
remembered.

So: every transformation is a `Stage`. The chain declares the order once, in
one list, and each stage is a pure function of (text, context) that can be unit
tested without a microphone, a model, or an LLM.

Two properties the chain guarantees, both of which matter more than they look:

**A stage can never destroy an utterance.** If `run()` raises, the chain logs a
stable error code and carries the *previous* text forward. A regex bug in
Hinglish transliteration must not cost someone the paragraph they just spoke.

**A stage can never silently empty an utterance.** If a stage returns empty for
non-empty input, the chain treats that as a bug and keeps the input. Losing
words is the worst failure this app has; it fails closed.
"""

import logging
from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable

from ..redact import E_PIPE_STAGE, shape

log = logging.getLogger(__name__)

LEVELS = ("none", "light", "medium", "high")


def rank(level: str) -> int:
    """Cleanup level → integer, for `min_level` comparisons. Unknown levels
    read as 'light' — the historical default."""
    try:
        return LEVELS.index(level)
    except ValueError:
        return 1


@dataclass(frozen=True)
class UtteranceContext:
    """Everything the pipeline knows about one dictation.

    This is the value object that used to be smeared across `MyWhisperApp`
    instance attributes (`_active_app`, `_active_title`, `_voice_rms`) and
    ad-hoc keyword arguments. Frozen on purpose: a stage that wants to change
    the context is a stage doing something surprising.
    """

    app: str = ""                      # focused exe, lowercase ("slack.exe")
    title: str = ""                    # its window title
    locale: str = "en-US"              # BCP-47-ish; drives typography rules
    style_hint: str | None = None      # per-app tone, fed to the LLM stage
    is_terminal: bool = False          # shell/REPL — suppress invisible chars
    is_chat: bool = False              # messenger — drop the trailing period
    is_elevated: bool = False          # target runs as admin and we don't
    caret_prefix: str | None = None    # text immediately before the caret
    duration_s: float = 0.0
    level: str = "light"               # cleanup level in effect for this run
    source: str = "dictation"          # dictation | command | recovery | scratchpad
    meta: dict = field(default_factory=dict)  # stage-to-stage scratch space

    def with_level(self, level: str) -> "UtteranceContext":
        return replace(self, level=level)


@runtime_checkable
class Stage(Protocol):
    """One text transformation.

    `name` shows up in logs and in the stage-order test, so it is part of the
    contract, not decoration.
    """

    name: str
    min_level: int

    def applies(self, ctx: UtteranceContext) -> bool: ...

    def run(self, text: str, ctx: UtteranceContext) -> str: ...


class BaseStage:
    """Convenience base — most stages only need `run()`."""

    name: str = "unnamed"
    min_level: int = 0        # 0=none 1=light 2=medium 3=high

    def applies(self, ctx: UtteranceContext) -> bool:  # noqa: ARG002
        return True

    def run(self, text: str, ctx: UtteranceContext) -> str:
        raise NotImplementedError


class Chain:
    """Runs stages in declared order, defensively.

    Stages are held in a list rather than resolved dynamically so the order is
    inspectable (`chain.order`) and assertable in tests — the ordering
    invariants are the whole point of having a chain at all.
    """

    def __init__(self, stages: list[Stage]):
        self.stages = list(stages)

    @property
    def order(self) -> list[str]:
        return [s.name for s in self.stages]

    def replace_stage(self, name: str, stage: Stage) -> bool:
        """Swap a stage in place, preserving position. Used by live config
        reloads (dictionary edits, locale changes) so the order never shifts
        under the user."""
        for i, existing in enumerate(self.stages):
            if existing.name == name:
                self.stages[i] = stage
                return True
        return False

    def get(self, name: str) -> Stage | None:
        for s in self.stages:
            if s.name == name:
                return s
        return None

    def run(self, text: str, ctx: UtteranceContext) -> str:
        if not text:
            return text
        level = rank(ctx.level)
        for stage in self.stages:
            if level < stage.min_level:
                continue
            try:
                if not stage.applies(ctx):
                    continue
                out = stage.run(text, ctx)
            except Exception:  # noqa: BLE001 — one bad stage must not cost the utterance
                log.error("%s stage %r failed — keeping text as-is (%s)",
                          E_PIPE_STAGE, stage.name, shape(text), exc_info=True)
                continue
            if out is None:
                continue
            if text.strip() and not out.strip():
                # A stage that empties a non-empty utterance is a bug, and the
                # user pays for it in lost words. Refuse the result.
                log.error("%s stage %r emptied the text — refusing (%s)",
                          E_PIPE_STAGE, stage.name, shape(text))
                continue
            text = out
        return text
