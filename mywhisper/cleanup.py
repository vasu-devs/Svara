"""Backwards-compatible façade over `mywhisper.pipeline`.

The cleanup logic moved into a stage chain (`pipeline/`) so that locale
typography, transliteration, list detection and per-app rules could each be a
testable unit instead of another branch in one growing method. This module
keeps the old import path working — external configs, the tests written against
v0.4, and anything a user has scripted against `mywhisper.cleanup` all continue
to resolve.

New code should import from `mywhisper.pipeline`.
"""

from .pipeline import (LEVELS, Chain, CleanupPipeline, LlmCleanup, Personalizer,
                       UtteranceContext, apply_backtrack, build_chain,
                       strip_fillers)
from .pipeline.personal import _SPOKEN_PUNCT

__all__ = [
    "LEVELS", "Chain", "CleanupPipeline", "LlmCleanup", "Personalizer",
    "UtteranceContext", "apply_backtrack", "build_chain", "strip_fillers",
    "_SPOKEN_PUNCT",
]
