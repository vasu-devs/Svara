"""Self-install: the downloaded Svara.exe copies itself to a permanent home
and registers to start at login, so dictation works after every reboot.

Why: a portable exe in Downloads only runs while the user remembers to
double-click it. After a restart nothing launches it, the hotkey does nothing,
and the app looks broken. Real dictation apps survive reboots because they
install themselves once and register with the OS. This module does exactly
that, without an installer download:

  1. First double-click (from Downloads or anywhere) → copy the exe to
     %LOCALAPPDATA%\\Svara\\Svara.exe, migrate config/state next to it,
     register the Start Menu shortcut + login autostart, launch the installed
     copy, and exit. The downloaded file becomes a disposable installer.
  2. Every launch of the installed copy re-asserts the registrations
     (self-healing: a deleted Run key or retargeted shortcut gets fixed).

Everything is best-effort: if any step fails (AV lock, disk full), Svara
keeps running from wherever it is — installation must never brick a launch.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "Svara"
EXE_NAME = "Svara.exe"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MANIFEST = "installed.json"


def install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:  # extremely unusual, but never crash over it
        local = str(Path.home() / "AppData" / "Local")
    return Path(local) / APP_NAME


def installed_exe() -> Path:
    return install_dir() / EXE_NAME


def is_installed_copy() -> bool:
    """Is the running exe the one living in the install dir?"""
    if not getattr(sys, "frozen", False):
        return False
    try:
        return Path(sys.executable).resolve().parent == install_dir().resolve()
    except OSError:
        return False


def _version_tuple(v: str) -> tuple:
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _installed_version() -> str | None:
    try:
        data = json.loads((install_dir() / MANIFEST).read_text(encoding="utf-8"))
        return data.get("version")
    except (OSError, ValueError):
        return None


def _stamp_of(exe: Path, version: str) -> str | None:
    """The setup-done stamp __main__._exe_stamp() would compute for this exe."""
    try:
        st = exe.stat()
        return f"{version}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return None


def _write_manifest(version: str) -> None:
    try:
        (install_dir() / MANIFEST).write_text(
            json.dumps({"version": version, "exe": str(installed_exe())}),
            encoding="utf-8")
    except OSError:
        log.debug("could not write install manifest", exc_info=True)


def _migrate_user_files(src_dir: Path, dst_dir: Path) -> None:
    """Carry the user's config/state (and the setup-done flag) into the
    install dir — but never clobber what's already there: the installed copy's
    files are the live ones; the source files are just a seed for first
    install. copy2 preserves mtime, which .svara_ready's exe-stamp check
    relies on."""
    for name in ("config.yaml", "state.json", ".svara_ready"):
        src, dst = src_dir / name, dst_dir / name
        try:
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)
                log.info("migrated %s → %s", name, dst_dir)
        except OSError:
            log.debug("could not migrate %s", name, exc_info=True)
    # The on-demand CUDA runtime (~1.9 GB) also lives next to the exe. MOVE it
    # (same-drive rename is instant) — losing it means a silent 1.3 GB
    # re-download for GPU users. On failure the app re-downloads on demand.
    src_cuda, dst_cuda = src_dir / "cuda", dst_dir / "cuda"
    try:
        if src_cuda.is_dir() and not dst_cuda.exists():
            shutil.move(str(src_cuda), str(dst_cuda))
            log.info("migrated CUDA runtime → %s", dst_cuda)
    except OSError:
        log.warning("could not migrate the CUDA runtime — Svara will offer "
                    "to re-download GPU support", exc_info=True)


def _release_single_instance_mutex() -> None:
    """Let go of the single-instance mutex so the installed copy we spawn can
    acquire it — otherwise the handoff child sees 'already running' and exits."""
    handle = getattr(sys, "_mywhisper_mutex", None)
    if handle and os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            pass
        sys._mywhisper_mutex = None


def _spawn(exe: Path) -> bool:
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            [str(exe)], cwd=str(exe.parent), close_fds=True,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        return True
    except OSError:
        log.exception("could not launch installed copy at %s", exe)
        return False


def ensure_installed(splash=None) -> bool:
    """Called once at startup of a frozen build (after the single-instance
    check). Returns True if this process handed off to the installed copy and
    must exit now; False to continue running normally.

    Running copy IS the installed one → just refresh the manifest, continue.
    Running copy is elsewhere (Downloads…) → install + relaunch + hand off.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    from . import __version__

    if is_installed_copy():
        _write_manifest(__version__)
        _purge_applied_updates(__version__)
        return False

    src = Path(sys.executable).resolve()
    dst = installed_exe()

    # Downgrade guard: an old forgotten download ("Svara (2).exe") must not
    # silently replace a newer installed version — run the installed one.
    have = _installed_version()
    if have and dst.is_file() and _version_tuple(have) > _version_tuple(__version__):
        log.info("installed v%s is newer than this v%s — launching it instead",
                 have, __version__)
        _migrate_user_files(src.parent, dst.parent)
        _release_single_instance_mutex()
        return _spawn(dst)

    if splash:
        splash("Installing Svara (one time) — moving in to its permanent home…")
    try:
        install_dir().mkdir(parents=True, exist_ok=True)
        # Upgrade carry-forward: if setup was completed for the exe we're about
        # to replace, the user shouldn't be re-onboarded just because the
        # version bumped — restamp the flag for the new exe after the copy.
        flag = install_dir() / ".svara_ready"
        carry_setup = False
        try:
            if have and dst.is_file() and flag.is_file():
                carry_setup = (flag.read_text(encoding="utf-8").strip()
                               == _stamp_of(dst, have))
        except OSError:
            pass
        same = False
        try:
            s, d = src.stat(), dst.stat()
            same = (s.st_size == d.st_size
                    and s.st_mtime_ns == d.st_mtime_ns)
        except OSError:
            pass
        if not same:
            tmp = dst.with_suffix(".exe.new")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)  # atomic: never a half-written Svara.exe
        _migrate_user_files(src.parent, dst.parent)
        _write_manifest(__version__)
        if carry_setup:
            new_stamp = _stamp_of(dst, __version__)
            if new_stamp:
                try:
                    flag.write_text(new_stamp, encoding="utf-8")
                    log.info("upgrade — carrying setup-done forward (no re-setup)")
                except OSError:
                    pass
        log.info("installed Svara v%s → %s", __version__, dst)
    except OSError:
        # PermissionError here usually means the installed copy is running
        # (unlikely — the mutex check would have caught it) or AV interference.
        # Portable fallback: keep running from where we are.
        log.warning("install to %s failed — running portable from %s",
                    dst, src, exc_info=True)
        return False

    _release_single_instance_mutex()
    if _spawn(dst):
        return True
    return False  # spawn failed → keep running from here rather than dying


