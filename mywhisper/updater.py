"""Auto-update via GitHub Releases — download in the background, apply on a
user-approved restart.

Riding the self-install machinery keeps this small and safe: "applying" an
update just means launching the downloaded exe after this process exits — its
own ensure_installed() replaces %LOCALAPPDATA%\\Svara\\Svara.exe, carries the
setup-done flag forward (no re-onboarding), re-registers autostart, and
relaunches. Nothing here rewrites a running binary.
"""

import json
import logging
import re
import subprocess
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/vasu-devs/Svara/releases/latest"
_EXE_RE = re.compile(r"^Svara(?:[-_ ]?v?(\d+(?:\.\d+)*))?\.exe$", re.IGNORECASE)


def pick_asset(release: dict) -> tuple[str, str, str] | None:
    """(version, download_url, filename) of the newest Svara exe asset in a
    GitHub release JSON, or None. Prefers a versioned filename
    (Svara-0.4.0.exe); falls back to the release tag for a bare Svara.exe."""
    tag = (release.get("tag_name") or "").lstrip("vV")
    best = None
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        m = _EXE_RE.match(name)
        if not m:
            continue
        version = m.group(1) or tag
        url = asset.get("browser_download_url")
        if not version or not url:
            continue
        from .install import _version_tuple
        if best is None or _version_tuple(version) > _version_tuple(best[0]):
            best = (version, url, name)
    return best


def check_latest(timeout: float = 15.0) -> tuple[str, str, str] | None:
    """Query GitHub for the latest release. None on any failure — update
    checks are best-effort background noise, never user-facing errors."""
    try:
        req = urllib.request.Request(
            RELEASES_API, headers={"User-Agent": "Svara-updater",
                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            release = json.loads(r.read().decode("utf-8"))
        return pick_asset(release)
    except Exception:  # noqa: BLE001
        log.debug("update check failed", exc_info=True)
        return None


def download(url: str, dest: Path, timeout: float = 600.0) -> bool:
    """Stream the asset to dest (.part then atomic rename)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Svara-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            with open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001
        log.warning("update download failed", exc_info=True)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


class Updater:
    """Background checker + staged-update state for the running app."""

    def __init__(self, notify=None):
        self.notify = notify or (lambda *_: None)
        self.staged: Path | None = None   # downloaded exe ready to apply
        self.staged_version: str | None = None
        self._lock = threading.Lock()

    def check_and_stage(self, quiet: bool = True) -> bool:
        """One check→download cycle. Returns True if an update is staged.
        quiet=False (user clicked "Check for updates") always toasts a result."""
        from . import __version__
        from .install import _version_tuple, install_dir
        with self._lock:
            if self.staged and self.staged.is_file():
                if not quiet:
                    self.notify(f"Update v{self.staged_version} is already "
                                "downloaded — use 'Restart to update'.")
                return True
            found = check_latest()
            if not found:
                if not quiet:
                    self.notify("Couldn't reach GitHub to check for updates — "
                                "try again later.")
                return False
            version, url, name = found
            if _version_tuple(version) <= _version_tuple(__version__):
                if not quiet:
                    self.notify(f"You're up to date (v{__version__}).")
                return False
            self.notify(f"Downloading Svara v{version} in the background…")
            dest = install_dir() / "updates" / name
            if not download(url, dest):
                if not quiet:
                    self.notify("Update download failed — will retry later.")
                return False
            self.staged, self.staged_version = dest, version
            self.notify(f"Svara v{version} is ready — right-click the tray "
                        "icon and choose 'Restart to update'.")
            log.info("update v%s staged at %s", version, dest)
            return True

    def start_background_checks(self, hours: float):
        """Daily-ish check loop: first check ~2 min after boot (never compete
        with model load), then every `hours`."""
        if hours <= 0:
            return

        def loop():
            import time
            time.sleep(120)
            while True:
                try:
                    self.check_and_stage(quiet=True)
                except Exception:  # noqa: BLE001
                    log.debug("background update check crashed", exc_info=True)
                time.sleep(max(1.0, hours) * 3600)

        threading.Thread(target=loop, daemon=True, name="updater").start()

    def apply(self, shutdown):
        """Launch the staged exe after this process exits, then shut down.
        The staged exe self-installs (newer version wins) and relaunches."""
        if not (self.staged and self.staged.is_file()):
            self.notify("No update downloaded yet.")
            return
        try:
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            # 3s delay lets this process release the single-instance mutex
            # and the exe file lock before the new version starts.
            subprocess.Popen(
                ["cmd", "/c",
                 f'timeout /t 3 /nobreak >nul & start "" "{self.staged}"'],
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                close_fds=True)
            log.info("restarting into staged update v%s", self.staged_version)
        except OSError:
            log.exception("could not launch the staged update")
            self.notify("Couldn't start the update — see logs/mywhisper.log.")
            return
        shutdown()
