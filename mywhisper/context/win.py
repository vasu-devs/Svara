"""Foreground-app awareness — which app is about to receive the dictation.

Fully local (Win32 only): the exe name drives per-app rules (chat apps don't
want a trailing period, terminals need line-safe injection, styles pick a tone),
and the window title is mined for proper nouns to feed faster-whisper's hotword
boosting — the same accuracy trick cloud dictation tools ship by uploading
screenshots, done here without anything leaving the machine.

Every function fails to a neutral value. Context is an enhancement; it must
never be the reason a dictation doesn't happen.
"""

import ctypes
import logging
import os
import re
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Window-chrome words that appear in every title bar and boost nothing.
_NOISE = {
    "google", "chrome", "microsoft", "windows", "edge", "mozilla", "firefox",
    "opera", "brave", "untitled", "document", "file", "edit", "view", "help",
    "new", "tab", "visual", "studio", "code", "notepad", "explorer", "settings",
    "search", "home", "page", "the", "and", "with", "for", "not", "free",
    "online", "login", "profile", "inbox", "app", "web", "site", "menu",
}


@dataclass(frozen=True)
class Foreground:
    exe: str = ""
    title: str = ""
    pid: int = 0
    hwnd: int = 0


def foreground_full() -> Foreground:
    """Everything we can learn about the focused window in one pass."""
    if os.name != "nt":
        return Foreground()
    try:
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return Foreground()
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
        return Foreground(exe=exe, title=title, pid=int(pid.value), hwnd=int(hwnd))
    except Exception:  # noqa: BLE001
        return Foreground()


def foreground() -> tuple[str, str]:
    """(exe_name_lowercase, window_title) — the pre-0.5 shape, still used by
    callers that only need those two."""
    fg = foreground_full()
    return (fg.exe, fg.title)


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
