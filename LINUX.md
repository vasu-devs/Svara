# Svara on Linux (Wayland / Hyprland)

A source build of the same app, tuned for the lowest footprint that still wins
on accuracy and latency on a CPU. Nothing Windows-specific was removed; the
platform seams below pick a Linux implementation at import time.

```sh
./run.sh            # first run creates .venv and downloads the models (~250 MB)
./run.sh --test 3   # record 3 s from the mic, print the transcript, exit
./run.sh --bench    # latency + WER on this machine (bench/corpus)
./run.sh -v         # verbose log; logs/mywhisper.log always has the full one
```

Then, in any text field, either **hold the Copilot key** and
speak (the island shows the words, they land in one paste when you let go),
or **double-tap** it (a soft sound answers) and the words land at your
cursor as you talk; tap once, click the island, or stay quiet for 8 s to
finish. Quit with `systemctl --user stop svara`.

## Requirements

| Need | Why | On CachyOS |
|---|---|---|
| Hyprland | it owns the keyboard, so it fires the hotkey for us; set `input:numlock_by_default = true` so Svara's virtual keyboard matches your Num Lock (otherwise each dictation flips the lock state and a lock-key OSD flashes) | present |
| `wl-clipboard` | paste path and non-ASCII text | present |
| `/dev/uinput` writable by you | the virtual keyboard that types | an ACL already grants it; otherwise `sudo usermod -aG input $USER` and a udev rule |
| Python 3.13 with Tk, `uv` | venv; Tk only for the optional windows | the mise Python 3.13 has Tk 9 |
| `portaudio` | mic capture through PipeWire's ALSA bridge | present |

## How the Windows pieces map

| Windows | Linux | Where |
|---|---|---|
| Win32 `GetAsyncKeyState` poller | Hyprland press + release binds registered at startup with `hyprctl eval 'hl.bind(...)'`, each echoing `down`/`up` into `$XDG_RUNTIME_DIR/svara-hotkey.fifo`; the same `LongPressMachine` decides hold/tap/double-tap. Binds are removed at exit. | `mywhisper/hotkey_hyprland.py` |
| `SendInput` | uinput virtual keyboard (python-evdev). US-layout keycodes; anything outside printable ASCII goes through the clipboard instead. | `mywhisper/injector_wayland.py` |
| Win32 clipboard + Ctrl+V / Shift+Insert | `wl-copy` / `wl-paste` + the same chords from uinput; previous clipboard restored after 0.5 s | same |
| `GetForegroundWindow` exe name | `hyprctl -j activewindow` app-id (`kitty`, `code`, `firefox`), so the per-app rules and the terminal safety rules apply unchanged | `mywhisper/context/win.py` |
| Layered-window pill | the Quickshell dynamic island (`~/.config/quickshell/island`): Svara writes `$XDG_RUNTIME_DIR/svara-island.json` (state, live words, mic level) and `shell.qml` watches it. Without `island.service` a Hyprland notification marks the open mic instead. | `mywhisper/overlay.py` |
| Tray toasts | `notify-send` | `app.py::_notify` |
| Named mutex | `flock` on `$XDG_RUNTIME_DIR/svara.lock` | `__main__.py` |

Not available on Linux (by design, for now): the tray menu and the Tk settings
windows, chord shortcuts (`shortcuts:`) and mouse push-to-talk (both pynput),
meeting mode (WASAPI loopback), the GPU path (this laptop's NVIDIA driver was
mismatched at port time; `model.device: cuda` plus the CUDA wheels should work
once it is healthy). The dictation key is consumed by the compositor while
Svara runs, exactly like `suppress_key: true` on Windows.

Trying it without a key press:

```sh
echo down > $XDG_RUNTIME_DIR/svara-hotkey.fifo; sleep 2; echo up > $XDG_RUNTIME_DIR/svara-hotkey.fifo
```

## Engine choice

`config-linux.yaml` is the only file `run.sh` adds on top of the code
defaults. The engine was picked by `--bench` on this machine (i7-13650HX, CPU
int8, 3 reference clips, 59 s of audio):

| Engine | Params | Peak RSS | First word | Partial p95 | Final p95 | WER |
|---|---|---|---|---|---|---|
| **Moonshine base** (chosen) | 61M | 721 MB | 54 ms | 456 ms | 708 ms | **5.56%** |
| Moonshine tiny | 27M | 464 MB | 23 ms | 264 ms | 350 ms | 11.94% |
| faster-whisper base.en int8 (Windows default) | 74M | 734 MB | 290 ms | 497 ms | 514 ms | 8.33% |
| faster-whisper tiny.en int8 | 39M | 556 MB | 223 ms | 563 ms (over budget) | 660 ms | 11.94% |
| hybrid: Moonshine base + base.en final | 61M + 74M | 1070 MB | 56 ms | 454 ms | 776 ms | 8.33% |
| hybrid: Moonshine base + small.en final | 61M + 244M | 1462 MB | 55 ms | 511 ms (over budget) | 2283 ms | 4.17% |
| hybrid: Moonshine base + distil-small.en final | 61M + 166M | 1462 MB | 39 ms | 314 ms | 1088 ms | 11.11% |

