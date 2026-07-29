"""Devanagari → Latin romanisation, for Hinglish dictation.

Hindi speakers routinely write Hindi in Latin script — "kya haal hai" rather
than "क्या हाल है" — especially in chat, code comments, and search. Whisper
transcribes Hindi speech into Devanagari, which is correct and often not what
was wanted. This stage bridges the two.

**Scope, honestly stated.** This is Hunterian-style romanisation: readable,
conventional, and lossy. It uses short vowels (ā→a), which reads naturally for
most words, and it will differ from what any individual speaker would have
typed — Hinglish has no orthography, only habits. Latin text passes through
untouched, so the English half of a code-mixed sentence is never disturbed.

**It ships off by default** (`locale.romanize: never`), and the plan that
introduced it commits to not defaulting it on without a native-speaker test
pass. A romaniser that is 90% right is a feature; one that is 90% right and
silently on is an insult.
"""

import re

from .base import BaseStage, UtteranceContext

# Consonants → their Latin base. The inherent 'a' is added by the assembler,
# not baked in here.
_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ळ": "l",
    # nukta forms (Perso-Arabic loans)
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}

# Independent vowels. Long ī/ū romanise as plain "i"/"u" to match the matra
# table — otherwise "मुंबई" (which ends in an *independent* ई) comes out
# "mumbaee" instead of "mumbai".
_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "ऍ": "e", "ऑ": "o",
}

# Dependent vowel signs (matras) — override the inherent 'a'.
_MATRA = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
}

_VIRAMA = "्"
_NUKTA = "़"
_ANUSVARA = "ं"
_CHANDRABINDU = "ँ"
_VISARGA = "ः"

_DIGITS = {"०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
           "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"}

_PUNCT = {"।": ".", "॥": ".", "॰": "."}

# Conjuncts whose conventional romanisation is not the sum of their parts.
# च्छ is here because the literal sum ("ch" + "chh") gives "achchha" for अच्छा,
# where every Hindi speaker writes "achcha".
_CONJUNCTS = {
    "क्ष": "ksh", "ज्ञ": "gy", "त्र": "tr", "श्र": "shr", "द्य": "dy",
    "द्व": "dv", "श्व": "shv", "ह्म": "hm", "ह्य": "hy", "च्छ": "chch",
}

_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
# Labial consonants: anusvara before one is an 'm', not an 'n' ("mumbai").
_LABIALS = set("पफबभम")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI_RE.search(text))


def _romanize_word(word: str) -> str:
    """One whitespace-delimited Devanagari run → Latin."""
    for conj, latin in _CONJUNCTS.items():
        word = word.replace(conj, "\x01" + latin + "\x01")

    out: list[str] = []
    i, n = 0, len(word)
    # Track where each consonant's inherent 'a' landed, so schwa deletion can
    # remove the final one.
    last_inherent: int | None = None

    while i < n:
        ch = word[i]

        if ch == "\x01":                       # pre-expanded conjunct
            i += 1
            while i < n and word[i] != "\x01":
                out.append(word[i])
                i += 1
            i += 1
            last_inherent = None
            # a conjunct still carries an inherent 'a' unless a matra follows
            if i < n and word[i] not in _MATRA and word[i] != _VIRAMA:
                out.append("a")
                last_inherent = len(out) - 1
            continue

        if ch in _CONS:
            base = _CONS[ch]
            i += 1
            if i < n and word[i] == _NUKTA:     # already folded above; skip stray
                i += 1
            out.append(base)
            last_inherent = None
            if i < n and word[i] in _MATRA:
                out.append(_MATRA[word[i]])
                i += 1
            elif i < n and word[i] == _VIRAMA:
                i += 1                          # no vowel at all
            else:
                out.append("a")                 # inherent
                last_inherent = len(out) - 1
            continue

        if ch in _VOWELS:
            out.append(_VOWELS[ch])
            last_inherent = None
            i += 1
            continue

        if ch in (_ANUSVARA, _CHANDRABINDU):
            nxt = word[i + 1] if i + 1 < n else ""
            out.append("m" if nxt in _LABIALS else "n")
            last_inherent = None
            i += 1
            continue

        if ch == _VISARGA:
            out.append("h")
            last_inherent = None
            i += 1
            continue

        if ch in _DIGITS:
            out.append(_DIGITS[ch])
            last_inherent = None
            i += 1
            continue

        if ch in _PUNCT:
            out.append(_PUNCT[ch])
            i += 1
            continue

        if ch in _MATRA:                        # stray matra — emit it
            out.append(_MATRA[ch])
            last_inherent = None
            i += 1
            continue

        out.append(ch)                          # anything else passes through
        last_inherent = None
        i += 1

    # Schwa deletion: Hindi drops the word-final inherent 'a' ("कमल" is
    # "kamal", not "kamala"). Only the final one — medial schwa deletion needs
    # morphology and gets it wrong often enough to be worse than not trying.
    if last_inherent is not None and last_inherent == len(out) - 1:
        # keep it for one-syllable words, where dropping leaves a bare consonant
        if sum(1 for c in out if c and c[0] in "aeiou") > 1:
            out.pop()

    return "".join(out)


def romanize(text: str) -> str:
    """Romanise every Devanagari run; leave everything else exactly as-is."""
    if not has_devanagari(text):
        return text
    return re.sub(r"[ऀ-ॿ]+", lambda m: _romanize_word(m.group(0)), text)


class TransliterationStage(BaseStage):
    """`locale.romanize`:

    - `never`  (default) — off
    - `auto`   — only when the focused app is a chat app or terminal, where
                 Latin script is the norm and Devanagari often renders badly
    - `always` — every dictation
    """

    name = "romanize"
    min_level = 1

    def __init__(self, mode: str = "never"):
        self.mode = str(mode or "never").lower()

    def applies(self, ctx: UtteranceContext) -> bool:
        if self.mode == "always":
            return True
        if self.mode == "auto":
            return ctx.is_chat or ctx.is_terminal
        return False

    def run(self, text: str, ctx: UtteranceContext) -> str:  # noqa: ARG002
        return romanize(text)
