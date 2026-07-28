"""Cheap rules-based cleanup: fillers and spoken retractions.

No model, no latency, no network. These run first because everything after them
(the LLM, typography, the user's own replacements) works better on text that
isn't full of "um".
"""

import re

from .base import BaseStage, UtteranceContext

_FILLER_RE = re.compile(r"\b(?:um+|uh+|uhm+|erm+|hmm+|mmm+)\b[,.]?\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def strip_fillers(text: str) -> str:
    out = _FILLER_RE.sub("", text)
    out = _SPACE_RE.sub(" ", out)
    out = _SPACE_PUNCT_RE.sub(r"\1", out)
    return out.strip()


# Backtrack: "send the email... scratch that, delete it" → "delete it".
# Deliberately limited to explicit retraction phrases — resolving "at 2,
# actually 3" correctly needs a language model, and a rule that guesses wrong
# silently destroys words the user said on purpose.
_BACKTRACK_RE = re.compile(
    r"[^.!?\n]*?\b(?:scratch|strike|forget) that\b[,.!?]?\s*", re.IGNORECASE)


def apply_backtrack(text: str) -> str:
    out = _BACKTRACK_RE.sub("", text)
    return out.strip() if out.strip() else text  # never erase everything


class FillerStage(BaseStage):
    name = "fillers"
    min_level = 1  # light

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def applies(self, ctx: UtteranceContext) -> bool:  # noqa: ARG002
        return self.enabled

    def run(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        return strip_fillers(text)


class BacktrackStage(BaseStage):
    name = "backtrack"
    min_level = 2  # medium

    def run(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        return apply_backtrack(text)
