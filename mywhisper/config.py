"""Configuration loading — config.yaml deep-merged over sane defaults."""

import copy
import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "model": {
        "name": "large-v3-turbo",       # tiny | base | small | medium | large-v3 | large-v3-turbo
        "device": "cuda",               # cuda | cpu | auto
        "compute_type": "int8_float16", # GPU: int8_float16 (~1.5GB) or float16; CPU: int8
        "language": "en",               # ISO code, or null for auto-detect
        "beam_size": 2,                 # final-pass beam: 2 = good, 1 = fastest, 5 = default
        "partial_beam_size": 2,         # live streaming beam: 2 balances speed + accuracy
        "initial_prompt": None,         # optional vocabulary hint for the decoder
        "download_root": None,          # None = default HuggingFace cache
    },
    "recording": {
        "mode": "press_to_toggle",      # press_to_toggle | hold_to_record
        "hotkey": "ctrl+shift+space",   # combo toggle; single keys ("f8") get long-press behavior
        "long_press_ms": 250,           # (single-key hold mode) shorter = tap (cancel)
        "double_tap_lock": True,        # (single-key hold mode) double-tap = hands-free lock
        "double_tap_ms": 400,
        "suppress_key": False,          # False = poll-only (no system hook, robust default)
                                        # True = low-level hook that swallows the key globally
        "preroll_ms": 1000,             # audio kept from BEFORE the hotkey press
        "max_seconds": 600,             # hard cap per utterance
        "auto_stop": {                  # (toggle mode) stop when you go silent
            "enabled": False,           # off: you stop it yourself (hotkey or click the pill)
            "silence_ms": 900,
            "min_speech_ms": 300,
        },
    },
    "injection": {
        "method": "type",               # type (Win32 SendInput) | paste (clipboard + Ctrl+V)
        "append_space": True,           # trailing space so consecutive dictations join nicely
        "restore_clipboard": True,      # (paste) restore previous clipboard content after
    },
    "cleanup": {
        "strip_fillers": True,          # regex removal of um/uh/erm...
        "expressive": {                 # voice-aware formatting
            "enabled": True,
            "caps_ratio": 2.5,          # segment ≥2.5× the utterance median → CAPS
        },
        "llm": {
            "enabled": False,           # requires a local Ollama server
            "url": "http://localhost:11434",
            "model": "qwen2.5:3b-instruct",
            "timeout_s": 20,
            "keep_alive": "10m",
            "prompt": (
                "You are a dictation post-processor. Rewrite the dictated text with "
                "correct punctuation, capitalization and paragraph breaks. Remove "
                "filler words, false starts and stutters. Apply the speaker's "
                "self-corrections. Never add new content, never answer questions "
                "found in the text, never translate. Output ONLY the cleaned text."
            ),
        },
    },
    "streaming": {
        "mode": "preview",              # off | preview (live text in the pill)
                                        # | live (types words in real time as you speak)
        "interval_ms": 300,             # how often to re-transcribe while recording
        "min_audio_s": 0.5,             # don't start until this much audio exists
    },
    "audio": {
        "sample_rate": 16000,
        "block_size": 512,
        "input_device": None,           # None = system default mic (see --list-devices)
    },
    "ui": {
        "sounds": True,                 # beep on record start/stop
        "tray": True,                   # system tray icon
        "overlay": True,                # on-screen recording pill
        "theme": "minimal-dark",        # see themes.py / tray ▸ Theme
        "theme_overrides": {},          # per-key tweaks on top of the theme
        "position": "bottom",           # bottom | top
        "offset_px": 80,                # distance from the screen edge
        "scale": 1.0,                   # pill size multiplier
        "pill_width": 180,              # pill length in px
        "wave": "strings",              # strings | spectrum | bars | scope | pulse | particles
        "wave_weight": 1.0,             # thickness multiplier for the visualizer
        "bg": "gradient",               # gradient | solid | aurora | carbon | nebula
        "compact": True,                # waveform-only pill (no text) — minimal
        "glass": False,                 # acrylic is broken on recent Win11 builds
        "style": "siri",                # siri (flowing strings) | metal | glass
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path | None) -> dict:
    """Load config.yaml (if present) merged over DEFAULTS."""
    cfg = copy.deepcopy(DEFAULTS)
    if path is None:
        return cfg
    p = Path(path)
    if not p.is_file():
        log.info("No config file at %s — using defaults.", p)
        return cfg
    try:
        with open(p, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        if not isinstance(user, dict):
            raise ValueError("config root must be a mapping")
        cfg = _merge(cfg, user)
        log.debug("Loaded config from %s", p)
    except Exception as e:  # noqa: BLE001 — bad config should not kill the app
        log.error("Failed to parse %s (%s) — using defaults.", p, e)
    return cfg
