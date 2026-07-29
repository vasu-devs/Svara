"""Noticing the corrections you make, and asking before acting on them.

If Svara writes "Kubernetes" as "cuban eddies" and you fix it three times, it
should offer to learn the word. That is the retention loop that makes a
dictation tool feel like yours.

It is also the most invasive idea in the codebase, so every design decision
here is a restraint:

- **It only ever suggests.** Observations go into a review queue
  (`dictionary_io.LearnQueue`). The dictionary is written only when the user
  clicks accept. Nothing is silently learned, ever.
- **Two independent thresholds.** N occurrences *and* ≥2 distinct sessions. One
  frustrated editing session should not teach Svara anything permanent.
- **Only single-word substitutions.** Rewriting a whole sentence is editing,
  not correcting, and inferring vocabulary from it produces nonsense.
- **Needs two opt-ins.** `dictionary.auto_learn` *and*
  `context.read_caret_text`, because it is built on reading text you typed that
  Svara did not produce.
- **Nothing is logged.** Not the observation, not the correction, not the
  field. Counts only.
- **It gives up quietly.** Wrong field, closed window, slow app — the
  observation is dropped. A missed correction costs nothing; a wrong one costs
  trust.
"""

import difflib
import logging
import re
import threading

log = logging.getLogger(__name__)

DEFAULT_DELAY_S = 6.0
MAX_EDIT_DISTANCE = 8

# How alike a heard/corrected pair must be to count as a *correction* rather
# than a rewrite. Calibrated against real cases in both directions:
#   "cuban" → "kubernetes"  scores 0.40 — a plausible mishearing, must pass
#   "colour" → "color"      scores 0.91 — obviously a correction
#   "shop"   → "cinema"     scores 0.00 — the user rephrased, must fail
#   "meeting" → "standup"   scores 0.29 — also a rephrase, must fail
# 0.35 sits in the gap. Raising it starts dropping genuine phonetic misses,
# which are exactly the words worth learning.
MIN_SIMILARITY = 0.35


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'’-]+", text or "")


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=a.lower(), b=b.lower()).ratio()


def find_corrections(before: str, after: str,
                     max_pairs: int = 3) -> list[tuple[str, str]]:
    """Single-word substitutions between what Svara typed and what's there now.

    Restricted hard, on purpose:

    - one-for-one replacements only (a 1→3 word change is rephrasing);
    - both sides alphabetic and 3+ characters (drops digits and "a"/"the");
    - the pair must be *similar* (a phonetic near-miss like
      "cuban"→"kubernetes") but not identical. Two unrelated words mean the
      user rewrote their sentence, which teaches nothing about recognition.
    """
    a, b = _words(before), _words(after)
    if not a or not b:
        return []
    out: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(a=[w.lower() for w in a],
                                      b=[w.lower() for w in b], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace" or (i2 - i1) != 1 or (j2 - j1) != 1:
            continue
        heard, corrected = a[i1], b[j1]
        if len(heard) < 3 or len(corrected) < 3:
            continue
        if not heard.isalpha() or not corrected.isalpha():
            continue
        if heard.lower() == corrected.lower():
            continue
        if abs(len(heard) - len(corrected)) > MAX_EDIT_DISTANCE:
            continue
        if _similar(heard, corrected) < MIN_SIMILARITY:
            continue
        out.append((heard, corrected))
        if len(out) >= max_pairs:
            break
    return out


class AutoLearner:
    """Schedules one delayed re-read per dictation and queues what it finds."""

    def __init__(self, queue, enabled: bool = False, delay_s: float = DEFAULT_DELAY_S,
                 notify=None, read_caret=None):
        self.queue = queue
        self.enabled = enabled
        self.delay_s = delay_s
        self.notify = notify or (lambda *_: None)
        # Injected so tests don't need UI Automation, and so the caret reader
        # stays the single place that touches UIA.
        self._read_caret = read_caret
        self._timer: threading.Timer | None = None

    def _caret_text(self, max_chars: int) -> str | None:
        if self._read_caret is not None:
            return self._read_caret(max_chars)
        from .context import caret
        return caret.prefix(max_chars=max_chars, budget_s=0.4)

    def watch(self, injected: str):
        """Called right after a dictation lands. Schedules the re-read."""
        if not self.enabled or not injected or not injected.strip():
            return
        if len(_words(injected)) < 2:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.delay_s, self._check, args=(injected,))
        self._timer.daemon = True
        self._timer.start()

    def _check(self, injected: str):
        try:
            # Read a window comfortably larger than what we typed, so the
            # comparison sees the corrected version in full.
            now = self._caret_text(max(200, len(injected) + 120))
            if not now:
                return
            # Align on the tail: the user may have kept typing after our text.
            tail = now[-(len(injected) + 120):]
            pairs = find_corrections(injected, tail)
            for heard, corrected in pairs:
                ready = self.queue.observe(heard, corrected)
                if ready is not None:
                    self.notify(
                        f"You've corrected “{ready.heard}” to "
                        f"“{ready.corrected}” {ready.count} times. "
                        "Add it to your dictionary? Tray ▸ Dictionary ▸ "
                        "Suggestions.")
        except Exception:  # noqa: BLE001 — a failed observation is a non-event
            log.debug("auto-learn check failed", exc_info=True)

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
