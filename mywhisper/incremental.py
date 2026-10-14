"""Finalize while the user is still talking.

The streamer trims audio whose words have been committed (local agreement) at
segment boundaries. That audio is finished: nothing later will change it. So
instead of re-decoding the whole utterance after the key is released, trimmed
audio is decoded at full quality in the background as it accumulates, and the
resulting text is polished (the cleanup pipeline, LLM included) one sentence
group at a time. Release then costs the tail only: the last few seconds of
audio and one short polish call, whatever the length of the dictation.

Two guards keep the user's words safe: a chunk whose final decode comes back
much shorter than what the streamer heard keeps the streamer's words, and a
polish that drops most of a span keeps the unpolished text.
"""

import logging
import queue
import re
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"[.!?]['\")\]]*$")
MIN_SPAN_WORDS = 14    # polish spans long enough for the LLM to see a sentence in context
MIN_DECODE_S = 5.0     # trimmed chunks are adjacent: merge them so Whisper gets context
CONTEXT_WORDS = 40     # words before the chunk, handed to the decoder as its prompt
KEEP_RATIO = 0.5       # below this fraction of the raw words, a decode/polish is refused


class IncrementalFinalizer:
    def __init__(self, transcribe, polish, min_span_words: int = MIN_SPAN_WORDS,
                 min_decode_s: float = MIN_DECODE_S, sr: int = 16000):
        self._transcribe = transcribe      # (audio, prompt) → segments (text, start, end)
        self._polish = polish              # text → cleaned text
        self._min_span = min_span_words
        self._min_decode = int(min_decode_s * sr)
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        # polished spans as (first raw word, one past the last raw word or
        # None for "to the end", text); raw = the words live typing committed
        self.spans: list[tuple[int, int | None, str]] = []
        self._taken = 0                    # spans the screen has applied
        self._pending: list[str] = []      # final words not yet polished
        self._pending_raw_start = 0
        self._raw_end = 0
        self._closed = False               # the span reaching the end has been emitted
        self._buf: list = []               # adjacent trimmed audio not decoded yet
        self._buf_raw: list[str] = []      # the streamer's words for that audio
        self._context: list[str] = []      # final words so far, for the decoder prompt
        self.chunks = 0
        self.polish_s = 0.0
        self.decode_s = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="finalizer")
        self._thread.start()

    # -- producer side (the streamer) -------------------------------------------

    def push(self, chunk, raw_words: list[str] | None = None):
        """Audio the streamer has trimmed, with the words it committed for it,
        cut at a segment boundary."""
        self._q.put((chunk, list(raw_words or [])))

    def take_ready(self) -> list[tuple[int, int | None, str]]:
        """Spans polished since the last call, for the screen to apply."""
        with self._lock:
            out = self.spans[self._taken:]
            self._taken = len(self.spans)
            return out

    @property
    def text(self) -> str:
        with self._lock:
            return " ".join(t for _a, _b, t in self.spans).strip()

    @property
    def covered(self) -> int | None:
        """Raw words the polished spans account for (None: all of them)."""
        with self._lock:
            return self.spans[-1][1] if self.spans else 0

    def cancel(self):
        self._q.put(None)

    def stop_now(self) -> tuple[str, int]:
        """Release, instantly: drop queued work, return the text polished so
        far and how many raw words it covers. A chunk already mid-polish
        finishes in the background and is ignored; nothing waits on the LLM."""
        while True:
            try:
                self._q.get_nowait()
                self._q.task_done()
            except queue.Empty:
                break
        self._q.put(None)
        with self._lock:
            covered = self.spans[-1][1] if self.spans else 0
            return " ".join(t for _a, _b, t in self.spans).strip(), covered or 0

    # -- the background thread ----------------------------------------------------

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            try:
                self._absorb(*item)
            except Exception:  # noqa: BLE001 — one bad chunk must not lose the rest
                log.warning("incremental finalize failed for a chunk", exc_info=True)
            finally:
                self._q.task_done()

    def _absorb(self, chunk, raw_words: list[str], final: bool = False):
        self._buf.append(chunk)
        self._buf_raw.extend(raw_words)
        if not final and sum(len(c) for c in self._buf) < self._min_decode:
            return
        self._decode_buffer(final)

    def _decode_buffer(self, final: bool):
        audio = np.concatenate(self._buf) if len(self._buf) > 1 else self._buf[0]
        raw, self._buf, self._buf_raw = self._buf_raw, [], []
        t0 = time.perf_counter()
        prompt = " ".join(self._context[-CONTEXT_WORDS:]) or None
        segs = self._transcribe(audio, prompt)
        self.decode_s += time.perf_counter() - t0
        self.chunks += 1
        words = " ".join(t for t, _s, _e in segs).split()
        if raw and len(words) < KEEP_RATIO * len(raw):
            log.warning("final decode heard %d words where the stream heard %d "
                        "— keeping the stream's words", len(words), len(raw))
            words = raw
        self._pending.extend(words)
        self._context.extend(words)
        if final:
            self._raw_end = None
        else:
            self._raw_end += len(raw)
        if final or (len(self._pending) >= self._min_span
                     and _SENTENCE_END.search(self._pending[-1])):
            self._flush_pending()

    def _flush_pending(self):
        a, b = self._pending_raw_start, self._raw_end
        if self._closed:
            return
        if not self._pending:
            if b is None:
                with self._lock:   # the tail said nothing: still close the span
                    self.spans.append((a, None, ""))
                self._closed = True
            return
        text = " ".join(self._pending)
        self._pending = []
        t0 = time.perf_counter()
        out = (self._polish(text) or "").strip()
        self.polish_s += time.perf_counter() - t0
        if out and len(out.split()) < KEEP_RATIO * len(text.split()):
            log.warning("polish kept %d of %d words — keeping the unpolished text",
                        len(out.split()), len(text.split()))
            out = text
        with self._lock:
            self.spans.append((a, b, out))
        if b is None:
            self._closed = True
        else:
            self._pending_raw_start = b

    # -- consumer side (the worker, after release) ----------------------------------

    def finish(self, tail, quick_polish=None) -> str:
        """Decode the tail, polish what is left, return the whole text. The
        spans not yet applied to the screen are in `take_ready()`.
        `quick_polish` (no LLM) replaces the polish for this last span: the
        words are already on screen and the user wants the pill gone."""
        if quick_polish is not None:
            # Swapped BEFORE waiting: chunks still queued at the stop are
            # cleaned without the LLM too, so a cold or busy model never
            # holds the pill. (A span already mid-call still finishes.)
            self._polish = quick_polish
        self._q.join()                      # every pushed chunk absorbed
        self._q.put(None)
        self._thread.join()
        try:
            if tail is not None and len(tail):
                self._absorb(tail, [], final=True)
            elif self._buf:
                self._decode_buffer(final=True)
            else:
                self._raw_end = None
        except Exception:  # noqa: BLE001 — keep what was finalized
            log.warning("tail decode failed — pasting what was finalized",
                        exc_info=True)
            self._raw_end = None
        self._flush_pending()
        return self.text
