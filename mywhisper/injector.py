"""System-wide text injection on Windows.

Two methods (both proven by whisper-local / faster-whisper-dictation):
- "type":  Win32 SendInput with KEYEVENTF_UNICODE — types the text directly into
           the focused control, char-perfect, works without touching the clipboard.
- "paste": put text on the clipboard via the Win32 API, simulate Ctrl+V, then
           restore the previous clipboard content. Fastest for very long text.

Before injecting we wait for the hotkey's modifier keys to be physically
released, otherwise a still-held Ctrl would turn our keystrokes into shortcuts.
"""

import ctypes
import logging
import threading
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- SendInput plumbing -------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN, VK_TAB, VK_CONTROL, VK_V = 0x0D, 0x09, 0x11, 0x56
_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # shift, ctrl, alt, lwin, rwin

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
user32.GetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)
user32.SetClipboardData.restype = ctypes.c_void_p


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return inp


def _send(events: list[INPUT]):
    if not events:
        return
    arr = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"SendInput sent {sent}/{len(events)} events "
                      f"(error {ctypes.get_last_error()})")


def wait_modifiers_released(timeout: float = 2.0):
    """Block until Shift/Ctrl/Alt/Win are all physically up (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS):
            return
        time.sleep(0.01)
    log.warning("modifier keys still held after %.1fs — injecting anyway", timeout)


def type_text(text: str):
    """Type text into the focused window via KEYEVENTF_UNICODE."""
    events: list[INPUT] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch in ("\n", "\t"):
            vk = VK_RETURN if ch == "\n" else VK_TAB
            events.append(_key_event(vk=vk))
            events.append(_key_event(vk=vk, flags=KEYEVENTF_KEYUP))
            continue
        # UTF-16 code units (handles emoji / surrogate pairs)
        data = ch.encode("utf-16-le")
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i + 2], "little")
            events.append(_key_event(scan=unit, flags=KEYEVENTF_UNICODE))
            events.append(_key_event(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    # Chunk so slow apps don't drop events (128 events = 64 chars per call).
    for i in range(0, len(events), 128):
        _send(events[i:i + 128])
        time.sleep(0.005)


# --- Clipboard method -----------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _clipboard_get() -> str | None:
    if not user32.OpenClipboard(None):
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _clipboard_set(text: str) -> bool:
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, buf, size)
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


def paste_text(text: str, restore: bool = True):
    old = _clipboard_get() if restore else None
    if not _clipboard_set(text):
        log.warning("clipboard set failed — falling back to direct typing")
        type_text(text)
        return
    _send([
        _key_event(vk=VK_CONTROL),
        _key_event(vk=VK_V),
        _key_event(vk=VK_V, flags=KEYEVENTF_KEYUP),
        _key_event(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
    ])
    if restore and old is not None:
        # Give the target app time to read the clipboard before restoring.
        def _restore():
            time.sleep(0.5)
            _clipboard_set(old)
        threading.Thread(target=_restore, daemon=True).start()


# --- Public façade ---------------------------------------------------------------

class TextInjector:
    def __init__(self, inj_cfg: dict):
        self.method = inj_cfg["method"]
        self.append_space = bool(inj_cfg["append_space"])
        self.restore_clipboard = bool(inj_cfg["restore_clipboard"])

    def inject(self, text: str) -> int:
        if not text:
            return 0
        if self.append_space and not text.endswith((" ", "\n")):
            text += " "
        wait_modifiers_released()
        if self.method == "paste":
            paste_text(text, restore=self.restore_clipboard)
        else:
            type_text(text)
        return len(text)

    def inject_stream(self, text: str) -> int:
        """Live-typing chunks: always direct typing, no trailing-space logic
        (streaming deltas carry their own spacing), clipboard untouched."""
        if not text:
            return 0
        wait_modifiers_released()
        type_text(text)
        return len(text)