Moonshine base is the only engine that is both faster to the first word and
more accurate than the Windows default, at a smaller size. Moonshine tiny is
the lowest-footprint option if RAM matters more than the extra 6 points of
WER: set `asr.moonshine: tiny`. Moonshine is English-only and ignores the
dictionary's hotword boost (the personal replacements still apply in the
cleanup pipeline); for another language set `asr.backend: faster-whisper`.
Full logs: `bench/results/`.

small.en as the final pass is the most accurate thing measured (4.17%), but it
costs a 2.3 s wait at the end of every dictation, doubles memory and pushes the
live partials over budget. In live mode the words you see typed come from the
streaming engine anyway; the final pass only repairs the tail. So Moonshine
base stays. If you dictate long passages and the end-of-utterance wait does not
bother you, `asr.backend: hybrid` with `model.name: small.en` is the accuracy
option.

## Inline preview at the caret (input method)

Where the focused app speaks the Wayland text-input protocol, Svara acts as
the input method (`mywhisper/ime_wayland.py`, zwp_input_method_v2, the same
seat fcitx/ibus would take): the live words appear *inside* the field as
preedit text, drawn by the app in its own preview style, replaced silently
as sentences are polished, and committed once when you finish. No
keystrokes, no backspacing, and it works while a modifier is held, so even
push-to-talk previews inline. Apps that take part: GTK and Qt apps, kitty,
Firefox, and Chromium/Electron apps started with `--enable-wayland-ime`
(Brave: add it to `~/.config/brave-flags.conf`; an Electron AppImage such as
T3 Code needs it on its command line). Everywhere else the keystroke path
below is used. `injection.inline_preview: false` turns it off. The log says
`inline preview armed` at start and the island shows only the bars while a
preview is inline.

## Dictation flow: words at the cursor, sentences polished in place

`config-linux.yaml` runs the stream and the polish at the same time:

1. The last few seconds are decoded every ~200 ms: by **Moonshine base**
   (CPU, 61M, up in 1.2 s) for the first seconds after a cold start, then by
   **Whisper large-v3-turbo on the GPU** as soon as it has loaded (0.2-0.3 s
   per window whatever its length, and far better on accents). Words two
   passes agree on are *committed* and typed at your cursor at once
   (`streaming.mode: live`), raw, into any app: T3, a browser, a terminal.
2. Audio whose words are all committed is trimmed at the next pause. That
   audio is final, so `mywhisper/incremental.py` collects it until it has
   about 8 s, decodes it again with **Whisper large-v3-turbo on the RTX
   4060** (int8_float16, 0.33 s for 9 s of audio) with the words before it as
   the decoder's prompt, and runs the cleanup pipeline, local LLM included,
   over each completed sentence group of 14+ words. Two guards keep your
   words: a decode that hears fewer than half the words the stream heard
   keeps the stream's words, and a polish that drops a leading or trailing
   sentence (small models do) is refused and the span stays unpolished
   (`drops_content` in `pipeline/llm.py`; the log says `SVARA-LLM-002`).
3. A polished sentence that changes *words* replaces its raw run on screen:
   Svara backspaces from the first changed character and retypes
   (`LiveScreen` in `streaming.py`). A polish that only changes case or
   punctuation is held back and applied once, when you finish, so the text
   does not jump while you talk. "Do 2+2, no, I meant 3+3" becomes "Do 3+3." in the text
   field a few seconds after you said it. In a terminal the polished text's
   newlines become spaces, so nothing can ever press Enter at a prompt.
4. **Spoken edits** work on screen at once: "remove the last five words",
   "delete the last sentence", "scrap that", "cut the last part" erase
   exactly those words (`apply_edit_commands` in `pipeline/text_rules.py`),
   and the finalizer applies the same rule to the text it polishes, so the
   command never comes back. All of one pass's appends, edits and polished
   rewrites go out as a single backspace-and-retype (`_sync_screen`).
5. Finishing is instant: at the tap or release the island hides, queued
   polish work is dropped (`IncrementalFinalizer.stop_now`), only the audio
   since the last trim is decoded (~0.3 s on the GPU) so the word you were
   finishing is kept, and the unpolished last stretch gets the instant
   cleanup (dictionary, punctuation, edit commands) without the LLM. Done in
   0.3-0.7 s after release. Sentences that finished polishing while you spoke
   keep their polish.
