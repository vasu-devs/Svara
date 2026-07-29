"""The speech-recognition seam.

Svara has been faster-whisper the whole way down, and faster-whisper is a good
default. It is not obviously the *best* one — streaming-native architectures
exist that do not re-decode a growing window every pass, which is precisely the
cost the benchmark identifies as the constraint on this machine.

Swapping an engine is only a sane experiment if there is somewhere to swap it
in. This is that place.

`Segment` is a `NamedTuple`, deliberately: it is still a `(text, start, end)`
tuple, so every existing `for text, start, end in segs` keeps working, while new
code can say `seg.text`. A seam that forces a rewrite of its callers is a seam
nobody uses.

Anything claiming to be a backend must, without negotiation:

- run **fully offline** after any first-run download,
- package into a PyInstaller build,
- carry a licence compatible with AGPL-3.0,
- and **beat the incumbent on `--bench`**, on the machine in question, rather
  than on a number from a paper.
"""

from dataclasses import dataclass
from typing import NamedTuple, Protocol, runtime_checkable

import numpy as np


class Segment(NamedTuple):
    """One recognised span. Timings drive loudness→CAPS and window trimming."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class BackendCaps:
    """What a backend can actually do, so callers stop guessing.

    `streaming_native` is the one that matters for Phase 3: a backend that
    consumes audio incrementally does not need the re-decode-the-window dance
    at all, and the streamer can take a different path for it.
    """

    name: str
    streaming_native: bool = False
    multilingual: bool = True
    word_timings: bool = True
    translate: bool = True
    hotwords: bool = True


@runtime_checkable
class AsrBackend(Protocol):
    device_used: str
    compute_used: str

    @property
    def capabilities(self) -> BackendCaps: ...

    def transcribe(self, audio: np.ndarray) -> list[Segment]:
        """Full-quality pass over a finished utterance."""
        ...

    def transcribe_partial(self, audio: np.ndarray,
                           prompt: str | None = None) -> list[Segment]:
        """Fast pass over an in-progress buffer, for live streaming."""
        ...
