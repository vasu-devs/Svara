"""Windows integrity levels — why dictation into an admin window does nothing.

User Interface Privilege Isolation stops a medium-integrity process from
sending synthetic input to a high-integrity one. It does this *silently*:
`SendInput` returns the number of events it "sent", the events are discarded,
and nothing anywhere reports an error. From the user's seat, Svara typed
nothing into their elevated PowerShell and gave no reason.

So we detect it ourselves and say so. The check is cheap and cached per-pid,
because it runs on the hot path at the start of every dictation.

Detection: compare our token's integrity RID with the target's. When the target
sits above us we cannot open its token at all — that `ACCESS_DENIED`, from a
medium-integrity process, *is* the answer.
"""

import ctypes
import logging
import os
from ctypes import wintypes

log = logging.getLogger(__name__)

SECURITY_MANDATORY_UNTRUSTED = 0x0000
SECURITY_MANDATORY_LOW = 0x1000
SECURITY_MANDATORY_MEDIUM = 0x2000
SECURITY_MANDATORY_HIGH = 0x3000
SECURITY_MANDATORY_SYSTEM = 0x4000

_TOKEN_QUERY = 0x0008
_TOKEN_INTEGRITY_LEVEL = 25
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5

_cache: dict[int, bool] = {}
_own_level: int | None = None


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = (("Label", _SID_AND_ATTRIBUTES),)


def _token_integrity(handle) -> int | None:
    """Integrity RID of an open process handle, or None if unreadable."""
    advapi = ctypes.windll.advapi32
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(handle, _TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD(0)
        advapi.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, None, 0,
                                   ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, _TOKEN_INTEGRITY_LEVEL, buf,
                                          size, ctypes.byref(size)):
            return None
        label = ctypes.cast(buf, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
        count_ptr = advapi.GetSidSubAuthorityCount(label.Label.Sid)
        count = ctypes.cast(count_ptr, ctypes.POINTER(ctypes.c_ubyte)).contents.value
        rid_ptr = advapi.GetSidSubAuthority(label.Label.Sid, count - 1)
        return ctypes.cast(rid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value
    finally:
        ctypes.windll.kernel32.CloseHandle(token)


def own_integrity() -> int:
    """Our own integrity level. Cached — it cannot change while we run."""
    global _own_level
    if _own_level is not None:
        return _own_level
    _own_level = SECURITY_MANDATORY_MEDIUM
    if os.name == "nt":
        try:
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            level = _token_integrity(handle)
            if level is not None:
                _own_level = level
        except Exception:  # noqa: BLE001 — never break dictation over a probe
            log.debug("could not read own integrity level", exc_info=True)
    return _own_level


def we_are_elevated() -> bool:
    return own_integrity() >= SECURITY_MANDATORY_HIGH


def target_is_higher(pid: int) -> bool:
    """Whether `pid` runs at a higher integrity level than us — i.e. whether
    our synthetic keystrokes will be silently dropped."""
    if os.name != "nt" or not pid:
        return False
    if pid in _cache:
        return _cache[pid]
    result = False
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Can't even open it: on a medium-integrity process that usually
            # means the target is above us. If we're already elevated, it's
            # something else (a protected process) and not our problem.
            result = not we_are_elevated()
        else:
            try:
                level = _token_integrity(handle)
                if level is None:
                    err = ctypes.get_last_error()
                    result = (err == _ERROR_ACCESS_DENIED and not we_are_elevated())
                else:
                    result = level > own_integrity()
            finally:
                k32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        log.debug("elevation probe failed for pid %s", pid, exc_info=True)
        result = False
    # Bound the cache: pids are recycled and a long session touches many apps.
    if len(_cache) > 256:
        _cache.clear()
    _cache[pid] = result
    return result


def reset_cache():
    _cache.clear()