6. Release costs the tail only: the last few seconds of audio and one short
   polish call, however long you talked. The log line says how much was
   finalized while you were still speaking.

`recording.hotkey` is the Copilot key (it sends Shift+Super+F23); a comma
list such as `right alt, super + shift + f23` would bind several keys to the
same gestures. `recording.mode:
hold_to_record`: a lone tap does nothing, holding is push-to-talk, a double
tap is hands-free, so the key is never held while Svara types (a held Alt turns every keystroke into a shortcut, which is
why `hold_to_record` only shows the words in the island and pastes them on
release). Three ways to finish: tap Right Alt, click the island (its square
is the stop button; it writes `stop` into the hotkey FIFO), or just stop
talking: `recording.auto_stop.hands_free_silence_ms: 8000` finishes after
8 s of quiet, so a missed tap can never leave the mic open.

Live windows are decoded without the dictionary hotwords and skipped when
they hold no voice: both made Whisper invent the hint phrase on a quiet
window ("T3 Code" → "C4 code C4 code"). A hypothesis made of one or two
words repeated is dropped for the same reason.

`cleanup.level: high` removes fillers, applies self-corrections and "scratch
that", and hands each span to a local LLM when one answers. With no LLM it
behaves exactly like `medium`. The LLM is Ollama with `qwen2.5:7b-instruct`
(the 3B dropped whole sentences while polishing),
run as a user service so it survives reboots and needs no sudo:

```sh
systemctl --user enable --now ollama   # unit: ~/.config/systemd/user/ollama.service
ollama pull qwen2.5:7b-instruct        # ~4.7 GB, once
```

Ollama frees the model after 15 quiet minutes (`cleanup.llm.keep_alive`) and
Svara warms it again the moment you press the key (on the RTX 4060 a
sentence takes well under a second). If you would rather never wait, set
`cleanup.level: medium`.

The dynamic island shows five bars of your voice (`Recorder.bands()`, a
small FFT 15× a second) and the words (in grey: a preview) only while they
are not landing at the cursor, i.e. while the key is held or in preview
mode; during live typing it shows just the bars, so the text never appears
twice. A quiet dot while the last chunk is polished, then the final
text with a check for a second. Text typed at the cursor is plain keystrokes:
no app-independent way exists to colour it, so grey-vs-final lives in the
island only. The island only
picks the file up if it exists when `island.service` starts, so Svara creates
it at launch and `shell.qml` creates it itself when missing.

The GPU model needs the CUDA runtime in the venv (done once, ~800 MB):

```sh
uv pip install --python .venv/bin/python nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

`cuda_setup.py` dlopens those libraries when the GPU model loads, so no
`LD_LIBRARY_PATH` is needed. VRAM budget on the 8 GB card: the 7B polish
model (4.7 GB) + Whisper turbo (1.6 GB) + the desktop ≈ 6.6 GB. Full
`large-v3` was measured no better than turbo on this voice and would not fit
next to the 7B. The EarPods mic records around -40 dBFS, hence
`audio.gain: 1.8`; `dictionary.words` lists the project vocabulary Whisper
should favour. Without the GPU, `model: {name: base.en,
device: cpu, compute_type: int8}` is the CPU final pass measured below.

### One paste instead of live typing

`streaming.commit_policy: adaptive` with `hold_back: 0` lands a word as
soon as the hypothesis has settled instead of holding one word back forever;
the in-place rewrite repairs the rare wrong guess.

`streaming.mode: preview` keeps everything above but types nothing until
release: the island previews the words and the polished text lands in one
paste. `streaming.mode: "off"` (quoted: bare `off` is YAML for false) is the
classic batch decode.

`cleanup.expressive.enabled` is off in the Linux config: on the EarPods mic the
loudness-to-CAPS heuristic fired on every word.

## GPU

The RTX 4060 is the real accuracy lever: `large-v3-turbo` on CUDA decodes a
live window in well under the CPU's Moonshine time and is far more robust to
accents. It needs the NVIDIA kernel module and userspace to match; after a
driver upgrade that means a reboot (`nvidia-smi` says "Driver/library version
mismatch" until then). Then install the CUDA wheels into the venv and switch
the model:

```sh
uv pip install --python .venv/bin/python nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

```yaml
model: {name: large-v3-turbo, device: cuda, compute_type: int8_float16}
asr:   {backend: faster-whisper}
```

## Voice onboarding (record your voice, measure, correct)

