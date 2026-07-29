"""Spoken enumerations → numbered lists.

"first, set up the repo. second, run the tests. third, ship it." is dictated
prose that the speaker meant as a list. Turning it into `1. … 2. … 3. …` is one
of those small things that makes dictated text look written rather than
transcribed.

It is also the easiest thing in this whole pipeline to get wrong. "One of the
things I like" must never become "1. of the things I like". So the detector is
deliberately paranoid, and every guard below exists because its absence
produces a specific, embarrassing false positive:

- **≥3 markers.** Two is a coincidence ("first… second thoughts").
- **Consecutive and ascending from 1.** A stray "third" alone proves nothing.
- **Clause-initial only.** The marker has to start a sentence or follow a hard
  break, not appear mid-phrase.
- **Ordinals are safe; bare cardinals are not.** "first/second/third" is
  unambiguous. "one/two/three" is not, so bare cardinals additionally require
  a following comma or pause-marker — "One, set up the repo."
- **Level ≥ medium.** At `light`, Svara stays literal.
"""

import re

from .base import BaseStage, UtteranceContext

_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth",
             "seventh", "eighth", "ninth", "tenth"]
_CARDINALS = ["one", "two", "three", "four", "five", "six",
              "seven", "eight", "nine", "ten"]

# Sentence-ish split that keeps the delimiter, so re-assembly is lossless.
_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def _marker_index(clause: str) -> tuple[int, int] | None:
    """(1-based list position, chars consumed) if this clause opens with an
    enumeration marker, else None."""
    s = clause.lstrip()
    low = s.lower()
    for i, word in enumerate(_ORDINALS):
        m = re.match(rf"{word}(?:ly)?\b[,:]?\s+", low)
        if m:
            return i + 1, len(clause) - len(s) + m.end()
    for i, word in enumerate(_CARDINALS):
        # bare cardinals need explicit punctuation to count as a marker
        m = re.match(rf"{word}\b[,:]\s+", low)
        if m:
            return i + 1, len(clause) - len(s) + m.end()
    return None


def numbered_lists(text: str) -> str:
    clauses = _SPLIT.split(text)
    if len(clauses) < 3:
        return text

    marks: list[tuple[int, int, int]] = []      # (clause idx, position, consumed)
    for idx, clause in enumerate(clauses):
        hit = _marker_index(clause)
        if hit:
            marks.append((idx, hit[0], hit[1]))

    # Find the longest run that is consecutive in clause order AND ascends 1,2,3…
    best: list[tuple[int, int, int]] = []
    run: list[tuple[int, int, int]] = []
    for mark in marks:
        if run and mark[0] == run[-1][0] + 1 and mark[1] == run[-1][1] + 1:
            run.append(mark)
        else:
            run = [mark] if mark[1] == 1 else []
        if len(run) > len(best):
            best = list(run)

    if len(best) < 3:
        return text

    out = list(clauses)
    for idx, position, consumed in best:
        clause = clauses[idx]
        lead = clause[:len(clause) - len(clause.lstrip())]
        body = clause[consumed:].lstrip()
        body = body[:1].upper() + body[1:] if body else body
        out[idx] = f"{lead}{position}. {body}"

    # Rebuild with newlines between list items so the numbering is visible.
    rebuilt = []
    list_idx = {m[0] for m in best}
    for i, clause in enumerate(out):
        if i in list_idx and i != best[0][0]:
            rebuilt.append("\n" + clause)
        else:
            rebuilt.append(clause)
    joined = " ".join(rebuilt)
    return re.sub(r" *\n *", "\n", joined)


class NumberedListStage(BaseStage):
    name = "numbered_lists"
    min_level = 2  # medium

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def applies(self, ctx: UtteranceContext) -> bool:
        # A shell prompt does not want "1. " prefixes appearing in a command.
        return self.enabled and not ctx.is_terminal

    def run(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        return numbered_lists(text)
