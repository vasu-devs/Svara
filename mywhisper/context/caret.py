"""Reading the text immediately before the caret — locally, and only if asked.

Why it's worth having: dictating into the middle of a sentence should not
capitalise. "…and then we" + dictation should continue "went to the shop", not
"Went to the shop". Whisper has no idea it is mid-sentence; the text field does.
The same signal makes a much better `initial_prompt` for the decoder, and it is
what any honest auto-learned-dictionary feature has to be built on.

Why it is **off by default** (`context.read_caret_text: false`): this reads text
the user typed that Svara did not produce. That is a different and larger
promise than "we look at your window title". It is opt-in, hard-capped at a few
hundred characters, never written to a log, never persisted, and dropped the
moment the utterance finishes.

Implementation notes: UI Automation's TextPattern is the only interface that
works across Win32, browsers, and Electron. It is also slow and occasionally
hostile — some apps block for hundreds of milliseconds. So every call is
budgeted, and three consecutive failures disable the provider for the rest of
the session rather than paying that cost on every dictation.
"""

import logging
import os
import threading

log = logging.getLogger(__name__)

_UIA_TEXT_PATTERN = 10014       # UIA_TextPatternId
_CONTROL_EDIT = 50004
_CONTROL_DOCUMENT = 50030

_uia = None
_fails = 0
_lock = threading.Lock()

MAX_FAILS = 3


def available() -> bool:
    return os.name == "nt" and _fails < MAX_FAILS


def _client():
    global _uia
    if _uia is None:
        import comtypes
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation

        _uia = comtypes.CoCreateInstance(
            CUIAutomation._reg_clsid_, interface=IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER)
    return _uia


def _read(max_chars: int) -> str | None:
    el = _client().GetFocusedElement()
    if el is None:
        return None
    if el.CurrentControlType not in (_CONTROL_EDIT, _CONTROL_DOCUMENT):
        return None
    pattern = el.GetCurrentPattern(_UIA_TEXT_PATTERN)
    if not pattern:
        return None
    import comtypes.client
    from comtypes.gen.UIAutomationClient import IUIAutomationTextPattern

    text_pattern = pattern.QueryInterface(IUIAutomationTextPattern)
    selection = text_pattern.GetSelection()
    if selection is None or selection.Length < 1:
        return None
    rng = selection.GetElement(0)
    # Walk backwards from the caret. MoveEndpointByUnit with a negative count
    # on the Start endpoint extends the range leftwards; unit 3 = Character.
    try:
        rng.MoveEndpointByUnit(0, 3, -max_chars)
    except Exception:  # noqa: BLE001 — some providers reject character units
        rng.ExpandToEnclosingUnit(2)  # 2 = Line
    text = rng.GetText(max_chars)
    return text or None


def prefix(max_chars: int = 200, budget_s: float = 0.25) -> str | None:
    """Text immediately before the caret, or None.

    Runs on a worker thread with a hard budget: a slow or hostile UIA provider
    must not add a quarter-second to every dictation start. On timeout the
    result is simply dropped — a missing context signal is a non-event, a
    delayed dictation is not.
    """
    global _fails
    if not available():
        return None

    result: list[str | None] = [None]
    failed: list[bool] = [False]

    def work():
        try:
            import comtypes
            comtypes.CoInitialize()
            try:
                result[0] = _read(max_chars)
            finally:
                comtypes.CoUninitialize()
        except Exception:  # noqa: BLE001
            failed[0] = True
            log.debug("caret-text read failed", exc_info=True)

    thread = threading.Thread(target=work, daemon=True, name="caret-context")
    thread.start()
    thread.join(budget_s)

    with _lock:
        if thread.is_alive() or failed[0]:
            _fails += 1
            if _fails >= MAX_FAILS:
                log.info("caret-text context disabled for this session — the "
                         "focused app's automation provider is unavailable or "
                         "too slow")
            return None
        _fails = 0

    text = result[0]
    if not text:
        return None
    return text[-max_chars:]


def reset():
    """Re-enable after a session-level disable (used by tests and config reload)."""
    global _fails
    _fails = 0
