# Svara architecture

How a dictation becomes text, and where to put a change.

Read [`PRIVACY.md`](PRIVACY.md) for what crosses which boundary, and
[`PLAN.md`](PLAN.md) for why the 0.5 structure looks like this.

---

## The path of one utterance

```
  hotkey ──► Recorder ──────────────► streamer ──► injector ──► your app
   │         (pre-roll ring buffer)      │  live partials, LocalAgreement-2
   │                                     │
   └──► ContextProvider                  └──► queue ──► worker
          exe · title · locale                          │
          terminal? chat? elevated?                     ├─► Transcriber (faster-whisper)
          caret text (opt-in)                           ├─► Chain  (cleanup pipeline)
                │                                       ├─► Transformer (auto slot)
                └──────────► UtteranceContext ──────────┴─► TextInjector (per-target)
                             (one frozen value object,           │
                              shared by every stage)             └─► History · AutoLearner
```

The `UtteranceContext` is the spine. It is captured **once**, when recording
starts, and everything downstream is a pure function of it. That matters because
focus moves: if the user alt-tabs while Svara is transcribing, the text still
gets the formatting and injection strategy of the app they were actually
dictating into.

---

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | composition root + recording lifecycle. Builds the collaborators, wires the callbacks, owns the worker and streamer threads. |
| `audio.py` · `audio_policy.py` | mic capture, pre-roll ring buffer, crash spill. Policy decides *which* mic (`preferred` / `system_default` / `external_first`). |
| `hotkey.py` · `quickkeys.py` | the dictation key (poll-only state machine) and the chord shortcuts (pynput). |
| `asr/` | the recognition seam. `base.py` protocol + `Segment` · `faster_whisper.py` the default engine (batched final pass, warmup, CPU fallback). `transcriber.py` is the façade the app still calls. |
| `streaming.py` | the live-commit state machine: LocalAgreement policies, window trimming, and `align_remainder` for the stream/tail boundary. Pure — no audio, threads or Win32. |
| `endpoint.py` | semantic endpointing: is that pause a thought or an ending? |
| `context/` | `win.py` foreground exe+title · `elevation.py` integrity levels · `caret.py` opt-in UIA caret text · `__init__.py` composes `UtteranceContext`. |
| `pipeline/` | the cleanup stage chain. One stage per module. |
| `injection/` | strategy per target app. `injector.py` holds the Win32 primitives. |
| `transforms/` | slots 1–9, style samples, word diff, Polish, voice command mode. |
| `history.py` · `scratchpad.py` | SQLite stores. |
| `dictionary_io.py` · `autolearn.py` | dictionary file/CSV I/O, the auto-learn review queue, correction detection. |
| `redact.py` | transcript redaction + stable error codes. |
| `bench.py` | `--bench`: TTFW, p50/p95, WER, RTF. |
| `overlay.py` · `tray.py` · `howto_ui.py` · `setup_ui.py` · `themes.py` | UI. |
| `install.py` · `updater.py` · `paths.py` · `cuda_setup.py` · `doctor.py` | lifecycle and environment. |

---

## The cleanup pipeline

Declared in one place: `pipeline/__init__.py::build_chain()`. If you are adding
a text transformation, it goes in that list and nowhere else.

```
fillers → backtrack → numbered_lists → llm → locale → romanize
        → app_rules → continuation → personalizer
```

Three ordering constraints, each with a test in `tests/test_pipeline.py`:

1. **Fillers first.** Everything downstream works better on text without "um".
2. **Typography after the LLM.** French spacing and CJK spacing must see the
   *final* punctuation, not a draft of it.
3. **Personalizer last, always.** Everything upstream is a guess — Whisper
   guesses the word, the LLM guesses the phrasing, the locale rules guess the
   convention. The user's replacement table is not a guess. Nothing overrules it.

### Adding a stage

```python
class MyStage(BaseStage):
    name = "my_stage"
    min_level = 2                     # 0=none 1=light 2=medium 3=high

    def applies(self, ctx: UtteranceContext) -> bool:
        return not ctx.is_terminal    # most stages should ask this

    def run(self, text: str, ctx: UtteranceContext) -> str:
        return text.replace("x", "y")
```

Register it in `build_chain()` and write its unit test. The chain gives you two
guarantees for free, and both are load-bearing:

- **A raising stage cannot cost the utterance.** The exception is logged with
  `SVARA-PIPE-001` and the previous text carries forward. A regex bug must not
  eat the paragraph someone just spoke.
- **A stage cannot silently empty an utterance.** Returning `""` for non-empty
  input is treated as a bug and refused. Losing words is the worst failure this
  app has, so it fails closed.

---

## Injection strategies

`injection/resolver.py::classify()` maps an exe name to a strategy;
`TextInjector` resolves and delegates. This exists because one global "type or
paste" setting cannot express the real constraints:

| Target | Strategy | Why |
|---|---|---|
| ordinary text field | `SendInputStrategy` | char-perfect, clipboard untouched |
| long text / `method: paste` | `ClipboardPasteStrategy` | faster for bulk |
| Cursor, VS Code, Windsurf | `ShiftInsertStrategy` | they've claimed Ctrl+V |
| terminals, shells, TUI agents | `TerminalStrategy` | **a newline at a shell prompt is the Enter key** |
| elevated window | (blocked) | UIPI discards synthetic input *and reports success* |

