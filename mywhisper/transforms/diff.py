"""Word-level diff, and a themed window to review it before committing.

A transform replaces your text with a local 3B model's opinion of your text.
Doing that blind is a bad trade: the model is fast and private, but it is also
small, and it will occasionally drop a clause you needed. Showing the change
first turns "hope it worked" into a decision.

The pure diff lives here so it can be tested without a display. The window is
built from the *active theme's own palette* — additions use `done` (the success
colour every theme already defines) and deletions use `dot` (the recording
colour, red in every theme). Hardcoded red/green would be illegible in Matrix
and Vaporwave; borrowing the theme's own semantic colours means the preview
looks native in all eight without a per-theme table.
"""

import difflib
import logging
import re

log = logging.getLogger(__name__)

EQUAL, INSERT, DELETE = "equal", "insert", "delete"

# Each token carries its own LEADING whitespace, so reassembly is exact *and*
# a run of changed words stays one span. Tokenising whitespace separately looks
# equivalent but isn't: the spaces between two rewritten words match each
# other, which chops "a b c d" → "x y z w" into four interleaved edits and
# renders as "a x b y c z d w".
_TOKEN = re.compile(r"\s*\S+|\s+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def word_diff(before: str, after: str) -> list[tuple[str, str]]:
    """[(op, text), …] with ops equal/insert/delete, in reading order.

    Adjacent runs of the same op are merged so the renderer draws one span per
    change rather than one per word.
    """
    a, b = _tokens(before), _tokens(after)
    ops: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append((EQUAL, "".join(a[i1:i2])))
        elif tag == "delete":
            ops.append((DELETE, "".join(a[i1:i2])))
        elif tag == "insert":
            ops.append((INSERT, "".join(b[j1:j2])))
        else:  # replace → delete then insert, so both sides stay visible
            ops.append((DELETE, "".join(a[i1:i2])))
            ops.append((INSERT, "".join(b[j1:j2])))

    merged: list[tuple[str, str]] = []
    for op, text in ops:
        if not text:
            continue
        if merged and merged[-1][0] == op:
            merged[-1] = (op, merged[-1][1] + text)
        else:
            merged.append((op, text))
    return merged


def summarize(before: str, after: str) -> tuple[int, int]:
    """(words added, words removed) — for the one-line "+12 −5" header."""
    added = removed = 0
    for op, text in word_diff(before, after):
        n = len(text.split())
        if op == INSERT:
            added += n
        elif op == DELETE:
            removed += n
    return added, removed


def is_trivial(before: str, after: str) -> bool:
    """Whitespace-only change — not worth interrupting the user for."""
    return " ".join((before or "").split()) == " ".join((after or "").split())
