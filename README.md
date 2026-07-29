<div align="center">

# Svara

**Private voice dictation that runs on your own machine.**

Speak in any app. Text appears at your cursor. Nothing leaves your GPU.
A free, local, open-source alternative to cloud dictation tools like Wispr Flow.

[Website](https://vasu-devs.github.io/Svara/) · [Download](https://github.com/vasu-devs/Svara/releases) · [Report an issue](https://github.com/vasu-devs/Svara/issues)

![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-0a0a0d)
![python](https://img.shields.io/badge/python-3.11-0a0a0d)
![engine](https://img.shields.io/badge/engine-faster--whisper-22d3ee)
![license](https://img.shields.io/badge/license-AGPL--3.0-38ff88)

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
  - [Where the text lands](#where-the-text-lands)
  - [Locale, spelling and Hinglish](#locale-spelling-and-hinglish)
  - [Transforms and slots](#transforms-and-slots)
  - [Hotkey and recording modes](#hotkey-and-recording-modes)
  - [Streaming](#streaming)
  - [Themes and visualizers](#themes-and-visualizers)
- [How it works](#how-it-works)
- [Testing](#testing)
- [Privacy](#privacy)
- [Benchmarks](BENCH.md)
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
  cable unplugged. What Svara reads and writes is spelled out in
  [`PRIVACY.md`](PRIVACY.md) — including the three features that are off by
  default because they read more than your voice.
- **Fast, and it tells you how fast.** `run.bat --bench` measures time-to-first-word,
  p50/p95 streaming latency, WER and real-time factor **on your hardware**, and
  writes the result with your machine's spec attached. Defaults are CPU-first
  (`base.en`, int8); switch to `large-v3-turbo` on CUDA from the tray for the
  accurate path (~1.5 GB VRAM).
- **Live streaming.** Words appear at your cursor as you talk, about a second
  behind your voice — not only after you stop.
- **It types where you actually work.** Terminals and TUI coding agents (Claude
  Code, Codex, Cursor, Windsurf) get line-safe insertion — a dictated paragraph
  can never press Enter for you. Cursor and VS Code get `Shift+Insert`, because
  they've claimed `Ctrl+V`. And when the target runs as **administrator**, Svara
  detects that Windows will silently discard the keystrokes, says so, and leaves
  your words on the clipboard instead of losing them.
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
- **A UI you enjoy.** Eight live sound visualizers and pop-culture themes (Matrix,
  Cyberpunk, Sakura, Evangelion, Saiyan, Vaporwave, plus clean minimal).
- **Gets out of your way, automatically.** The pill reads the **text caret** of
  the focused app (`GetGUIThreadInfo`, with a UI-Automation fallback for browsers
  and Electron) and slides aside the instant it would cover what you are typing,
  easing back home when the coast is clear. You can also just drag it anywhere.
- **Always on, safe for your system.** Lives in the tray, restarts itself if it
  crashes, and uses a **poll-only** hotkey with no global keyboard hook, so it
  never interferes with your typing.
- **Installs itself, survives every reboot.** First run copies Svara to
  `%LOCALAPPDATA%\Svara`, registers start-with-Windows and a Start Menu entry.
  Background **auto-update** downloads new releases; they apply only when you
  click "Restart to update" — and upgrades never re-run setup.
- **Your personal dictionary.** Boost recognition of names/jargon (hotwords),
  exact replacement fixes, spoken snippets ("my email" → the address), spoken
  punctuation and bullets. Quick-add from the Svara window; live reload.
- **It knows where it's typing — locally.** The focused app's window title
  feeds proper nouns into recognition per-dictation, and chat apps
  (Slack/Discord/WhatsApp…) lose the passive-aggressive trailing period.
  Nothing about your screen ever leaves the machine.
- **Never lose a dictation.** Crash-safe audio recovery on the next launch, a
  searchable local **History** window, and `Win+Alt+Z` to re-paste the last
  dictation into any field.
- **Written the way your language is written.** French gets its narrow
  non-breaking spaces before `; ! ? »` and a full one before `:` — suppressed
  inside terminals, times and URLs, where an invisible character is a bug you
  can't see. CJK loses the Latin-style spacing around `。！？、`. English picks a
  side: **en-US / en-GB / en-CA / en-AU / en-IN** (Canadian correctly means
  British *colour* with American *organize*), with the `-ise`/`-ize` exception
  list that stops "surprize" and "advertize". Optional **Hinglish** romanisation
  writes Hindi in Latin script and leaves the English words alone.
- **AI on tap, not by default.** A Cleanup dial (None/Light/Medium/High),
  "scratch that" retractions, per-app tone styles, and an optional
  hold-and-speak **command key** — powered by your own local LLM server, plain
  rules when you don't want one. Svara auto-detects **Ollama** and any
  **OpenAI-compatible server (LM Studio, llama.cpp, Jan)**.
- **Nine transform slots.** Hotkey- and voice-addressable rewrites of your own
  design ("apply concise"). Slot 1 is **Prompt Engineer** — it turns a rambled
  thought into a structured prompt. Each slot can learn your voice from 1–5
  samples of your own writing. `Win+Alt+O` shows exactly what a transform
  changed — inserted words in one ink, deleted words struck through in another;
  set `transforms.preview: auto` and nothing lands until you accept it.
- **Whisper mode & scratchpad.** 3× mic gain for speaking softly at 2 a.m., and
  a `Win+Alt+S` note window with tabs and a version log that tags every save as
  *typed*, *dictated* or *transform* — so a rewrite is always undoable.
- **It can learn your words, but only if you say so.** Opt-in auto-learn watches
  the corrections *you* make and **suggests** dictionary entries after seeing the
  same fix three times across two sessions. It never adds one on its own.

## Requirements

- **Windows 10 or 11**
- **An NVIDIA GPU** for the fast path (a CPU fallback works automatically, just
  slower). ~2 GB of free VRAM for `large-v3-turbo`; less for smaller models.
- **Python 3.11** if running from source. Not needed for the packaged release.

The CUDA runtime ships as pip wheels — you do **not** need to install the CUDA
toolkit or cuDNN system-wide.

## Quick start

### Option A — packaged release (no Python)

1. Download the latest `Svara.exe` from [Releases](https://github.com/vasu-devs/Svara/releases).
2. Double-click it. Svara **installs itself once** to `%LOCALAPPDATA%\Svara`,
   registers itself to **start with Windows**, and appears in the tray — the
   downloaded file is just the installer and can be deleted afterwards.
3. Double-tap `Right Alt` and speak.

After that it's hands-off: Svara is already running after every reboot, ready
the moment you double-tap the hotkey. (Turn off "Start with Windows" in the
tray menu or the Svara window if you'd rather launch it yourself; run with
`--portable` to skip self-install entirely.)

The first launch downloads the speech model once; after that Svara runs
fully offline. Your settings live in `%LOCALAPPDATA%\Svara\config.yaml`.

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
  name: base.en          # tiny | base | small | medium | distil-large-v3
                         # | large-v3 | large-v3-turbo  (+ .en variants)
  device: cpu            # cuda | cpu | auto
  compute_type: int8     # GPU: int8_float16 (fastest) | float16 · CPU: int8
```

**The shipped default is `base.en` on CPU**, and first-run setup upgrades it if
your machine can do better. That is deliberate: `base.en` was measured as the
best live-streaming trade-off on a laptop CPU — a more accurate model that can't
finish a partial pass inside the streaming interval makes dictation feel worse,
not better. The tray's Model and Device menus switch live, and `--bench` will
tell you what each one actually costs on your hardware.

| Model | Memory (int8) | Speed | Accuracy |
|---|---|---|---|
| `tiny` / **`base.en`** (default) | ~1 GB | fastest | rough / decent English |
| `small` / `medium` | ~1–2 GB | fast | good |
| `distil-large-v3` | ~1.5 GB VRAM | fast | very good |
| `large-v3-turbo` | ~1.5 GB VRAM | fast | excellent |
| `large-v3` | ~3 GB VRAM | slower | best |

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
- **LLM polish (optional).** Point Svara at a local LLM for punctuation,
  paragraphing, and self-correction — the "Wispr magic", fully offline. It
  auto-detects [Ollama](https://ollama.com) or any OpenAI-compatible server
  ([LM Studio](https://lmstudio.ai), llama.cpp, Jan) and never adds content,
  answers questions, or translates.

### Personal dictionary, fixes, and snippets

Teach Svara your words — names, jargon, and shortcuts it should know. Tray icon
▸ **Dictionary ▸ Edit…**, add entries, then **Dictionary ▸ Reload** (no restart):

```yaml
dictionary:
  words: [Svara, Vasudev, CTranslate2]   # boosted during recognition itself
  replacements:                          # exact fixes applied after transcription
    "swara": "Svara"                     #   (case-insensitive, whole words only)
    "get hub": "GitHub"
  snippets:                              # say the trigger, type the block
    "my email": "vasu@example.com"
    "sign off": "Best,\nVasudev"
  spoken_punctuation: false              # true → "period"/"comma"/"new line"
                                         #   type . , ⏎ instead of the words
```

- **`words`** feed faster-whisper's hotword boosting — the model literally hears
  your vocabulary better, including in live streaming mode.
- **`replacements`** and **`snippets`** run last in the cleanup pipeline, so your
  exact spellings always win — even over the optional LLM polish.

### Where the text lands

Svara picks an injection strategy from the app you are dictating into, because
one setting cannot cover all of them.

```yaml
injection:
  method: type              # the default for ordinary text fields
  terminal_newline: space   # space | shift_enter | literal
  warn_on_elevated: true
  targets: {}               # override anything: { "myapp.exe": shift_insert }
```

- **Terminals and TUI coding agents** get line-safe insertion. A newline at a
  shell prompt is the Enter key, so by default newlines collapse to spaces and
  the trailing one is always stripped — a dictated paragraph arrives as one
  editable line and *you* press Enter. Use `shift_enter` for multi-line prompts
  in Claude Code and similar, where Shift+Enter is a soft break.
- **Cursor, VS Code and Windsurf** get `Shift+Insert`, because `Ctrl+V` is
  claimed there (in a shell it's readline's quoted-insert, not paste).
- **Elevated windows.** Windows silently discards synthetic input aimed at a
  higher-integrity process *and reports success*, so without a check your
  dictation would vanish with no error anywhere. Svara detects it, tells you
  once, and leaves the text on your clipboard.

Live streaming is disabled for terminals and elevated windows — they get one
clean insertion when you finish, because a half-typed line at a shell prompt is
a line you can accidentally submit.

### Locale, spelling and Hinglish

```yaml
locale:
  typography: auto          # French/CJK spacing rules
  english_variant: en-US    # en-US | en-GB | en-CA | en-AU | en-NZ | en-IN
  romanize: never           # never | auto (chat + terminals) | always
  numbered_lists: true      # "First… Second… Third…" → 1. 2. 3.
```

All rules, no model, no latency. The English variants share an exception list so
`-ise`/`-ize` conversion never produces "surprize" or "advertize", and
`Colorado` never becomes `Colourado`. French spacing is suppressed inside
terminals, times (`12:30`), URLs and `` `code spans` `` — an invisible U+202F in
a shell command is an error naming a character you cannot see. Also on the tray:
**Writing ▸ English spelling** and **Writing ▸ Hinglish**.

Hinglish romanisation is off by default and Hunterian-style: readable and lossy.
It leaves the English half of a code-mixed sentence untouched.

### Transforms and slots

```yaml
transforms:
  preview: on_request       # auto | on_request | off
  auto_after_dictation: null
  slots:
    1: {name: Prompt Engineer, builtin: prompt_engineer, hotkey: "<cmd>+<alt>+1"}
    2:
      name: Concise
      prompt: "Tighten this without losing meaning."
      hotkey: "<cmd>+<alt>+2"
      samples: [samples/my-writing.txt]   # 1-5 files, 50-500 words each
```

Select text anywhere and press a slot's hotkey, or hold the command key and say
"apply concise". `Win+Alt+O` shows what the last transform changed — inserted
words in green ink, deleted words struck through in red, both drawn from the
Svara window palette so they stay readable on it — and `preview: auto` gates
every rewrite behind that view. Samples teach a slot your
voice; Svara enforces the word bounds and a total prompt budget, because five
500-word samples on a local 3B model is a latency cliff.

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
| Audio capture | `sounddevice`, 16 kHz mono, pre-roll ring buffer, policy-driven device choice |
| Voice activity | Silero VAD (bundled) trims silence, prevents clipped words |
| Speech to text | faster-whisper on CTranslate2, int8 |
| Streaming | rolling re-transcription + LocalAgreement word commit |
| Context | Win32 foreground exe/title, integrity level, optional UIA caret text — all local |
| Cleanup | an ordered **stage chain**: fillers → retractions → lists → LLM → typography → romanisation → per-app rules → your dictionary |
| Expressive | median-loudness → CAPS, filler regex, optional local-LLM pass |
| Hotkey | poll-only via `GetAsyncKeyState`, **no** system keyboard hook |
| Text injection | strategy per target: `SendInput`, clipboard, `Shift+Insert`, or line-safe terminal insertion |
| Overlay | per-pixel alpha via Pillow and `UpdateLayeredWindow` |
| Packaging | PyInstaller |

The model is warmed up at launch (one dummy transcribe) so CUDA/cuDNN kernels are
compiled before your first real dictation, making the first word instant.

[`ARCHITECTURE.md`](ARCHITECTURE.md) has the full module map, the pipeline's
ordering invariants, the threading rules and the caching strategy.

## Testing

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

273 tests, about 17 seconds. Most are pure functions with no audio, model or
network; `tests/test_livepath.py` loads a real model and pushes audio through
the real streaming path end-to-end, asserting that nothing is duplicated or
dropped at the stream/tail boundary.

`tests/test_redact.py` is the privacy guarantee: it runs real text through the
real pipeline with logging captured and fails if any of it reaches the log.

```bat
run.bat --bench          :: latency + WER on YOUR machine → bench/results/*.json
```

Exits non-zero if the latency budget (TTFW ≤ 300 ms, p95 ≤ 500 ms) is missed.
Drop `<name>.wav` + `<name>.txt` pairs into `bench/corpus/` for accuracy numbers;
without a corpus it measures latency and says WER was not measured rather than
printing a flattering zero.

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
  app.py              composition root + recording lifecycle
  transcriber.py      faster-whisper wrapper (model, language, task, warmup)
  audio.py            mic capture + pre-roll ring buffer + crash spill
  audio_policy.py     which microphone, and when to switch
  hotkey.py           poll-only key listener + long-press/double-tap state
  pipeline/           the cleanup stage chain — one stage per module
    base.py           Stage protocol, UtteranceContext, fail-safe Chain
    locale.py         French/CJK spacing, en-US/GB/CA spelling
    transliterate.py  Devanagari → Latin (Hinglish)
    lists.py          spoken enumerations → 1. 2. 3.
  injection/          a strategy per target app (terminal, Shift+Insert, …)
  injector.py         the Win32 primitives underneath it
  context/            foreground app, integrity level, opt-in caret text
  transforms/         slots 1-9, style samples, word diff, command mode
  redact.py           keeps transcripts out of the log; stable error codes
  bench.py            --bench: TTFW, p50/p95, WER, RTF
  history.py          scratchpad.py   dictionary_io.py   autolearn.py
  overlay.py          the draggable live pill overlay
  tray.py             system tray icon, theme picker, toggles
  howto_ui.py         Svara window, history, scratchpad, dictionary, diff
  themes.py           theme palettes
  cuda_setup.py       loads bundled CUDA runtime wheels
  doctor.py           mic / CUDA / GPU self-check
config.yaml           every setting, documented inline
ARCHITECTURE.md       module map, invariants, threading, caching
PRIVACY.md            what is read and written, and how to turn it off
PLAN.md               the roadmap this structure was built for
web/                  the Next.js marketing site (Vercel + GitHub Pages)
```

## Privacy

Nothing you dictate leaves your machine — see [`PRIVACY.md`](PRIVACY.md) for the
complete accounting: every file Svara writes, every network connection it can
open (a model download, an update check, and your own local LLM), and why it
carries no compliance certification (there is no processor to certify).

Two things worth knowing here:

- **The log file holds no transcripts.** Up to v0.4.1 it kept an 80-character
  preview of every dictation, which outlived the history retention you
  configured. As of 0.5.0 it records only shape — `«redacted» 12w/68c` — plus
  stable error codes you can quote in an issue. `tests/test_redact.py` enforces it.
- **Three features are off by default** because they read more than your voice:
  `context.read_caret_text` (the text before your cursor),
  `dictionary.auto_learn` (the corrections you make — suggest-only, never
  silent), and `logging.debug_transcripts`.

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

**GNU AGPL-3.0** — see [`LICENSE`](LICENSE). You are free to use, study, modify,
and share Svara; if you run a modified version as a network service, the AGPL
requires you to offer that modified source to its users.

Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[CTranslate2](https://github.com/OpenNMT/CTranslate2), and
[Silero VAD](https://github.com/snakers4/silero-vad). Your voice stays with you.
