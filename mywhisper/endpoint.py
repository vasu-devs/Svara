"""Knowing when you've *finished*, not just when you've gone quiet.

Silero VAD answers "is this speech?". It cannot answer "are they done?" — and
that is the question hands-free dictation actually needs. Which is why
`auto_stop` ships off: a fixed silence timer cuts people off mid-thought, and
being cut off mid-thought is worse than tapping the key yourself.

The gap is that pauses mean different things. "Send it to the team and…" followed
by 900 ms of silence is someone thinking. "Send it to the team." followed by the
same 900 ms is someone finished. The audio is identical; the *text* is not.

So: when the silence timer fires, look at what was said. If it ends mid-clause,
extend the window and keep listening. If it looks complete, stop. There is
always a hard ceiling (`max_silence_ms`) so an unfinished sentence cannot hold
the recording open forever.

Rules-based, no model, no latency — which also means no new failure mode on the
hot path. `cleanup.llm` can refine it later; it does not need to.
"""

import logging
import re

log = logging.getLogger(__name__)

# Words that cannot end a sentence. Someone who stops after "and" has not
# stopped — they are choosing the next word.
_DANGLING = {
    # conjunctions
    "and", "but", "or", "nor", "so", "yet", "because", "although", "though",
    "while", "whereas", "unless", "until", "since", "whether", "if", "when",
    "before", "after", "once", "than", "that", "which", "who", "whom", "whose",
    # prepositions
    "to", "of", "in", "on", "at", "by", "for", "with", "from", "into", "onto",
    "about", "over", "under", "between", "through", "during", "against",
    "toward", "towards", "upon", "within", "without", "across", "behind",
    # determiners / articles / quantifiers
    "the", "a", "an", "this", "that", "these", "those", "some", "any", "every",
    "each", "my", "your", "our", "their", "his", "her", "its",
    # auxiliaries and common sentence-openers left hanging
    "is", "are", "was", "were", "be", "been", "being", "am", "will", "would",
    "can", "could", "should", "shall", "may", "might", "must", "do", "does",
    "did", "have", "has", "had", "let", "going", "want", "need", "trying",
    # spoken hesitation
    "um", "uh", "erm", "like", "well", "so",
}

_TERMINAL = re.compile(r"[.!?…。！？]['\"”’)\]]*\s*$")
_WORD = re.compile(r"[\w'’-]+")


def looks_complete(text: str) -> bool:
    """Whether the text reads like a finished thought.

    Deliberately asymmetric. Saying "complete" too early cuts someone off;
    saying "incomplete" too often just means the hard ceiling stops them a
    moment later. So the bar for *complete* is the higher one.
    """
    text = (text or "").strip()
    if not text:
        return False
    words = _WORD.findall(text.lower())
    if not words:
        # Punctuation with no words ("…", "?") is a decoder artifact, not a
        # finished thought. Checking the punctuation first would call it one.
        return False
    if _TERMINAL.search(text):
        return True
    if words[-1] in _DANGLING:
        return False
    # A comma or a dash at the end is an explicit "there's more coming".
    if text.rstrip().endswith((",", ";", ":", "-", "—", "–")):
        return False
    # Two words is not a sentence; it is a false start or a stray word the VAD
    # picked up. Give it longer.
    return len(words) >= 3


def should_finish(text: str, silence_ms: float, silence_threshold_ms: float,
                  max_silence_ms: float = 0.0, semantic: bool = False) -> bool:
    """Should auto-stop fire now?

    Without `semantic`, this is the pre-0.5 behaviour exactly: stop as soon as
    the silence threshold is crossed.
    """
    if silence_ms < silence_threshold_ms:
        return False
    if not semantic:
        return True
    if max_silence_ms and silence_ms >= max_silence_ms:
        # The ceiling always wins. An unfinished sentence must not be able to
        # hold the recording open indefinitely.
        return True
    return looks_complete(text)
