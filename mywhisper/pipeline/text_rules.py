"""Cheap rules-based cleanup: fillers and spoken retractions.

No model, no latency, no network. These run first because everything after them
(the LLM, typography, the user's own replacements) works better on text that
isn't full of "um".
"""

import re

from .base import BaseStage, UtteranceContext
from .corrections import outside_literals

_FILLER_RE = re.compile(
    r"\b(?:u+m+|u+h+|u+h+m+|e+r+m+|h+m{2,}|m{3,}|a+h{2,}|a{2,}h+)\b[,.!?]*[ \t]*",
    re.IGNORECASE)
# Keep meaningful repetition such as "had had", "that that" and "very very".
_SUBJECT_STUTTER = re.compile(r"\b(I|we|you|he|she|they)(?:[ ,\t-]+\1\b)+", re.I)
_FRAGMENT_STUTTER = re.compile(r"\b([a-z]{1,3})-(?:\1-)+(\1[a-z]+)\b", re.I)
_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def strip_fillers(text: str) -> str:
    def clean(part):
        out = _FILLER_RE.sub("", part)
        out = _SUBJECT_STUTTER.sub(r"\1", out)
        out = _FRAGMENT_STUTTER.sub(r"\2", out)
        out = _SPACE_RE.sub(" ", out)
        return _SPACE_PUNCT_RE.sub(r"\1", out)
    return outside_literals(text, clean).strip()


# Backtrack: "send the email... scratch that, delete it" → "delete it".
# Whole-clause retraction is separate from the conservative slot repairs in
# corrections.py; broader rewrites remain the local language model's job.
_BACKTRACK_RE = re.compile(
    r"[^.!?\n]*?\b(?:scratch|strike|forget) that\b[,.!?]?\s*", re.IGNORECASE)


def apply_backtrack(text: str) -> str:
    out = outside_literals(text, lambda part: _BACKTRACK_RE.sub("", part))
    return out.strip() if out.strip() else text  # never erase everything


class FillerStage(BaseStage):
    name = "fillers"
    min_level = 1  # light
    allow_empty = True  # filler-only speech should insert nothing

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
