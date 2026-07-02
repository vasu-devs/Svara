"""Where MyWhisper reads/writes user files (config, state, logs).

Frozen (.exe): next to the executable, so users can edit config.yaml and keep
state/logs beside the app. Source run: the project root.
"""
import sys
from pathlib import Path


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return base_dir() / "config.yaml"


def state_path() -> Path:
    return base_dir() / "state.json"


def logs_dir() -> Path:
    d = base_dir() / "logs"
    try:
        d.mkdir(exist_ok=True)
    except OSError:
        pass
    return d
