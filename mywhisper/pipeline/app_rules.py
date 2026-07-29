"""Rules that depend on *where* the text is about to land.

Previously stranded in `app.py` as `_strip_chat_period`, which meant the one
transformation that most obviously belonged in the cleanup pipeline was the one
transformation not in it. It runs here now, in declared order, with the same
fail-safe treatment as everything else.
"""

import re

from .base import BaseStage, UtteranceContext

_TRAILING_SPACE = re.compile(r"[ \t]+(?=\n)")


class AppRulesStage(BaseStage):
    """Per-target text rules.

    **Chat apps lose the trailing period.** In a messenger, "ok." reads as
    curt in a way "ok" does not — a real convention, and one of the details
    that makes dictated chat messages look typed rather than transcribed.
    Multiple periods (an ellipsis) are left alone: those are deliberate.

    **Terminals lose trailing whitespace before newlines**, which some shells
    and REPLs treat as significant.
    """

    name = "app_rules"
    min_level = 0

    def __init__(self, chat_no_period: bool = True):
        self.chat_no_period = chat_no_period

    def run(self, text: str, ctx: UtteranceContext) -> str:
        if ctx.is_terminal:
            text = _TRAILING_SPACE.sub("", text)
        if self.chat_no_period and ctx.is_chat:
            stripped = text.rstrip()
            if stripped.endswith(".") and not stripped.endswith(".."):
                text = stripped[:-1]
        return text


# Sentence-final punctuation, or nothing at all — either way the next word
# starts a new sentence and keeps its capital.
_ENDS_SENTENCE = re.compile(r"(?:^|[.!?:;\n]|[-—]\s*|\)\s*)\s*$")
_OPEN_QUOTE = re.compile(r"[\"'“‘(\[{]\s*$")


class ContinuationStage(BaseStage):
    """Casing that knows it's mid-sentence.

    Whisper capitalises the first word of everything it transcribes, because
    from its side every utterance is a fresh start. From the user's side it
    frequently isn't: they typed "and then we ", put the caret there, and
    dictated the rest. "And Then We went" is wrong in a way that is annoying to
    fix by hand every time.

    Needs `context.read_caret_text` (opt-in). Without a caret prefix there is
    no signal and the stage does nothing — it never guesses.

    Deliberately conservative: it only *lowercases*, only the first word, only
    when the preceding text clearly does not end a sentence, and never when the
    word is an acronym, "I", or already lowercase.
    """

    name = "continuation"
    min_level = 1

    def applies(self, ctx: UtteranceContext) -> bool:
        return bool(ctx.caret_prefix and ctx.caret_prefix.strip())

    def run(self, text: str, ctx: UtteranceContext) -> str:
        prefix = (ctx.caret_prefix or "").rstrip()
        if not prefix or _ENDS_SENTENCE.search(prefix) or _OPEN_QUOTE.search(prefix):
            return text
        lead_len = len(text) - len(text.lstrip())
        lead, rest = text[:lead_len], text[lead_len:]
        first = rest.split(" ", 1)[0] if rest else ""
        if not first or not first[:1].isupper():
            return text
        stripped = first.strip(".,!?;:\"'“”")
        # "I" and acronyms/initialisms keep their capitals.
        if stripped == "I" or stripped.isupper() or not stripped.isalpha():
            return text
        return lead + rest[:1].lower() + rest[1:]
