"""Configuration loading — config.yaml deep-merged over sane defaults."""

import copy
import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "model": {
        "name": "base.en",              # ANY Whisper model or HF CT2 repo id (see config.yaml)
        "device": "cpu",                # cuda | cpu | auto (setup switches GPU machines to cuda)
        "compute_type": "int8",         # GPU: int8_float16 (~1.5GB) or float16; CPU: int8
        "language": "en",               # ISO code, or null for auto-detect
        "task": "transcribe",           # transcribe (write what you said) |
                                        #   translate (any language in, English out)
        "stream_language": "en",        # language for LIVE partials when language is
                                        #   null — auto-detect is unreliable on the
                                        #   sub-second buffers streaming works with
        "beam_size": 2,                 # final-pass beam: 2 = good, 1 = fastest, 5 = default
        "partial_beam_size": 2,         # live streaming beam: 2 balances speed + accuracy
        "initial_prompt": None,         # optional vocabulary hint for the decoder
        "download_root": None,          # None = default HuggingFace cache
        "batched": "auto",              # auto | off — BatchedInferencePipeline for
                                        #   the FINAL pass (faster-whisper >=1.1).
                                        #   Falls back silently if unsupported.
        "batch_size": 8,
    },
    "asr": {
        "backend": "faster-whisper",    # the only one today; see mywhisper/asr/
    },
    "recording": {
        "mode": "hold_to_record",       # hold_to_record | press_to_toggle
        "hotkey": "right alt",          # single keys get long-press behavior; combos toggle
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
            # Semantic endpointing: at the silence threshold, look at what was
            # actually said. "…and" is someone thinking; "…the team." is
            # someone finished. Keeps listening through mid-clause pauses.
            "semantic": False,
            "max_silence_ms": 2500,     # hard ceiling — an unfinished sentence
                                        #   can never hold the recording open
        },
    },
    "logging": {
        # OFF by default. On, every dictation is written to logs/mywhisper.log
        # in plain text — which outlives history.retention_hours and gets
        # pasted into bug reports. Only for debugging, and Svara says so.
        "debug_transcripts": False,
        "max_log_mb": 10,
    },
    "injection": {
        "method": "type",               # type (Win32 SendInput) | paste (clipboard + Ctrl+V)
        "append_space": True,           # trailing space so consecutive dictations join nicely
        "restore_clipboard": True,      # (paste) restore previous clipboard content after
        "targets": {},                  # {"exe": "type|paste|shift_insert|terminal"}
                                        #   explicit override, wins over the lists below
        "terminal_apps": None,          # None = the built-in list (injection.resolver)
        "shift_insert_apps": None,      # editors whose Ctrl+V is claimed (Cursor, VS Code…)
        "terminal_newline": "space",    # space | shift_enter | literal — how newlines are
                                        #   sent at a shell prompt. "space" can never submit.
        "terminal_paste": True,         # clipboard insert (fast) vs per-char typing (slow)
        "warn_on_elevated": True,       # tell the user when the target runs as admin
    },
    "locale": {
        "typography": "auto",           # auto | off — per-language spacing rules
        "english_variant": "en-US",     # en-US | en-GB | en-CA | en-AU | en-NZ | en-IN
        "romanize": "never",            # never | auto | always — Devanagari → Latin
        "numbered_lists": True,         # "first… second… third…" → 1. 2. 3.
    },
    "cleanup": {
        "level": "light",               # none | light | medium | high (one dial:
                                        # light=fillers, medium=+backtrack,
                                        # high=+LLM rewrite when Ollama is up)
        "strip_fillers": True,          # regex removal of um/uh/erm...
        "expressive": {                 # voice-aware formatting
            "enabled": True,
            "caps_ratio": 2.5,          # segment ≥2.5× the utterance median → CAPS
        },
        "llm": {
            "enabled": False,           # force-on; level "high" also uses it when a
                                        # local server is detected
            "api": "auto",              # auto | ollama | openai (LM Studio, llama.cpp…)
            "url": "http://localhost:11434",
            "openai_url": "http://localhost:1234/v1",  # LM Studio's default server
            "openai_model": None,       # None = first model the server reports
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
    "dictionary": {
        "words": [],                    # names/jargon boosted during recognition
        "replacements": {},             # {"heard": "typed"} exact fixes, post-STT
        "snippets": {},                 # {"spoken trigger": "expanded text"}
        "spoken_punctuation": False,    # "period"/"comma"/"new line" → . , \n
        # Watches corrections you make to text Svara typed and SUGGESTS
        # dictionary entries. Never adds one on its own; suggestions wait in a
        # review queue. Off by default — it reads text Svara did not produce.
        "auto_learn": False,
        "auto_learn_threshold": 3,      # same correction N times, across ≥2 sessions
    },
    "history": {
        "enabled": True,                # local dictation log (history.db)
        "retention_hours": 0,           # 0 = keep forever; e.g. 24 = a day
    },
    "context": {
        "enabled": True,                # look at the focused app per dictation
        "title_hotwords": True,         # window-title nouns → recognition boost
        "chat_no_period": True,         # drop the trailing period in chat apps
        "chat_apps": ["slack.exe", "discord.exe", "whatsapp.exe",
                      "telegram.exe", "ms-teams.exe", "signal.exe"],
        "styles": {},                   # {"slack.exe": "casual, friendly"} —
                                        # tone hint for the LLM cleanup
        # Reads the text just before your caret so mid-sentence dictation is
        # not capitalised. Off by default: this reads text Svara did not
        # produce. Never logged, never stored, dropped after each utterance.
        "read_caret_text": False,
        "caret_chars": 200,
    },
    "shortcuts": {
        # Win+Alt family on purpose: Shift+Alt is the Windows keyboard-layout
        # toggle on multi-layout machines — a chord that flips the user's
        # input language as a side effect is not a shortcut, it's a trap.
        "paste_last": "<cmd>+<alt>+z",      # re-paste the last dictation
        "copy_last": "<cmd>+<alt>+x",       # copy it instead
        "polish": "<cmd>+<alt>+p",          # rewrite SELECTED text (needs local LLM)
        "scratchpad": "<cmd>+<alt>+s",      # toggle the notes window
        "view_diff": "<cmd>+<alt>+o",       # review what the last transform changed
        "dictionary": None,                 # e.g. "<cmd>+<alt>+d": the word editor
        "command_key": None,                # e.g. "f9": hold + speak an instruction
    },
    "update": {
        "check": True,                  # look for new releases in the background
        "hours": 24,                    # how often
    },
    "transforms": {
        "polish_prompt": None,          # custom Polish instruction (None = default)
        "max_chars": 8000,              # selection size limit for transforms
        # Slots 1-9. Slot 1 defaults to Prompt Engineer unless you claim it.
        # Each: {name, prompt | builtin, hotkey, samples: [paths]}
        "slots": {
            1: {"name": "Prompt Engineer", "builtin": "prompt_engineer",
                "hotkey": "<cmd>+<alt>+1"},
        },
        "auto_after_dictation": None,   # slot number → runs on every dictation
        "preview": "on_request",        # auto (confirm every rewrite) |
                                        #   on_request (view_diff shortcut) | off
    },
    "streaming": {
        "mode": "live",                 # live (types words in real time as you speak)
                                        # | preview (live text in the pill) | off
        "interval_ms": 180,             # how often to re-transcribe while recording
        "min_audio_s": 0.35,            # don't start until this much audio exists
        "commit_policy": "local_agreement",  # local_agreement | adaptive
        "hold_back": 1,                 # words held back after two passes agree
        "confident_after": 12,          # (adaptive) agreement run that earns hold_back=0
        "max_window_s": 30,             # cap the re-decoded window; past this, trimming
                                        #   gets more aggressive so pass time stays flat
                                        #   through speech with no pauses (0 = no cap)
        "context_prompt_words": 0,      # feed the last N typed words back to the
                                        #   decoder as context (0 = off; measure with
                                        #   --bench before turning it on — it can also
                                        #   induce repetition)
    },
    "audio": {
        "sample_rate": 16000,
        "block_size": 512,
        "input_device": None,           # None = system default mic (see --list-devices)
        "gain": 1.0,                    # software mic boost (whisper mode uses 3.0)
        "device_policy": "preferred",   # preferred (honour input_device) |
                                        #   system_default (follow Windows) |
                                        #   external_first (auto-switch to a headset
                                        #   or dock mic the moment one appears)
    },
    "scratchpad": {
        "enabled": True,                # the Win+Alt+S notes window (tabs + versions)
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


def merged_dictionary(cfg: dict) -> dict:
    """config.yaml's dictionary section overlaid with dictionary.yaml (the
    machine-managed personal file): words union, replacements/snippets merge
    (dictionary.yaml wins on conflicts)."""
    from .paths import dictionary_path
    base = copy.deepcopy(cfg.get("dictionary") or DEFAULTS["dictionary"])
    p = dictionary_path()
    if not p.is_file():
        return base
    try:
        with open(p, "r", encoding="utf-8") as f:
            over = yaml.safe_load(f) or {}
        if not isinstance(over, dict):
            raise ValueError("dictionary root must be a mapping")
        base["words"] = list(dict.fromkeys(
            list(base.get("words") or []) + list(over.get("words") or [])))
        for key in ("replacements", "snippets"):
            merged = dict(base.get(key) or {})
            merged.update(over.get(key) or {})
            base[key] = merged
        if "spoken_punctuation" in over:
            base["spoken_punctuation"] = bool(over["spoken_punctuation"])
    except Exception as e:  # noqa: BLE001 — a broken dictionary must not kill startup
        log.error("Failed to parse %s (%s) — using config.yaml's dictionary only.",
                  p, e)
    return base


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
