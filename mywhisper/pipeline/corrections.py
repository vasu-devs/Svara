"""Conservative English repairs for explicit spoken self-corrections.

These rules resolve local replacements, not arbitrary intent. An unmatched repair
stays intact for the optional local LLM. Never search or edit the target document.
"""

import re

from .base import BaseStage, UtteranceContext

# Treat quotations, code and addresses as literal content, including quoted fillers.
_LITERAL = re.compile(
    r'```[\s\S]*?```|`[^`\n]*`|"[^"\n]*"|“[^”\n]*”|'
    r"(?<!\w)'[^'\n]*'(?!\w)|https?://\S+|\b[\w.+-]+@[\w.-]+\.[\w-]+")
_WORD = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)
_MARKER = re.compile(
    r"\b(?:no(?:[ \t,]+no)+|no|I mean|sorry|actually|rather)\b[ \t,;:—–-]*",
    re.IGNORECASE)
_PREP = re.compile(r"^(?:at|on|in|to|from|for|with)\s+", re.IGNORECASE)
_NUMBER_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
                r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
                r"eighty|ninety|hundred|thousand|million)")
_NUMBER = re.compile(
    rf"(?:[$£€]\s*)?(?:\d+(?:[.:,]\d+)*|{_NUMBER_WORD}(?:[ -]{_NUMBER_WORD})*)"
    r"(?P<unit>\s*(?:a\.?m\.?|p\.?m\.?|percent|%|dollars?|pounds?|euros?|"
    r"minutes?|hours?|seconds?|days?|weeks?))?(?!\w)", re.IGNORECASE)
_KINDS = {
    "day": re.compile(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|"
                      r"today|tomorrow|yesterday)\b", re.IGNORECASE),
    "month": re.compile(r"(?:January|February|March|April|May|June|July|August|"
                        r"September|October|November|December)\b", re.IGNORECASE),
    "color": re.compile(r"(?:red|blue|green|yellow|orange|purple|black|white|"
                        r"grey|gray|pink|brown)\b", re.IGNORECASE),
    "number": _NUMBER,
}
_AUXILIARIES = {"can't": "can", "cannot": "can", "won't": "will",
                "don't": "do", "doesn't": "does", "didn't": "did",
                "isn't": "is", "aren't": "are", "wasn't": "was",
                "weren't": "were", "couldn't": "could", "shouldn't": "should",
                "wouldn't": "would", "haven't": "have", "hasn't": "has"}


def _anchor_word(word: str) -> str:
    word = word.casefold().replace("’", "'")
    return _AUXILIARIES.get(word, word)


def outside_literals(text: str, transform) -> str:
    """Keep protected spans byte-for-byte; never align repairs across them."""
    pieces, end = [], 0
    for match in _LITERAL.finditer(text):
        pieces.extend((transform(text[end:match.start()]), match.group()))
        end = match.end()
    pieces.append(transform(text[end:]))
    return "".join(pieces)


def _replace(left: str, right: str, marker: str) -> str | None:
    # Restrict the search to the current clause (Whisper may end it with a period
    # just before "no"). Earlier sentences and paragraph boundaries stay intact.
    clean_left = left.rstrip(" ,;:.!?—–-\t")
    boundaries = list(re.finditer(r"[!?\n]|\.(?=\s|$)", clean_left))
    boundary = boundaries[-1].end() if boundaries else 0
    clause = clean_left[boundary:]
    words = list(_WORD.finditer(clause))
    new_words = list(_WORD.finditer(right))
    if not words or not new_words or len(clause) > 600:
        return None
    if "\n" in left[len(clean_left):] or right.startswith("\n"):
        return None
    if (marker.casefold() == "no" and not left.rstrip().endswith((",", ";", ".", "—", "–"))
            and _PREP.match(right) is None):
        return None  # ordinary negation without an explicit repair cue

    # A restarted phrase: "I want the blue one, no, I want the red one".
    # Require two shared words, so ordinary discourse "actually I think..."
    # cannot delete the previous clause on the strength of one pronoun.
    for index in range(len(words)):
        shared = 0
        for old, new in zip(words[index:], new_words):
            if _anchor_word(old.group()) != _anchor_word(new.group()):
                break
            shared += 1
        if shared >= 2:
            return clean_left[:boundary + words[index].start()] + right

    prep = _PREP.match(right)
    value_start = prep.end() if prep else 0
    value = right[value_start:]
    for kind, pattern in _KINDS.items():
        new = pattern.match(value)
        if new is None:
            continue
        if re.match(r"\s+(?:is|was|were|are|has|had|would|could|should)\b", value[new.end():], re.I):
            continue  # e.g. "red, no blue was available" is an explanation
        old_candidates = [m for m in pattern.finditer(clause)
                          if (m.start() == 0 or not clause[m.start() - 1].isalnum())
                          and not clause[m.end():].strip()]
        if not old_candidates:
            continue
        old = old_candidates[-1]
        prefix = clean_left[:boundary + old.start()]
        if prep and not prefix.casefold().endswith(prep.group().casefold()):
            continue  # "on Monday, no, at four" is not the same slot
        replacement = new.group()
        if kind == "number" and not new.group("unit"):
            if old.group("unit"):
                replacement += old.group("unit")  # "five pm, no four" → four pm
            if old.group()[0] in "$£€" and replacement[0] not in "$£€":
                replacement = old.group()[0] + replacement
        return prefix + replacement + value[new.end():]

    # Explicit repeated preposition supports names/places without guessing a
    # bare noun's meaning: "send it to Alice, no no, to Bob".
    if prep and marker.casefold() not in {"actually", "rather"}:
        anchor = list(re.finditer(r"\b" + re.escape(prep.group()), clause, re.I))
        if anchor:
            pos = anchor[-1].start()
            old_tail = clause[anchor[-1].end():].split()
            if (1 <= len(old_tail) <= 3 and len(new_words) >= 2
                    and new_words[1].group().casefold() not in
                    {"not", "no", "be", "do", "have", "i", "we", "you", "they"}):
                return clean_left[:boundary + pos] + right

    # Bare proper-name repairs need an explicit marker and two capitalized
    # names. A lowercase unknown word is left for the semantic model.
    old, new = words[-1], new_words[0]
    if (marker.casefold() in {"i mean", "sorry"}
            and old.group()[0].isupper() and new.group()[0].isupper()
            and new.group().casefold() not in {"i", "we", "you", "it", "that", "this"}
            and not clause[old.end():].strip()):
        return clean_left[:boundary + old.start()] + right
    return None


def _repair(text: str) -> str:
    # Consume each marker at most once; successful repairs may expose a later
    # repair ("at five, no four, actually three"). No unbounded rewrite loop.
    cursor = 0
    while match := _MARKER.search(text, cursor):
        left, right = text[:match.start()], text[match.end():]
        marker = match.group().rstrip(" ,;:—–-\t\n")
        repaired = _replace(left, right, marker) if right.strip() else None
        if repaired is None:
            cursor = match.end()
        else:
            cursor = max(0, len(repaired) - len(right))
            text = repaired
    return text


def resolve_corrections(text: str) -> str:
    return outside_literals(text, _repair).strip()


class CorrectionStage(BaseStage):
    name = "self_corrections"
    min_level = 1

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def applies(self, ctx: UtteranceContext) -> bool:
        return self.enabled and ctx.source != "command"

    def run(self, text: str, ctx: UtteranceContext) -> str:
        return resolve_corrections(text)