`./run.sh --onboard` toggles a recording session in the running Svara
(design: `docs/voice-onboarding-design.md`). An ordinary window
(`~/.config/quickshell/island/Onboarding.qml`, driven by the island's JSON
feed, layout B "teleprompter", `docs/onboarding-window.png`) shows how to read this block, the line in large serif, the next line faintly below, a rail of the seven styles,
with Skip and Pause. The session is hands-free: it listens on its own, a
pause of a second after you read saves the take and shows the next line; half a
minute without a word is discarded and it listens afresh. The key is not used.
Every take is checked against its line with the live engine before it is
saved (`voice_session.matches`, word error rate at most 0.6): talking to
someone else, a cough or "hello" shows "That didn't sound like the line.
Once more?" and the line stays. About 100 takes: all 60 lines in your normal voice, then 20 fast and 20
quiet (8-10 minutes of speech). Progress is saved per take under
`~/.local/share/svara/voice/` (`clips/*.wav`, `lines.jsonl`), so the session
can be paused (`--onboard` again) and resumed. A take under 0.6 s is treated
as a key slip and the line stays.

Then score your own voice:

```sh
.venv/bin/python bench/voice_measure.py            # WER per engine and style
```

It writes `results.json` and `corrections.yaml` (the misses seen twice or
more, as `dictionary.replacements` to paste into `config-linux.yaml`). The
fine-tune stage of the design is not built yet.

## Adapting the model to your voice

Training lives in its own venv so its PyTorch can never clash with the CUDA
libraries the running Svara uses:

```sh
uv venv --python 3.13 .venv-train
uv pip install --python .venv-train/bin/python torch transformers peft accelerate ctranslate2 faster-whisper numpy
.venv-train/bin/python -m mywhisper.voice_adapt            # train, convert, A/B on held-out lines
.venv-train/bin/python -m mywhisper.voice_adapt --apply    # …and point config-linux.yaml at it if it wins
```

`mywhisper/voice_adapt.py` LoRA-tunes Whisper large-v3-turbo on the
onboarding takes. The bottom 24 of its 32 encoder layers run once per clip and
are cached on the GPU, so training only runs the top 8 encoder layers and the
4 decoder layers. It first asks Ollama to unload the polish model (Svara warms
it again on the next dictation). Every fifth line is held out; the merged and
converted model is scored against the stock one on those takes, and it is
kept only if it wins by at least a point of word error rate. A run takes about
a minute end to end on the 4060 (cache 3 s, train 12 s for 3 epochs on 35 takes,
convert 4 s, the rest is scoring both models in Svara's own venv, whose CUDA 12
runtime the training venv's PyTorch cannot load). The verdict is
in `~/.local/share/svara/voice/adapt.json`; a kept model lives under
`~/.local/share/svara/models/`.

## Installing from a release

```sh
tar xzf Svara-0.8.0-linux.tar.gz && mv svara-0.8.0-linux ~/Svara && cd ~/Svara
./run.sh --test 3                                   # first run builds .venv and fetches models
mkdir -p ~/.config/systemd/user && cp linux/svara.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now svara.service
```

`linux/svara.service` expects the folder at `~/Svara` (edit `ExecStart` if not).
`linux/quickshell/Onboarding.qml` is the voice-onboarding window for a
Quickshell shell: copy it next to your `shell.qml`, add
`Onboarding { dict: <your feed object> }`, and feed it
`$XDG_RUNTIME_DIR/svara-island.json` the way the island section above does.

## Always on, light when idle

`svara.service` (`~/.config/systemd/user`, enabled under
`graphical-session.target` like the island) starts Svara with the session and
restarts it if it dies. `model.unload_after_min: 10` in `config-linux.yaml`
keeps that cheap: nothing is loaded until you press Right Alt, the engine loads
in about 2.5 s while the mic already buffers your words, and after ten quiet
minutes it is dropped again. Ollama does the same with `keep_alive: "15m"`,
and Svara warms it the moment you press the key.

```sh
systemctl --user enable --now svara.service
systemctl --user restart svara.service     # after changing config or code
journalctl --user -u svara.service -f      # or logs/mywhisper.log
```

```ini
# ~/.config/systemd/user/svara.service
[Unit]
Description=Svara dictation
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=0
[Service]
ExecStart=%h/Svara/run.sh
Restart=always
RestartSec=1
RestartSteps=6
RestartMaxDelaySec=30
[Install]
WantedBy=graphical-session.target
```

## Tests

```sh
.venv/bin/python -m unittest tests.test_linux_desktop tests.test_injection tests.test_pipeline tests.test_cleanup tests.test_config_integrity tests.test_redact tests.test_streaming -q
```

`test_install`, `test_hotkey_gesture` and `test_hotkey_real_keys` are
Windows-only and fail on Linux by design.
