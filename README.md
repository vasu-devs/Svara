<div align="center">

# Svara

**Private voice dictation that runs on your own machine.**

Speak in any app. Text appears at your cursor. Nothing leaves your GPU.
A free, local, open-source alternative to cloud dictation tools.

[Website](https://vasu-devs.github.io/Svara/) · [Download](https://github.com/vasu-devs/Svara/releases) · [Report an issue](https://github.com/vasu-devs/Svara/issues)

</div>

---

## What it is

Svara is a system-wide dictation app for Windows. Double-tap `Right Alt`, speak,
and your words are typed at the cursor in whatever app you are using. Everything
runs on your device with faster-whisper on your GPU, so your audio is never
uploaded anywhere.

- **Private by architecture.** Transcription happens locally. There is no server to send audio to. Works offline.
- **Fast.** `large-v3-turbo` on CTranslate2. On an RTX 4060 laptop, 5 seconds of speech transcribes in about 0.3s using ~1.2 GB VRAM.
- **Streaming.** Words appear as you speak, roughly a second behind your voice.
- **Works everywhere.** System-wide text injection drops text into any focused app.
- **A UI you will enjoy.** Twelve themes, eight sound visualizers, ten backgrounds, a draggable pill that dodges your cursor, and a few surprises.
- **Always on, safe.** Lives in the tray, restarts itself if it crashes, and uses a poll-only hotkey with no global keyboard hook.

## Quick start (from source)

```bat
setup.bat            :: creates a Python 3.11 venv and installs dependencies
run.bat --doctor     :: verifies mic, CUDA runtime, and GPU transcription
MyWhisper.bat        :: start it (look for the mic icon in the tray)
```

Then double-tap `Right Alt` and speak. Everything is configurable in `config.yaml`.

## Build a shippable app

```bat
build.bat
```

Produces `dist/Svara/` (a self-contained folder with the executable and all
dependencies, including the CUDA runtime). Zip it and send it. Users unzip and
double-click. No Python required. See `SHIP.md` for details.

## How it works

| Stage | Tech |
|---|---|
| Speech to text | faster-whisper on CTranslate2, `large-v3-turbo` at int8 |
| Voice activity | Silero VAD with a pre-roll ring buffer |
| Hotkey | poll-only via `GetAsyncKeyState`, no system keyboard hook |
| Text injection | Win32 `SendInput` and clipboard paste |
| Overlay | per-pixel alpha via Pillow and `UpdateLayeredWindow` |
| Packaging | PyInstaller |

## Website

The landing page lives in [`docs/`](docs/) and is a static site served via
GitHub Pages. The hero features a live recreation of Svara's flowing-strings
pill, running the same visualizer math as the app.

## Requirements

- Windows 10 or 11
- An NVIDIA GPU for the fast path (CPU fallback works, just slower)

## Docs in this repo

- `PLAN.md` / `Plan.html` — the research and architecture behind the project
- `SHIP.md` — how to build and distribute
- `config.yaml` — every setting, documented inline

## License

Open source. Runs on faster-whisper. Your voice stays with you.
