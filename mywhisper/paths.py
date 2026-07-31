"""Where MyWhisper reads/writes user files (config, state, logs).

Frozen (.exe): next to the executable, so users can edit config.yaml and keep
state/logs beside the app. Source run: the project root.
"""
import os
import shutil
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return base_dir() / "config.yaml"


def ensure_config() -> Path:
    """First run of a frozen build (.exe): drop the bundled default config.yaml
    next to the executable so it loads the intended defaults and users can edit
    it. (PyInstaller bundles data under _internal/_MEIPASS, not next to the exe.)
    """
    p = config_path()
    if not p.exists() and getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", base_dir())) / "config.yaml"
        try:
            if bundled.is_file():
                shutil.copyfile(bundled, p)
        except OSError:
            pass
    return p


def reference_config_path() -> Path:
    return base_dir() / "config.reference.yaml"


def write_reference_config() -> Path | None:
    """Drop this build's fully-commented config next to the user's own.

    `ensure_config()` only seeds config.yaml when there isn't one, which is
    right — nobody's settings should be overwritten by an update. But it means
    an upgrading user keeps a config.yaml that has never heard of the options
    added since. Everything still *works* (missing keys fall back to defaults),
    they just have no way to discover it.

    So the current documented config is written alongside, read-only in intent,
    refreshed every launch. Copy a block out of it into config.yaml to use it.
    """
    if not getattr(sys, "frozen", False):
        return None
    bundled = Path(getattr(sys, "_MEIPASS", base_dir())) / "config.yaml"
    dest = reference_config_path()
    try:
        if bundled.is_file():
            shutil.copyfile(bundled, dest)
            return dest
    except OSError:
        pass
    return None


def state_path() -> Path:
    return base_dir() / "state.json"


def meetings_dir() -> Path:
    """Where meeting notes land: Documents\\Svara Meetings — a user-visible
    place, because notes are documents, not app state. Falls back to the app
    dir if Documents is missing/redirected somewhere unwritable."""
    docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    d = (docs if docs.is_dir() else base_dir()) / "Svara Meetings"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = base_dir() / "Svara Meetings"
        d.mkdir(parents=True, exist_ok=True)
    return d


def dictionary_path() -> Path:
    """The personal dictionary (words/replacements/snippets). Its own file —
    unlike config.yaml it's machine-edited (quick-add, future auto-learn), and
    round-tripping YAML would destroy config.yaml's inline documentation."""
    return base_dir() / "dictionary.yaml"


def logs_dir() -> Path:
    d = base_dir() / "logs"
    try:
        d.mkdir(exist_ok=True)
    except OSError:
        pass
    return d
