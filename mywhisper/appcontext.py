"""Foreground-app awareness — which app is about to receive the dictation.

Fully local (Win32 only): the exe name drives per-app rules (chat apps don't
want a trailing period; styles pick a tone), and the window title is mined for
proper nouns to feed faster-whisper's hotword boosting — the same accuracy
trick Wispr Flow ships by uploading screenshots to their cloud, done here
without anything leaving the machine.
"""

import ctypes
import logging
import os
import re
from ctypes import wintypes

log = logging.getLogger(__name__)

# Window-chrome words that appear in every title bar and boost nothing.
_NOISE = {
    "google", "chrome", "microsoft", "windows", "edge", "mozilla", "firefox",
    "opera", "brave", "untitled", "document", "file", "edit", "view", "help",
    "new", "tab", "visual", "studio", "code", "notepad", "explorer", "settings",
    "search", "home", "page", "the", "and", "with", "for", "not", "free",
    "online", "login", "profile", "inbox", "app", "web", "site", "menu",
}


def foreground() -> tuple[str, str]:
    """(exe_name_lowercase, window_title) of the focused window — ("", "") on
    any failure; context must never break dictation."""
    if os.name != "nt":
        return ("", "")
    try:
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ("", "")
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value or ""

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                size = wintypes.DWORD(1024)
                pbuf = ctypes.create_unicode_buffer(size.value)
                if k32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                    exe = os.path.basename(pbuf.value).lower()
            finally:
                k32.CloseHandle(h)
        return (exe, title)
    except Exception:  # noqa: BLE001
        return ("", "")


def title_hotwords(title: str, limit: int = 8) -> list[str]:
    """Proper-noun-ish tokens from a window title, worth boosting.

    Kept deliberately picky: Capitalized, CamelCase, dotted, or underscored
    tokens only — common window-chrome words are filtered. "PR #142 — Svara
    streaming fix" yields ["PR", "Svara"]-grade tokens, not "streaming"."""
    out: list[str] = []
    seen: set[str] = set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_.\-]{2,29}", title or ""):
        low = tok.lower().strip(".-_")
        if low in _NOISE or low in seen:
            continue
        interesting = (tok[0].isupper()
                       or any(c.isupper() for c in tok[1:])
                       or "." in tok or "_" in tok)
        if not interesting:
            continue
        seen.add(low)
        out.append(tok)
        if len(out) >= limit:
            break
    return out