def _purge_applied_updates(current_version: str) -> None:
    """Staged auto-update downloads are ~107 MB each; once we're running a
    version ≥ theirs they're dead weight. Newer ones (downloaded, not yet
    applied) are kept."""
    import re
    updates = install_dir() / "updates"
    if not updates.is_dir():
        return
    for f in updates.glob("*.exe"):
        m = re.search(r"(\d+(?:\.\d+)+)", f.name)
        if m and _version_tuple(m.group(1)) > _version_tuple(current_version):
            continue  # a newer staged update — leave it for the tray to apply
        try:
            f.unlink()
            log.info("removed applied update %s", f.name)
        except OSError:
            pass


# -- login autostart (HKCU Run key — per-user, no admin needed) ---------------

def autostart_registered() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, APP_NAME)
        return bool(value)
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Register/unregister launch-at-login for the installed exe. Returns
    success. Points at the INSTALLED copy even if called from elsewhere, so
    the registration never targets a file the user may delete."""
    if os.name != "nt":
        return False
    exe = installed_exe()
    if enabled and not exe.is_file():
        # Not installed (dev run / portable) — fall back to the running exe.
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable)
        else:
            log.info("autostart skipped — no installed exe (dev run)")
            return False
    try:
        import winreg
        # CreateKeyEx, not OpenKey: a pristine user profile (fresh Windows
        # install, CI runner) may not have the Run key yet.
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ,
                                  f'"{exe}" --autostart')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        log.info("autostart %s", "registered" if enabled else "removed")
        return True
    except OSError:
        log.warning("autostart registry update failed", exc_info=True)
        return False


def ensure_autostart() -> None:
    """Self-heal on every launch of the installed copy: unless the user turned
    it off, (re)write the Run key — fixes deleted keys and stale paths. The
    user's choice lives in state.json ("autostart": false = opted out)."""
    if not is_installed_copy():
        return
    from .paths import state_path
    wants = True
    try:
        state = json.loads(state_path().read_text(encoding="utf-8"))
        wants = state.get("autostart", True) is not False
    except (OSError, ValueError):
        pass
    set_autostart(wants)
