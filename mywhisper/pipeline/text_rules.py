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


# Spoken editing commands, applied to a word list so the live screen and the
# finalizer erase exactly the same words: "remove the last five words",
# "delete the last sentence", "scrap that". Deterministic, instant; the LLM
# is told the same rule for looser phrasings.
_NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_EDIT_CMD_RE = re.compile(
    r"\b(?:remove|delete|erase|scrap|scratch|cut|drop)\s+(?:the\s+|that\s+|this\s+)?"
    r"(?:last\s+|previous\s+)?(?:(?P<n>\d+|[a-z]+)\s+)?"
    r"(?P<unit>words?|sentences?|lines?|part|bit)\b", re.IGNORECASE)
_SCRAP_RE = re.compile(r"\b(?:scratch|strike|forget|scrap)\s+that\b", re.IGNORECASE)


def _word_clean(w: str) -> str:
    return re.sub(r"[^\w']+", "", w).lower()


def has_edit_command(words: list[str]) -> bool:
    text = " ".join(words)
    return bool(_EDIT_CMD_RE.search(text) or _SCRAP_RE.search(text))


def apply_edit_commands(words: list[str]) -> list[str]:
    """Return `words` with every spoken edit command applied and removed."""
    out = list(words)
    while True:
        text = " ".join(out)
        m = _EDIT_CMD_RE.search(text) or _SCRAP_RE.search(text)
        if not m:
            return out
        # which word index does the match start at?
        start_word = len(text[:m.start()].split())
        end_word = start_word + len(text[m.start():m.end()].split())
        if m.re is _SCRAP_RE or m.group("unit").lower() in ("sentence", "sentences", "line", "lines", "part", "bit"):
            # back to the previous sentence end
            a = start_word
            while a > 0 and not re.search(r"[.!?]$", out[a - 1]):
                a -= 1
        else:
            n = m.group("n")
            count = (int(n) if n and n.isdigit() else _NUMBER_WORDS.get((n or "").lower(), 1))
            a = max(0, start_word - count)
        out = out[:a] + out[end_word:]


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
