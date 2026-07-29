"""The live-streaming commit state machine, with no audio, threads or Win32 in it.

Deciding *when a word is safe to type* is the hardest logic in Svara, and until
now it lived inline in `app.py`'s streamer loop — untestable without a
microphone and a model, and impossible for the benchmark to model without
reimplementing it (which it did, subtly wrong: it never trimmed, so it reported
worse partial latency than the app actually has).

Both problems have the same fix. The policy lives here as a pure function of
(hypothesis, previous hypothesis, committed words); `app.py` drives it with real
audio and `bench.py` drives it with recorded segments, so a measurement can no
longer disagree with the thing it measures.

## The problem

Whisper re-transcribes a growing buffer every ~200 ms and each pass may revise
what the last one said. Type every hypothesis and the user watches words flicker
and rewrite themselves. Wait for the end and it isn't streaming.

**LocalAgreement-2**: a word is safe once two consecutive passes agree on it.
Everything up to the first disagreement is stable; hold back the last stable
word anyway, because it is the one most likely to change when the next syllable
arrives. When a hypothesis stops changing entirely (the speaker paused) the
held-back word is released too.

## Why trimming matters more than it looks

Committed words are already on screen, so re-decoding their audio every pass is
pure waste — and the waste grows with utterance length until a pass costs more
than the interval between passes. So audio whose words are all committed is
dropped from the front of the window at segment (silence) boundaries, and pass
time stays roughly flat however long you talk.

`max_window_s` is the backstop for speech with no pauses to trim at: once the
window exceeds it, the guard that protects the most recent segment relaxes so
trimming can catch up. Closed segments (`segs[:-1]`) are never the active one,
so this stays safe.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

DEFAULT_GUARD_S = 0.5
TIGHT_GUARD_S = 0.2       # used once the window is over max_window_s


# ---------------------------------------------------------------------------
# Commit policies
# ---------------------------------------------------------------------------

@runtime_checkable
class CommitPolicy(Protocol):
    name: str

    def stable_prefix(self, words: list[str], last_words: list[str]) -> int:
        """How many leading words of `words` are safe to type."""
        ...


def _agreement(words: list[str], last_words: list[str]) -> int:
    n = 0
    for a, b in zip(words, last_words):
        if a != b:
            break
        n += 1
    return n


class LocalAgreementPolicy:
    """Two consecutive passes must agree, then hold back `hold_back` words.

    `hold_back=1` is the shipped default and the conservative choice: the final
    agreed word is the one still being spoken, and revising a word already on
    screen is worse than showing it 200 ms later.
    """

    name = "local_agreement"

    def __init__(self, hold_back: int = 1):
        self.hold_back = max(0, int(hold_back))

    def stable_prefix(self, words: list[str], last_words: list[str]) -> int:
        if words and words == last_words:
            # Settled — the speaker paused. Release everything, including the
            # word we would normally hold.
            return len(words)
        return max(_agreement(words, last_words) - self.hold_back, 0)


class AdaptiveAgreementPolicy(LocalAgreementPolicy):
    """Holds back less once the decoder has proved itself on this utterance.

    The fixed one-word hold-back costs a word of latency on every pass forever.
    But a long unbroken agreement run is evidence the hypothesis has settled —
    after `confident_after` consecutive agreeing words, the tail is stable
    enough to release immediately.

    Strictly an experiment until the benchmark says otherwise; `streaming.commit
    _policy` selects it.
    """

    name = "adaptive"

    def __init__(self, hold_back: int = 1, confident_after: int = 12):
        super().__init__(hold_back)
        self.confident_after = max(1, int(confident_after))

    def stable_prefix(self, words: list[str], last_words: list[str]) -> int:
        if words and words == last_words:
            return len(words)
        agree = _agreement(words, last_words)
        hold = 0 if agree >= self.confident_after else self.hold_back
        return max(agree - hold, 0)


POLICIES = {
    "local_agreement": LocalAgreementPolicy,
    "adaptive": AdaptiveAgreementPolicy,
}


def make_policy(name: str, **kw) -> CommitPolicy:
    cls = POLICIES.get(str(name or "local_agreement").lower())
    if cls is None:
        log.warning("unknown streaming.commit_policy %r — using local_agreement "
                    "(known: %s)", name, ", ".join(POLICIES))
        cls = LocalAgreementPolicy
    if cls is LocalAgreementPolicy:
        kw.pop("confident_after", None)
    return cls(**kw)


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------

def plan_trim(segs, committed_count: int, window_dur_s: float,
              max_window_s: float = 0.0) -> tuple[int, float]:
    """(words_dropped, seconds_to_trim) for a window whose prefix is committed.

    Only whole segments, only ones whose words are *all* committed, and never
    the last segment in the list — that one is still being spoken.
    """
    guard = DEFAULT_GUARD_S
    if max_window_s and window_dur_s > max_window_s:
        guard = TIGHT_GUARD_S
    cum, trim_sec = 0, 0.0
    for text, _start, end in segs[:-1]:
        count = len(text.split())
        if cum + count <= committed_count and end < window_dur_s - guard:
            cum += count
            trim_sec = end
        else:
            break
    return cum, trim_sec


# ---------------------------------------------------------------------------
# The stream / tail boundary
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w']+", re.UNICODE)


def _norm(word: str) -> str:
    """Compare words the way a reader would: ignoring case and the punctuation
    Whisper attaches or drops between passes ("to" vs "to,")."""
    return _PUNCT.sub("", (word or "").lower())


def align_remainder(committed: list[str], words: list[str]) -> list[str]:
    """Which of the final pass's words have NOT been typed yet.

    The finalising worker re-decodes the same trimmed window the streamer used,
    so its hypothesis should begin with exactly the words already on screen —
    and `words[len(committed):]` would be the remainder. In practice the final
    pass runs with a different beam and no VAD truncation, so it occasionally
    tokenises the boundary differently: one extra "to", one merged contraction.
    Slicing by count then lands mid-repeat and the user gets
    "push the code to to get hub", or loses a word.

    So match by content instead of by position:

    1. Longest common prefix, punctuation- and case-insensitive. Covers the
       normal case, including a boundary word that gained a comma.
    2. Failing that, find the largest overlap between the tail of what was typed
       and the head of the new hypothesis, and continue after it. This is the
       repeat case — it is what removes the duplicate.
    3. If neither matches, fall back to the old count-based slice. Some
       remainder is better than none.
    """
    if not committed:
        return list(words)
    if not words:
        return []

    limit = min(len(committed), len(words))
    lcp = 0
    while lcp < limit and _norm(committed[lcp]) == _norm(words[lcp]):
        lcp += 1
    if lcp == len(committed):
        return _drop_seam_repeat(committed, list(words[lcp:]))

    norm_committed = [_norm(w) for w in committed]
    norm_words = [_norm(w) for w in words]
    for k in range(limit, 0, -1):
        if norm_committed[-k:] == norm_words[:k]:
            return _drop_seam_repeat(committed, list(words[k:]))

    if lcp:
        return _drop_seam_repeat(committed, list(words[lcp:]))
    return _drop_seam_repeat(committed, list(words[len(committed):]))


def _drop_seam_repeat(committed: list[str], remainder: list[str]) -> list[str]:
    """Drop a remainder that starts by repeating the last word already typed.

    Alignment cannot fix this one, because nothing is misaligned: the final
    pass genuinely decodes the boundary word twice. faster-whisper runs a
    different beam over a window whose end moved, and around a word straddling
    that edge it will sometimes emit it once for the streamer and again for the
    finaliser. The user sees "push the code to to get hub".

    Only the exact seam is considered - the last committed word against the
    first remaining one - so a real doubled word further along is untouched.
    English does have "had had" and "that that", but they are rare, and they
    are rarer still landing precisely on a decode boundary; a dropped duplicate
    is a far smaller error than a visible stutter in every long dictation.
    """
    if committed and remainder and _norm(committed[-1]) == _norm(remainder[0]):
        return remainder[1:]
    return remainder


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """What one streaming pass concluded."""

    words: list[str] = field(default_factory=list)
    commit_from: int = 0          # index into `words` of the first new word
    commit_to: int = 0            # exclusive end
    trimmed_words: int = 0
    trimmed_samples: int = 0

    @property
    def new_words(self) -> list[str]:
        return self.words[self.commit_from:self.commit_to]

    @property
    def has_new(self) -> bool:
        return self.commit_to > self.commit_from


class StreamState:
    """Per-utterance streaming state: what has been typed, and what to trim.

    `t0` and `committed` are shared with the finalising worker, which decodes
    the *same* trimmed window so its hypothesis lines up word-for-word with what
    was already typed. Get that wrong and the boundary either duplicates words
    or drops them — the bug `tests/test_livepath.py` exists to catch.
    """

    def __init__(self, policy: CommitPolicy | None = None, sr: int = 16000,
                 max_window_s: float = 0.0):
        self.policy = policy or LocalAgreementPolicy()
        self.sr = sr
        self.max_window_s = float(max_window_s or 0.0)
        self.t0 = 0
        self.committed: list[str] = []
        self.last_words: list[str] = []

    def step(self, segs, window_samples: int, can_type: bool = True) -> Step:
        """Fold one decoder pass into the state.

        `can_type=False` (the dictation hotkey is physically held, so synthetic
        keystrokes would arrive as Alt+char and be eaten) records the hypothesis
        and trims, but commits nothing — the release finalisation types it.
        """
        words = " ".join(text for text, _s, _e in segs).split()
        step = Step(words=words)
        if not words:
            return step

        stable = self.policy.stable_prefix(words, self.last_words)
        already = len(self.committed)
        if can_type and stable > already:
            step.commit_from, step.commit_to = already, stable
            self.committed.extend(words[already:stable])
        self.last_words = words

        window_dur = window_samples / self.sr if self.sr else 0.0
        dropped, trim_sec = plan_trim(segs, len(self.committed), window_dur,
                                      self.max_window_s)
        if dropped:
            step.trimmed_words = dropped
            step.trimmed_samples = int(trim_sec * self.sr)
            self.t0 += step.trimmed_samples
            self.committed = self.committed[dropped:]
            self.last_words = (self.last_words[dropped:]
                               if dropped <= len(self.last_words) else [])
        return step
