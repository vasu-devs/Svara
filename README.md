<div align="center">

# Svara

**Private voice dictation that runs on your own machine.**

Speak in any app. Text appears at your cursor. Nothing leaves your GPU.
A free, local, open-source alternative to cloud dictation tools like Wispr Flow.

[Website](https://vasu-devs.github.io/Svara/) · [Download](https://github.com/vasu-devs/Svara/releases) · [Report an issue](https://github.com/vasu-devs/Svara/issues)

![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0a0a0d)
![python](https://img.shields.io/badge/python-3.11-0a0a0d)
![engine](https://img.shields.io/badge/engine-faster--whisper-22d3ee)
![license](https://img.shields.io/badge/license-MIT-38ff88)

</div>

---

## Contents

- [What it is](#what-it-is)
- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [How you use it](#how-you-use-it)
- [Configuration](#configuration)
  - [Models](#models)
  - [Languages and translation](#languages-and-translation)
  - [Expressive formatting: shout-to-caps, fillers, LLM polish](#expressive-formatting)
  - [Hotkey and recording modes](#hotkey-and-recording-modes)
  - [Streaming](#streaming)
  - [Themes and visualizers](#themes-and-visualizers)
- [How it works](#how-it-works)
- [Building a shippable app](#building-a-shippable-app)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [The website](#the-website)
- [Contributing](#contributing)
- [License](#license)

---

## What it is

Svara is a system-wide dictation app for Windows. Double-tap `Right Alt`, speak,
and your words are typed at the cursor in whatever app you are using — Slack, VS
Code, a browser, a terminal, anything. Every stage runs on your device with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) on your GPU, so your
audio is never recorded to disk and never uploaded anywhere.

It is the local, free answer to cloud dictation tools: no account, no
subscription, no telemetry, and it works offline.

## Features

- **Runs entirely on your machine.** Audio is captured, transcribed, and
  discarded in memory. There is no server to send it to. Works with the network
  cable unplugged.
- **Fast on your GPU.** `large-v3-turbo` on CTranslate2 at int8 in ~1.5 GB VRAM.
  On an RTX 4060 laptop, 5 seconds of speech transcribes in roughly 0.3 s.
- **Live streaming.** Words appear at your cursor as you talk, about a second
  behind your voice — not only after you stop.
- **90+ languages.** Dictate in any language Whisper understands, or let it
  **auto-detect** what you speak each time.
- **Speak-to-translate.** Flip one switch and talk in any language; Svara writes
  clean **English** at your cursor.
- **Any Whisper model.** From `tiny` to `distil-large-v3` to `large-v3-turbo` —
  trade speed for accuracy to fit whatever GPU (or CPU) you have.
- **Shout to CAPITALISE.** Raise your voice on a word and it lands IN CAPS.
  Loudness is measured against the median of the whole utterance, so it is
  shout-proof — only genuine emphasis is capitalised.
- **Cleaned up as you talk.** Automatic punctuation, filler removal (`um`, `uh`),
  and self-corrections. Optional local-LLM polish via [Ollama](https://ollama.com)
  — still fully offline.
- **Works in every app.** System-wide text injection places words at the cursor
  anywhere you can type.
- **A UI you enjoy.** Eight live sound visualizers, pop-culture themes (Matrix,
  Cyberpunk, Sakura, Evangelion, Saiyan, Vaporwave, plus clean minimal), and a
  draggable pill overlay that dodges your cursor so it never covers your text.
- **Always on, safe for your system.** Lives in the tray, restarts itself if it
  crashes, and uses a **poll-only** hotkey with no global keyboard hook, so it
  never interferes with your typing.

## Requirements

- **Windows 10 or 11**
- **An NVIDIA GPU** for the fast path (a CPU fallback works automatically, just
  slower). ~2 GB of free VRAM for `large-v3-turbo`; less for smaller models.
- **Python 3.11** if running from source. Not needed for the packaged release.

The CUDA runtime ships as pip wheels — you do **not** need to install the CUDA
toolkit or cuDNN system-wide.

## Quick start

### Option A — packaged release (no Python)

1. Download the latest zip from [Releases](https://github.com/vasu-devs/Svara/releases).
2. Unzip and run `Svara.exe`. Look for the mic icon in the tray.
3. Double-tap `Right Alt` and speak.

The first launch downloads the speech model once (~1.5 GB); after that Svara runs
fully offline.

### Option B — from source

```bat
setup.bat            :: creates a Python 3.11 venv and installs dependencies
run.bat --doctor     :: verifies mic, CUDA runtime, and GPU transcription
MyWhisper.bat        :: start it (look for the mic icon in the tray)
```

Then double-tap `Right Alt` and speak. Everything is configurable in
[`config.yaml`](config.yaml).

## How you use it

Default hotkey is **`Right Alt`**:

| Gesture | What happens |
|---|---|
| **Hold** `Right Alt` | Push-to-talk. Speak while held; release to finish and type. |
| **Double-tap** `Right Alt` | Hands-free lock. Speak as long as you like; **tap once** to stop and type. |
| **Tap** (quick) | Cancels without typing. |

The pill overlay shows a live meter while listening. Drag it anywhere; click the
dot to collapse it. Right-click the tray icon for the theme picker and toggles.

You can change the hotkey (single keys, combos, or `caps lock` / `f8` / etc.) in
`config.yaml`. See [Hotkey and recording modes](#hotkey-and-recording-modes).

## Configuration

Everything lives in [`config.yaml`](config.yaml), documented inline. Missing keys
fall back to sensible defaults. Highlights below.

### Models

```yaml
model:
  name: large-v3-turbo   # tiny | base | small | medium | distil-large-v3
                         # | large-v3 | large-v3-turbo
  device: cuda           # cuda | cpu | auto
  compute_type: int8_float16   # GPU: int8_float16 (fastest) | float16 · CPU: int8
```

| Model | VRAM (int8) | Speed | Accuracy |
|---|---|---|---|
| `tiny` / `base` | ~1 GB | fastest | rough |
| `small` / `medium` | ~1–2 GB | fast | good |
| `distil-large-v3` | ~1.5 GB | fast | very good |
| **`large-v3-turbo`** (default) | ~1.5 GB | fast | excellent |
| `large-v3` | ~3 GB | slower | best |

Any multilingual model (everything except the `*.en` variants) understands 90+
languages. Svara falls back to CPU automatically if CUDA is unavailable.

### Languages and translation

```yaml
model:
  language: en        # ISO code (en, hi, es, fr, de, it, pt, ja, ko, zh, ru, ar, ...)
                      #   or null to AUTO-DETECT the language each time
  task: transcribe    # transcribe = write it in the language you spoke
                      # translate  = speak ANY language, get ENGLISH at your cursor
  stream_language: en # language used for live partials when language is null
```

- **Dictate in another language:** set `language: hi` (Hindi), `es`, `ja`, etc.
- **Auto-detect:** set `language: null`. The final pass detects your language; live
  partials use `stream_language` (auto-detect is unreliable on tiny live buffers).
- **Translate as you speak:** set `task: translate`. Talk in any language and clean
  English is typed at your cursor.

### Expressive formatting

Svara does not just transcribe — it formats what you say based on how you say it.

```yaml
cleanup:
  strip_fillers: true         # remove um / uh / erm ...
  expressive:
    enabled: true
    caps_ratio: 2.5           # a word 2.5x louder than the median → TYPES IN CAPS
  llm:                        # optional local-LLM cleanup (needs Ollama running)
    enabled: false            # true after: ollama pull qwen2.5:3b-instruct
    model: qwen2.5:3b-instruct
```

- **Shout to capitalise.** Loudness is compared against the median volume of the
  whole utterance, so background noise or a naturally loud voice will not trigger
  it — only real emphasis does.
- **Filler removal.** `um`, `uh`, false starts, and stutters are cleaned on the fly.
- **LLM polish (optional).** Point Svara at a local [Ollama](https://ollama.com)
  model for punctuation, paragraphing, and self-correction — the "Wispr magic",
  fully offline. It never adds content, answers questions, or translates.

### Hotkey and recording modes

```yaml
recording:
  hotkey: right alt          # single keys (f8, caps lock, num 0, ...) or combos
                             #   (ctrl+shift+space, ctrl+win, alt+v)
  mode: hold_to_record       # hold_to_record | press_to_toggle
  double_tap_lock: true      # double-tap = hands-free lock
  suppress_key: false        # false = poll-only, NO global keyboard hook (recommended)
  preroll_ms: 1000           # audio kept from BEFORE you press (never lose the first word)
  max_seconds: 600           # safety cap per utterance
```

`suppress_key: false` is the recommended, robust default: the key is observed but
not hidden from other apps, so there is no system-wide keyboard hook and no input
lag. A pre-roll ring buffer keeps ~1 s of audio from before you pressed, so the
first word is never clipped.

### Streaming

```yaml
streaming:
  mode: live          # live = typed at your cursor in real time · preview = shown
                      #   in the pill, typed after you stop · off = batch
  interval_ms: 180    # how often the rolling buffer is re-transcribed
  min_audio_s: 0.35   # audio to gather before the first word appears
```

Live mode uses a LocalAgreement strategy: a word is committed only when two
consecutive passes agree on it, which keeps the streamed text stable instead of
flickering.

### Themes and visualizers

Eight live sound visualizers (strings, bars, spectrum, scope, pulse, particles,
beam, pixels) and a set of themes:

```yaml
ui:
  theme: minimal-dark   # minimal-dark | minimal-light | matrix | cyberpunk
                        # | sakura | evangelion | saiyan | vaporwave
```

The tray icon has a live theme picker, and your choice persists across restarts.

## How it works

| Stage | Tech |
|---|---|
| Audio capture | `sounddevice`, 16 kHz mono, with a pre-roll ring buffer |
| Voice activity | Silero VAD (bundled) trims silence, prevents clipped words |
| Speech to text | faster-whisper on CTranslate2, `large-v3-turbo` at int8 |
| Streaming | rolling re-transcription + LocalAgreement word commit |
| Expressive | median-loudness → CAPS, filler regex, optional Ollama pass |
| Hotkey | poll-only via `GetAsyncKeyState`, **no** system keyboard hook |
| Text injection | Win32 `SendInput` and clipboard paste |
| Overlay | per-pixel alpha via Pillow and `UpdateLayeredWindow` |
| Packaging | PyInstaller |

The model is warmed up at launch (one dummy transcribe) so CUDA/cuDNN kernels are
compiled before your first real dictation, making the first word instant.

## Building a shippable app

```bat
build.bat
```

Produces `dist/Svara/` — a self-contained folder with the executable and all
dependencies, including the CUDA runtime. Zip it and send it; users unzip and
double-click, no Python required. See [`SHIP.md`](SHIP.md) for details.

## Project structure

```
mywhisper/            the Python app (module name kept as mywhisper)
  app.py              orchestration: audio → transcribe → stream → inject
  transcriber.py      faster-whisper wrapper (model, language, task, warmup)
  audio.py            mic capture + pre-roll ring buffer
  hotkey.py           poll-only key listener + long-press/double-tap state
  injector.py         Win32 SendInput / clipboard paste
  cleanup.py          fillers, shout-to-caps, optional LLM polish
  overlay.py          the draggable live pill overlay
  tray.py             system tray icon, theme picker, toggles
  themes.py           theme palettes
  cuda_setup.py       loads bundled CUDA runtime wheels
  doctor.py           mic / CUDA / GPU self-check
config.yaml           every setting, documented inline
web/                  the Next.js marketing site (Vercel + GitHub Pages)
```

## Troubleshooting

- **`run.bat --doctor`** checks your mic, CUDA runtime, and a real GPU transcribe.
  Run it first.
- **CUDA / cuDNN errors.** faster-whisper ≥ 1.1 uses CTranslate2 ≥ 4.5, which needs
  **cuDNN 9** (the pip wheel `nvidia-cudnn-cu12>=9,<10`, already in
  `requirements.txt`). The old "use cuDNN 8" advice applies only to older
  CTranslate2.
- **No GPU / falls back to CPU.** That is expected and still works; set
  `device: cpu` and a smaller `model.name` for a better CPU experience.
- **First word cut off.** Increase `recording.preroll_ms`.
- **List microphones.** `python -m mywhisper --list-devices`, then set
  `audio.input_device`.

## The website

The marketing site lives in [`web/`](web/) — a **Next.js + Framer Motion** app with
a live recreation of Svara's flowing-strings pill running the same visualizer
math as the desktop app. It deploys to **Vercel** (set the root directory to
`web/`) and is mirrored to **GitHub Pages** at
https://vasu-devs.github.io/Svara/ via the
[`Deploy site to GitHub Pages`](.github/workflows/deploy.yml) Actions workflow,
which builds `web/` on every push to `main`.

## Contributing

Issues and pull requests are welcome. If you are filing a bug, `run.bat --doctor`
output and your `config.yaml` help a lot. If you are adding a feature, keep the
"nothing leaves the machine" guarantee intact.

## License

MIT. Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[CTranslate2](https://github.com/OpenNMT/CTranslate2), and
[Silero VAD](https://github.com/snakers4/silero-vad). Your voice stays with you.
