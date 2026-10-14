"""The user's own vocabulary — replacements, snippets, spoken punctuation.

This stage runs **last**, always, and that ordering is an invariant with a test
attached (`test_pipeline.py::test_personalizer_is_always_last`). The reason:
everything upstream is a guess. Whisper guesses the word, the LLM guesses the
phrasing, the locale rules guess the convention. The user's replacement table is
not a guess — it is them telling Svara, explicitly, how their name is spelled.
A model that "helpfully" reverts it has to lose.
"""

import logging
import re

from ..redact import E_DICT_IO
from .base import BaseStage, UtteranceContext

log = logging.getLogger(__name__)

_SPACE_RE = re.compile(r"[ \t]{2,}")

# Spoken-punctuation vocabulary: (phrase, exact replacement). The replacement
# includes its own spacing — trailing marks glue left ("hello. "), opening
# marks glue right (" (") — so one pass needs no cleanup afterwards.
_SPOKEN_PUNCT = [
    ("new paragraph", "\n\n"), ("new line", "\n"),
    ("question mark", "? "), ("exclamation mark", "! "),
    ("exclamation point", "! "), ("full stop", ". "), ("period", ". "),
    ("comma", ", "), ("semicolon", "; "), ("colon", ": "),
    ("open quote", " “"), ("close quote", "” "),
    ("open paren", " ("), ("close paren", ") "), ("dash", " — "),
    ("ellipsis", "… "), ("ampersand", " & "),
    ("at sign", "@"), ("hashtag", " #"), ("percent sign", "% "),
    ("bullet point", "\n- "), ("next bullet", "\n- "),
]


class Personalizer:
    """Dictionary boosting happens at decode time (hotwords); this class is the
    text side. All matching is case-insensitive on word boundaries so "swara"
    fixes "Swara," too, but never rewrites inside another word."""

    def __init__(self, dict_cfg: dict | None):
        self.reload(dict_cfg)

    def reload(self, dict_cfg: dict | None):
        cfg = dict_cfg or {}
        self.words: list[str] = [str(w) for w in (cfg.get("words") or []) if w]
        self.spoken_punct = bool(cfg.get("spoken_punctuation", False))
        self._rules: list[tuple[re.Pattern, str]] = []
        self._snippet_rules = set()
        # snippets first: a longer spoken trigger must win over a replacement
        # that happens to match one of its words
        merged = list((cfg.get("snippets") or {}).items())
        merged += list((cfg.get("replacements") or {}).items())
        for heard, typed in sorted(merged, key=lambda kv: -len(kv[0])):
            if not heard or typed is None:
                continue
            try:
                if heard in (cfg.get("snippets") or {}):
                    self._snippet_rules.add(len(self._rules))
                self._rules.append((
                    re.compile(rf"\b{re.escape(str(heard))}\b", re.IGNORECASE),
                    str(typed)))
            except re.error:
                log.warning("%s bad dictionary rule — skipped (%d chars)",
                            E_DICT_IO, len(str(heard)))
        # Match the original input once. Expanded snippets are literal payloads,
        # never input to later replacements or spoken punctuation rules.
        self._matcher = (re.compile("|".join(f"(?P<r{i}>{pattern.pattern})"
                                           for i, (pattern, _) in enumerate(self._rules)),
                                    re.IGNORECASE) if self._rules else None)

    @property
    def requires_final_cleanup(self) -> bool:
        return bool(self._rules or self.spoken_punct)

    @property
    def hotwords(self) -> str | None:
        """Decode-time recognition boost for faster-whisper (hotwords param)."""
        return ", ".join(self.words) if self.words else None

    def apply(self, text: str) -> str:
        def punctuation(raw: str) -> str:
            if not self.spoken_punct:
                return raw
            for phrase, repl in _SPOKEN_PUNCT:
                # swallow surrounding spaces and any punctuation Whisper stuck
                # around the phrase itself: "hello, comma, world" → "hello, world"
                raw = re.sub(rf"[,.]?\s*\b{re.escape(phrase)}\b[,.]?\s*", repl,
                             raw, flags=re.IGNORECASE)
            return _SPACE_RE.sub(" ", raw)

        if self._matcher is None:
            out = punctuation(text)
            return out.strip() if self.spoken_punct else out
        whole = self._matcher.fullmatch(text.strip().rstrip(".,!?"))
        if whole and int(whole.lastgroup[1:]) in self._snippet_rules:
            return self._rules[int(whole.lastgroup[1:])][1]
        pieces, end = [], 0
        for hit in self._matcher.finditer(text):
            gap = punctuation(text[end:hit.start()])
            if end == 0 and self.spoken_punct:
                gap = gap.lstrip()
            pieces.append(gap)
            pieces.append(self._rules[int(hit.lastgroup[1:])][1])
            end = hit.end()
        tail = punctuation(text[end:])
        if self.spoken_punct:
            tail = tail.rstrip()
        pieces.append(tail)
        return "".join(pieces)


class PersonalizerStage(BaseStage):
    name = "personalizer"
    min_level = 0  # even at level "none" — these are the user's words, not cleanup

    def __init__(self, personalizer: Personalizer):
        self.personalizer = personalizer

    def run(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        return self.personalizer.apply(text)