`TerminalStrategy` is the one with teeth. Its entire job is that Svara can never
submit something the user didn't submit: newlines collapse to spaces by default,
the trailing newline is stripped in every mode, and command-shaped output gets a
"typed it, didn't run it" toast.

Elevated targets are not a strategy but a refusal: Svara puts the text on the
clipboard and explains once per app, because the alternative is the dictation
vanishing with no error anywhere.

Live streaming is disabled for both terminals and elevated windows
(`TextInjector.streams_into`) — a half-typed line at a shell prompt is a line
you can accidentally submit.

---

## Threads

| Thread | Lives for | Does |
|---|---|---|
| main | process | tray message pump (blocking) |
| `hotkey` / `quickkey-*` | process | key polling; callbacks dispatched off-thread |
| `monitor` | process | auto-stop, session cap, mic health, device policy |
| `worker` | process | drains the utterance queue: transcribe → clean → inject |
| `streamer` | one recording | rolling partial passes + LocalAgreement commit |
| `audio-spill` | process | writes recording audio to disk for crash recovery |
| `howto-ui` | first window onwards | **one** `tk.Tk()` root for the whole process, serving every window through a queue |
| `model-switch`, `update-check`, `recovery`, `command-mode`, `caret-context` | one task | short-lived workers |

Two rules that are easy to break:

- **Never create a second `tk.Tk()`.** `howto_ui` creates one root, once, on one
  persistent thread, and every window is a `Toplevel` on it. Re-initialising
  Tcl's Windows notifier across threads intermittently produces a window that
  the OS draws but never paints.
- **Never block a hotkey callback.** `QuickKeys` already dispatches each to its
  own thread; keep it that way or system-wide keyboard input stutters.

---

## Testing

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

273 tests, ~17 s. `tests/test_livepath.py` loads a real model and runs audio
through the real streaming path; everything else is pure and fast.

| Suite | Covers |
|---|---|
| `test_pipeline.py` | stage contract, ordering invariants, locale/Hinglish/list rules |
| `test_injection.py` | classification, terminal safety, elevation handling |
| `test_transforms.py` | slot registry, style samples, word diff |
| `test_dictionary_io.py` | CSV import/export, auto-learn queue, correction detection |
| `test_redact.py` | **the privacy guarantee** — no transcript reaches the log |
| `test_stores.py` | scratchpad + versions + migration, device policy, WER maths |
| `test_streaming.py` | commit policies, trimming, and the stream/tail boundary |
| `test_endpoint.py` | thinking-pause vs finished-sentence |
| `test_config_integrity.py` | config.yaml ↔ DEFAULTS agree; privacy gates default off |
| `test_cleanup.py` · `test_features.py` · `test_llm_backend.py` · `test_install.py` | pre-0.5 behaviour, unchanged |
| `test_livepath.py` | end-to-end: audio in, keystrokes out, history matches |

### Why `streaming.py` is a separate module

Deciding when a word is safe to type is the hardest logic here, and it used to
live inline in the streamer loop — untestable without a microphone and a model,
and impossible for the benchmark to model without reimplementing it. Which it
did, subtly wrong: the first harness never trimmed, so it reported ~1127 ms p95
where the app achieves ~913 ms.

Both problems have one fix. The policy is a pure function of (hypothesis,
previous hypothesis, committed words); `app.py` drives it with real audio,
`bench.py` drives it with recorded segments. A measurement can no longer
disagree with the thing it measures.

`align_remainder` is the other half. The finalising worker re-decodes the same
trimmed window, so its hypothesis *should* start with the words already on
screen — but it runs a different beam and occasionally tokenises the boundary
differently, at which point slicing by count lands mid-repeat and types
"push the code to to get hub". Matching by content instead of position fixes it,
and `test_livepath.py` now fails on *any* adjacent repeated word rather than the
three phrases it used to check.

### Caching strategy

| Cache | Where | Invalidated by |
|---|---|---|
| Whisper model weights | `~/.cache/huggingface` (or `model.download_root`) | never automatically; delete the directory |
| Loaded model + warm CUDA kernels | process memory | model/device switch (rebuilds a `Transcriber`, swaps atomically) |
| Local LLM backend probe | `LlmCleanup._backend` | 600 s when found, 60 s when missing — so starting Ollama mid-session is noticed quickly |
| Loaded LLM in Ollama | Ollama itself, via `keep_alive: 10m` | its own timer |
| Style samples | `TransformSlot._sample_text` | `registry.reload()` |
| Integrity level per pid | `elevation._cache`, bounded at 256 | `reset_cache()`; pids recycle |
| Personal dictionary rules | compiled regexes in `Personalizer` | `reload_dictionary()` — tray ▸ Dictionary ▸ Reload |

---

## Benchmarks

```bat
run.bat --bench
```

Measures TTFW, partial-pass p50/p95/max, final-pass latency, RTF and peak RSS;
adds WER/CER and dictionary-term recall when `bench/corpus/` holds `<name>.wav`
+ `<name>.txt` pairs. Results land in `bench/results/<sha>-<model>-<device>.json`
with the machine spec attached.

It exits non-zero when the latency budget (TTFW ≤ 300 ms, p95 ≤ 500 ms) is
missed, so it can gate a release. With no corpus it says WER was not measured
rather than printing a flattering zero.
