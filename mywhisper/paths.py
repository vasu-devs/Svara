"""Where MyWhisper reads/writes user files (config, state, logs).

Frozen (.exe): next to the executable, so users can edit config.yaml and keep
state/logs beside the app. Source run: the project root.
"""
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


def state_path() -> Path:
    return base_dir() / "state.json"


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
