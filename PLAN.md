# Svara v0.5 → v1.0 — the plan to full Wispr parity and past it

**Status:** Phases 0–2 **implemented in v0.5.0**; Phase 3 (SOTA tier) open · **Written:** 29 Jul 2026 · **Baseline:** v0.4.1 (`7cde18f`)
**Companion docs:** [`ROADMAP.md`](ROADMAP.md) (what shipped) · [`ARCHITECTURE.md`](ARCHITECTURE.md) (how it's built) · [`PRIVACY.md`](PRIVACY.md) (what's read and written) · [`SHIP.md`](SHIP.md) (release process)

> **Implementation note (v0.5.0).** Everything in Phases 0, 1 and 2 below is
> built and tested — 273 tests, up from 74. The gap table in §1.3 is closed;
> §3's findings are fixed. The one deliberate deviation is **G14 clamshell**:
> reading the physical lid switch needs `RegisterPowerSettingNotification` and a
> message pump, and the case people describe as "clamshell" turned out to be
> "docked with an external mic", so it ships as `audio.device_policy:
> external_first` instead. §7 (Phase 3) is untouched and remains the roadmap.

---

## 0. How to read this

This plan is derived from a full architectural breakdown of Wispr Flow and the
real-time voice-intelligence ecosystem, mapped against **the Svara code as it
actually is today** (`mywhisper/`, 8,141 LOC, 74 tests).

Three things it deliberately does:

1. **Separates real gaps from fake ones.** A third of Wispr's feature list only
   exists because Wispr is a cloud SaaS. "Privacy Mode", "Private Cloud Sync",
   "Zero Data Retention agreements with subprocessors", "2,000 words/week" —
   Svara satisfies all of these by *construction*, not by feature. Building them
   would be building a cage and then a key for it.
2. **Fixes the architecture before adding to it.** Roughly 20 new behaviours want
   to attach to `cleanup.py` and `injector.py`. Both are currently fixed
   if-ladders. Bolting on is how you get a 2,500-line `app.py` nobody can change.
   Phase 1 exists to make Phase 2 cheap.
3. **Defines SOTA as a number, not a vibe.** The source report quotes
   `whisper-flow` at 275 ms mean latency / ~7% WER. Svara currently publishes no
   latency or accuracy figure at all. You cannot claim state of the art against a
   benchmark you have not run. Phase 0 is the harness.

---

## 1. Where Svara actually stands

### 1.1 Already shipped (no work needed)

| Wispr capability (from the report) | Svara today |
|---|---|
| Two-tier ASR → generative LLM post-processing | `CleanupPipeline` + `LlmCleanup` — Ollama **and** OpenAI-compatible (LM Studio/llama.cpp/Jan) |
| VAD, 16 kHz mono PCM ingestion | Silero VAD via faster-whisper, `audio.py` @ 16 kHz |
| Real-time partial/final streaming (`IsPartial` semantics) | `_streamer()` with LocalAgreement-2 word commit + segment trimming |
| Hotkey triggers, push-to-talk, hands-free lock | `hotkey.py` — poll-only, no global hook; hold / double-tap / tap-cancel |
| System-wide text injection | `injector.py` — SendInput UNICODE + clipboard paste |
| Filler removal, self-corrections, punctuation | `strip_fillers`, `apply_backtrack`, LLM stage |
| Custom dictionary (hotword boosting) | `dictionary.words` → faster-whisper `hotwords`, live in streaming too |
| Replacement rules ("Draught" → "Draft") | `dictionary.replacements`, applied **after** the LLM so user fixes always win |
| Snippets / spoken punctuation | `dictionary.snippets`, `_SPOKEN_PUNCT` |
| Per-app tone / context awareness | `appcontext.py` — exe + window-title proper nouns → per-utterance hotwords |
| Chat-app trailing-period suppression | `_strip_chat_period()` |
| Transcript history, paste-last | `history.py` SQLite + `Win+Alt+Z`/`X` |
| Transforms / Polish on selection | `transforms.py` — `Win+Alt+P`, plus optional voice Command Mode |
| Scratchpad | `Win+Alt+S`, autosaving note window |
| Session ceiling, crash recovery, auto-update, self-install | `app.py`, `updater.py`, `install.py` |
| 100+ languages, speak-to-translate | Whisper multilingual + `task: translate` |

### 1.2 Where Svara is already ahead (protect, don't trade away)

- **Wispr's context awareness uploads your screen.** Svara reads the same signal
  through Win32 locally. This is the single strongest differentiator in the
  product and every Phase-2 context feature must preserve it.
- **Offline.** Wispr has no offline mode — "transcription always occurs on the
  cloud". Svara works with the cable unplugged.
- **No account, no quota, no tier.** The report's entire pricing table is Svara's
  feature list, free.
- **Dual local-LLM backends.** Wispr routes to Gemini/OpenAI-class cloud models.
  Svara auto-detects Ollama *or* any OpenAI-compatible local server.

### 1.3 Real gaps — the work

Ranked by user-visible impact per unit of effort.

| # | Gap | Wispr behaviour | Svara today | Size |
|---|---|---|---|---|
| G1 | **Terminal / coding-tool injection** | Splits output into structured lines for Claude Code, Codex, Cursor, Windsurf; uses `Shift+Insert` where `Ctrl+V` is intercepted | One global `injection.method` for every app; long dictation lands as one line and can execute in a shell | **S** |
| G2 | **Elevation awareness** | Detects privilege boundary, tells the user to run elevated | Injection silently no-ops into an admin PowerShell — reads as "Svara is broken" | **S** |
| G3 | **Transform slots** | 9 slots; slot 1 reserved "Prompt Engineer"; slots 2–9 custom prompts | 1 Polish prompt + 1 voice command key | **M** |
| G4 | **Style-by-example** | 1–5 writing samples (50–500 words) per slot teach tone | none | **S** (rides on G3) |
| G5 | **Diff preview** | `Opt+O` inline overlay: additions highlighted, deletions struck | none — transforms replace text blind | **M** |
| G6 | **Locale typography** | fr narrow NBSP before `; : ? ! »`; CJK full-width spacing; en-US/GB/CA variants | none — no formatter layer exists | **M** |
| G7 | **Hinglish** | Romanises Hindi phonetics, formats English terms normally | none | **M** |
| G8 | **Auto-learned dictionary** | Watches post-dictation edits, proposes entries | roadmap item #1, deliberately unbuilt | **L** |
| G9 | **CSV dictionary import** | 2-column CSV, ≤1,000 entries / 3 MB | hand-edited YAML + quick-add box | **S** |
| G10 | **Dictionary table editor** | full table UI | quick-add only | **M** |
| G11 | **Scratchpad depth** | multi-tab, detachable, embedded images, version log tagged by source (Typed / Dictated / Transform) | single autosaving note | **M** |
| G12 | **Caret-adjacent context** | reads surrounding text for casing-aware continuation | window title only | **M** |
| G13 | **Auto-transform on finish** | status-bar bubble runs a chosen transform when dictation ends | none | **S** (rides on G3) |
| G14 | **Clamshell / device policy** | switches to external mic when the lid closes | auto-fallback on device *death* only | **S** |
| G15 | **Numbered-list detection** | "one… two… three…" → `1. 2. 3.` | roadmap item #3 | **S** |

### 1.4 Explicit non-goals (recording the decision, so it stops being re-litigated)

- **Privacy Mode / Private Cloud Sync toggles.** Meaningless locally. Svara's
  answer is "there is no cloud", not "there is a switch".
- **SOC 2 / ISO 27001 / HIPAA / ZDR.** These certify a data processor. Svara
  processes nothing off-device. The correct artifact is a one-page
  *"why Svara needs no compliance certification"* doc in the README — not an audit.
- **Mobile (iOS keyboard, Android accessibility bubble).** Desktop is the wedge,
  and the local-inference story does not survive a phone. Unchanged from `ROADMAP.md`.
- **Mid-sentence language switching.** Wispr punts on it too.
- **Word quotas / tiers / SSO / admin dashboards.** Not a SaaS.

---

## 2. What "SOTA" means here — and the numbers we commit to

"State of the art" is meaningless without an axis. Svara competes on three, and
should aim to *lead* on two and *match* on one.

| Axis | Metric | Report's reference point | Svara baseline | v1.0 target |
|---|---|---|---|---|
| **Latency** | time-to-first-word (TTFW), p50/p95 partial-commit latency | 275 ms mean, σ 84 ms, max 471 ms (M1, 16 GB) | **unmeasured** | TTFW < 300 ms; p95 commit < 500 ms |
| **Accuracy** | WER on a fixed held-out set, with and without dictionary boost | ~7.0% WER | **unmeasured** | ≤ 6% WER on the same set; ≥ 30% relative error cut on in-dictionary terms |
| **Output quality** | *does the text need editing after it lands* | Wispr's whole pitch | strong (levels + LLM + per-app rules) | **lead** — locale typography, terminal-safe injection, diff-reviewable transforms |
| **Privacy** | data leaving the device | none possible for a cloud product | already zero | **keep at zero, and stop leaking to local logs** (see §3.1) |

Two notes on honesty:

- **Report the distribution, not the mean.** The 275 ms ± 84 ms figure in the
  source has a 471 ms tail. p95 is what users feel. Svara publishes p50/p95/max.
- **State the hardware.** The report's numbers are Apple M1 / 16 GB. Svara ships
  a CPU-first default (`base.en`, `int8`) and a CUDA path. Every published number
  carries its machine, model, and compute type or it is marketing.

---

## 3. Findings from the current code that gate this plan

These came out of reading the v0.4.1 source. They are prerequisites, not opinions.

### 3.1 🔴 Dictated text is written to a plaintext log file

[`app.py:1021-1025`](mywhisper/app.py#L1021-L1025) logs an 80-character preview of
every dictation at `INFO`, and [`transforms.py:190`](mywhisper/transforms.py#L190)
logs each voice command verbatim:

```python
preview = text if len(text) <= 80 else text[:77] + "…"
log.info("✓ %.1fs audio → %d chars in %.2fs stt + %.2fs cleanup | %s", …, preview)
```

`logs/mywhisper.log` is unencrypted, unrotated, and outlives the History
retention policy the user configured. In a product whose entire promise is
"nothing leaves your machine", the passwords, medical notes, and private messages
people dictate should not be sitting in a text file that survives
`history.retention_hours: 24`.

**Fix (Phase 0, non-negotiable):** a `logging.Filter` that redacts transcript
content by default; previews only under an explicit `logging.debug_transcripts:
true` opt-in that also warns in the UI. Log *shape* — word count, duration,
timings — never content. This is exactly the "logs must never contain source,
secrets, or full payloads" standard, applied to the one thing Svara handles that
matters most.

### 3.2 🟠 `app.py` is a 1,166-line god object

It owns: recording lifecycle, the streaming loop, loudness→CAPS maths, model
switching, device switching, theme/wave/background cycling, dictionary file I/O,
state persistence, tray callbacks, update application, crash recovery, and window
launching. Phase 2 adds ~15 more behaviours to it.

**Fix (Phase 1):** decompose into a composition root plus injected collaborators
(§5.3). Not aesthetics — every Phase-2 feature otherwise edits the same file.

### 3.3 🟠 `CleanupPipeline.run()` is a fixed if-ladder

```python
if rank >= 1 and strip_fillers_enabled: text = strip_fillers(text)
if rank >= 2:                            text = apply_backtrack(text)
if use_llm:                              text = llm.run(text, style_hint)
return personalizer.apply(text)
```

Locale typography (G6), Hinglish (G7), numbered lists (G15), per-app formatters,
and the chat-period rule (currently stranded in `app.py`, outside the pipeline it
belongs to) all need a slot in this sequence. Five more `if`s makes ordering
implicit and untestable.

**Fix (Phase 1):** an ordered chain of declared stages (§5.1). This single
refactor converts "add a feature" into "register a stage + write its unit test",
and is the highest-leverage item in the plan.

### 3.4 🟠 Injection is one global method, not a per-target strategy

`TextInjector.method` is a single config string. G1, G2, and per-app newline
policy all need *per-target* behaviour.

**Fix (Phase 1):** `resolve(target) -> InjectionStrategy` (§5.2).

### 3.5 🟡 Free performance is being left on the table

- **`BatchedInferencePipeline` is unused.** faster-whisper ≥ 1.1 ships it;
  `transcriber.py` calls `model.transcribe()` directly. Meaningful speedup on the
  final pass for longer utterances. Free, in-dependency, measurable in Phase 0.
- **`condition_on_previous_text=False` everywhere.** Correct for avoiding
  hallucination loops, but it also discards continuation context. Feeding the last
  N committed words back as `initial_prompt` on each streaming pass is a cheap
  accuracy win — and is *the same mechanism* G12 (caret context) needs.
- **One `_lock` serialises partial and final passes.** On CPU that is a visible
  stall at the moment the user stops speaking — the worst possible moment.
- **The streamer holds back exactly one word** (`words[:agree-1]`). Alternative
  commit policies (AlignAtt-style attention, confidence thresholding) are a Phase-3
  experiment with a real latency payoff.

### 3.6 🟡 Docs have drifted from the code

`README.md` states `large-v3-turbo` / CUDA as the default; `config.yaml` ships
`base.en` / `cpu` / `int8` (correct — `base.en` measured best for live streaming).
A user reading the README gets the wrong performance model. Folded into Phase 4.

---

## 4. Phase 0 — Measure and harden *(prerequisite for every claim in §2)*

**Goal:** know the numbers, and stop leaking transcripts to disk.

### 0.1 Benchmark harness — `python -m mywhisper --bench`

New `mywhisper/bench.py`, plus `bench/` fixtures.

- **Corpus:** a small committed set of WAVs — LibriSpeech `test-clean` excerpt for
  comparability, plus ~20 self-recorded dictation-realistic clips (technical
  vocabulary, names, false starts, self-corrections) with reference transcripts.
  These are what the product is actually for; LibriSpeech alone flatters everyone.
- **Metrics:**
  - `TTFW` — hotkey press → first character injected.
  - Partial-commit latency p50 / p95 / max (mirrors the report's methodology, but
    reports the distribution).
  - WER + CER, overall and restricted to dictionary terms.
  - RTF (real-time factor) and peak RSS / VRAM.
- **Matrix:** every `(model, device, compute_type)` combination the setup wizard
  can produce.
- **Output:** `bench/results/<git-sha>-<machine>.json` + a rendered `BENCH.md`.
  The machine spec is part of every row.

**Exit criteria:** committed baseline numbers for the shipped default on at least
one CPU-only and one CUDA machine.

### 0.2 Transcript redaction in logs *(§3.1)*

- `logging.Filter` subclass; a single `redact()` helper for text-bearing log calls.
- Config: `logging.debug_transcripts: false` (default), surfaced in the UI with a
  plain-language warning when enabled.
- Stable error codes on every `log.error` (`SVARA-STT-001`, `SVARA-INJ-002`, …) so
  issues are diagnosable from a log the user is willing to paste.
- Log rotation with a size cap — unbounded logs are their own leak.

**Tests:** assert no test-corpus transcript string ever appears in captured log
output at default settings.

### 0.3 Quick perf wins, measured

Land `BatchedInferencePipeline` behind a config flag and A/B it with 0.1. Keep it
only if the harness says so. Same for the rolling `initial_prompt` continuation.

---

## 5. Phase 1 — Architecture *(makes Phase 2 cheap)*

No user-visible change. All 74 existing tests must pass untouched — this phase is
behaviour-preserving by definition.

### 5.1 Stage-chain cleanup pipeline

New package `mywhisper/pipeline/`.

```python
# pipeline/base.py
class Stage(Protocol):
    name: str
    def applies(self, ctx: UtteranceContext) -> bool: ...
    def run(self, text: str, ctx: UtteranceContext) -> str: ...
```

`UtteranceContext` is the missing value object — today the same facts are smeared
across `app.py` instance attributes (`_active_app`, `_active_title`, `_voice_rms`)
and ad-hoc kwargs:

```python
@dataclass(frozen=True)
class UtteranceContext:
    app: str                  # focused exe, lowercase
    title: str                # window title
    locale: str               # "en-GB", "fr-FR", "hi-Latn" …
    style_hint: str | None    # per-app tone
    is_terminal: bool
    is_chat: bool
    caret_prefix: str | None  # Phase 2, G12
    duration_s: float
    word_count: int
```

Declared order (each stage its own module, each with unit tests):

| # | Stage | Source |
|---|---|---|
| 1 | `FillerStage` | existing `strip_fillers` |
| 2 | `BacktrackStage` | existing `apply_backtrack` |
| 3 | `NumberedListStage` | **new — G15** |
| 4 | `LlmStage` | existing `LlmCleanup` |
| 5 | `LocaleTypographyStage` | **new — G6** |
| 6 | `TransliterationStage` | **new — G7 (Hinglish)** |
| 7 | `AppRulesStage` | **moved** — absorbs `_strip_chat_period` out of `app.py` |
| 8 | `PersonalizerStage` | existing — **stays last, always** |

The "personal rules win over everything, including the LLM" invariant becomes a
pipeline-level test rather than a comment.

`cleanup.level` (none/light/medium/high) becomes a *stage filter*, keeping the
existing dial and every current config working. Legacy keys (`strip_fillers`,
`llm.enabled`) keep their override semantics — same compatibility promise as today.

### 5.2 Injection strategy resolver

New package `mywhisper/injection/`.

```python
class InjectionStrategy(Protocol):
    def inject(self, text: str, ctx: UtteranceContext) -> int: ...

def resolve(ctx: UtteranceContext, cfg: dict) -> InjectionStrategy: ...
```

Strategies: `SendInputStrategy` (default), `ClipboardPasteStrategy`,
`ShiftInsertStrategy` (**G1** — Windows Terminal, Cursor), `TerminalStrategy`
(**G1** — line-split), `ElevatedTargetStrategy` (**G2** — detect and explain).

Target classification lives in `appcontext.py` next to the existing exe detection.
`injection.targets` in config lets users add their own exe → strategy mappings.

### 5.3 Decompose `app.py`

| New module | Moves out of `app.py` |
|---|---|
| `session.py` | recording lifecycle: start / stop / cancel / lock / finalize, caps-flag maths |
| `streaming.py` | `_streamer()` and its LocalAgreement state machine |
| `settings.py` | `_save_state`, `set_model`, `set_device`, `set_language`, `set_hotkey`, theme/wave/bg cycling |
| `context/` | `UtteranceContext` construction; `TitleContextProvider` today, `UiaContextProvider` in Phase 2 (G12) |

`app.py` becomes the composition root: build collaborators, inject them, wire
callbacks, run. Target ≤ 350 lines. Collaborators take their dependencies as
constructor arguments (`Transcriber`, `History`, `LlmCleanup` are already
injectable — `Transformer` and `CommandMode` already do this correctly and are the
pattern to follow).

**Exit criteria:** 74/74 existing tests green, no config change, `--bench` numbers
within noise of the 0.1 baseline.

---

## 6. Phase 2 — Close the parity gaps

Ordered so each slice is independently shippable.

### 2a. Injection targets — G1, G2 *(size S, highest impact)*

The report's most concrete desktop insight, and Svara's users are developers.

- **Terminal line-splitting.** In a classified terminal target, emit each line
  separately rather than one blob — a dictated paragraph containing "and then run
  the build" must not become a command. Explicit rule, tested against a recorded
  keystroke stream.
- **Target-appropriate paste.** `Shift+Insert` for Windows Terminal / Cursor,
  where `Ctrl+V` is intercepted.
- **Elevation detection.** Compare Svara's integrity level with the foreground
  process's (`GetTokenInformation` / `TokenIntegrityLevel`). On mismatch, toast
  once per target: *"Notepad is running as administrator — Svara needs to run
  elevated too to type into it."* Today this is a silent no-op, which reads as a
  bug and is almost certainly already generating issues.
- Config: `injection.targets: { "windowsterminal.exe": shift_insert, … }`.

**Tests:** classification table; line-split fixture; elevation branch mocked.

### 2b. Transform slots — G3, G4, G13 *(size M)*

Generalise `transforms.py` (which already has the right shape) from one prompt to
nine.

```yaml
transforms:
  slots:
    1:
      name: Prompt Engineer          # reserved, matching Wispr
      builtin: prompt_engineer
      hotkey: "<cmd>+<alt>+1"
    2:
      name: Concise
      prompt: "Tighten this without losing meaning."
      hotkey: "<cmd>+<alt>+2"
      samples: [samples/my-concise-voice.txt]   # 1–5 files, 50–500 words each
  auto_after_dictation: null          # slot number → runs on every finish (G13)
  max_chars: 8000
```

- `TransformSlot` value object; `SlotRegistry` loads, validates, and hot-reloads.
- **Style-by-example (G4):** sample files are appended to the system prompt as
  few-shot style anchors. Validate the 50–500-word band and cap total prompt size
  — a 5×500-word prompt on a local 3B model is a latency cliff, so enforce a
  budget and warn rather than silently blowing the `timeout_s`.
- `QuickKeys` already binds arbitrary combos from a dict, so slot hotkeys need
  registry wiring only, no new hotkey machinery.
- **Voice-selected slots:** Command Mode can name a slot ("apply concise") instead
  of only free-form instructions.

**Tests:** registry validation (bad slot, missing prompt, oversized sample, dup
hotkey); prompt assembly snapshot; `auto_after_dictation` firing exactly once.

### 2c. Diff preview — G5 *(size M)*

Wispr's `Opt+O`. Svara's version: transforms become *reviewable* rather than
blind, which matters more locally where a 3B model is doing the rewriting.

- `difflib.SequenceMatcher` word-level diff → additions / deletions.
- Rendered in the existing `overlay.py` layered-window surface — Svara already
  does per-pixel alpha via Pillow + `UpdateLayeredWindow`, so this reuses proven
  code rather than introducing a new window toolkit.
- Bindings: accept / reject / toggle-diff. Config
  `transforms.preview: auto | on_request | off`.
- Reject restores the original selection exactly (the original already goes to
  History as `transform-original` — reuse that).

**Design gate:** this is new visual UI. Before any pixel is written, run
`tasteskill:redesign-existing-projects` (Svara has an established visual language
— eight themes, `themes.py` palettes) with `frontend-design` as the quality gate.
The diff overlay must read as part of the existing pill system, not a bolted-on
dialog. Deletion/addition colours must be drawn from each theme's palette and stay
legible in Matrix, Vaporwave, and minimal-light alike — a hardcoded red/green will
break in at least three themes.

### 2d. Locale and typography — G6, G7 *(size M)*

The report's most-overlooked detail, and pure quality-per-byte: rules-based, no
model, no latency.

- **`LocaleTypographyStage`,** table-driven per BCP-47 tag:
  - `fr-*`: narrow NBSP (U+202F) before `; : ? ! »`, after `«`. **Suppressed** in
    terminal targets and inside time strings — `UtteranceContext.is_terminal`
    exists for exactly this, and an invisible U+202F in a shell command is a
    genuinely nasty bug.
  - `zh/ja/ko`: strip spaces around full-width `。！？、`.
  - `en-GB / en-US / en-CA`: spelling variant normalisation, explicitly configured
    rather than auto-detected so dialects never fight.
- **`TransliterationStage` (Hinglish).** Config `model.romanize: auto | always |
  never`. Hindi phonetics → Latin, English terms left alone. Start rules-based on
  the Whisper Devanagari output; escalate to the LLM stage only when
  `cleanup.level: high`. Ship behind a flag until a Hindi-speaker test pass exists
  — this one is easy to get subtly, embarrassingly wrong.
- **`NumberedListStage` (G15).** Conservative: requires ≥3 consecutive spoken
  ordinals with pauses at segment boundaries (timings are already available from
  `transcribe()`). Off unless `cleanup.level ≥ medium`.

**Tests:** one table-driven suite per locale. This is where unit tests pay for
themselves — every rule is a pure string function.

### 2e. Dictionary — G9, G10, G8 *(sizes S, M, L)*

- **CSV import/export (G9).** Two-column, ≤1,000 rows / 3 MB, matching the report.
  Merge semantics: import never silently overwrites — conflicts are reported.
- **Table editor (G10).** Words / replacements / snippets tabs in the existing
  `howto_ui.py` window; writes `dictionary.yaml`; live reload via the existing
  `reload_dictionary()`.
- **Auto-learn (G8)** — the hardest item, and the one to get *right* rather than
  *soon*:
  - **Signal:** after injection, watch the target field via UIA for N seconds. If
    the user edits a word Svara typed, record `(heard, corrected)`.
  - **Never silent.** Candidates go to a *review queue*, surfaced as
    "Svara noticed you corrected 'Kubernetes' 3 times — add it?" Nothing enters
    the dictionary without a click. A dictation tool that silently rewrites your
    words based on inferred intent is worse than one that gets a word wrong.
  - **Thresholded:** ≥3 occurrences, ≥2 distinct sessions, edit-distance bounded.
  - **Gated:** `dictionary.auto_learn: false` by default. It reads text you typed
    that Svara did not produce — an explicit trust boundary that must be opt-in,
    documented in the README's privacy section, and never logged (§3.1 applies).

### 2f. Scratchpad depth — G11 *(size M)*

Tabs, per-note version log tagged by source (`Typed` / `Dictated` / `Transform` —
the exact provenance the report describes), detachable window, image paste
(PNG/JPEG/WebP/GIF, ≤5 MB, ≤10 per note).

Storage moves from a flat file to SQLite alongside `history.db` — `history.py` is
the pattern to copy. **Migration is mandatory:** existing scratchpad content must
survive the upgrade, and the migration needs its own test. Losing a user's notes
in an auto-update is unrecoverable.

Cross-device sync stays a non-goal (§1.4).

### 2g. Context and audio polish — G12, G14 *(size M, S)*

- **Caret-adjacent text (G12).** `UiaContextProvider` reads the focused text
  control around the caret. `overlay.py` already does UIA for caret tracking, so
  the plumbing exists. Feeds:
  - casing-aware continuation (mid-sentence dictation shouldn't capitalise),
  - a smarter `initial_prompt` (§3.5),
  - the G8 edit-detection signal.
  Config `context.read_caret_text: false` by default, with the same trust-boundary
  treatment as auto-learn. Hard cap on how much is read; never logged; never
  persisted.
- **Clamshell / device policy (G14).** Generalise the existing dead-device
  fallback into a policy: `audio.device_policy: preferred | system_default |
  external_first`, reacting to lid-close (`WM_POWERBROADCAST`) and device-arrival
  events rather than only to failure.

---

## 7. Phase 3 — SOTA tier *(lead, don't follow)*

Nothing here has a Wispr equivalent. This is where being local wins outright.

### 3.1 Pluggable ASR backend

Extract `AsrBackend` from `transcriber.py`:

```python
class AsrBackend(Protocol):
    def transcribe(self, audio, ctx) -> list[Segment]: ...
    def transcribe_partial(self, audio, ctx) -> list[Segment]: ...
    @property
    def capabilities(self) -> BackendCaps: ...   # streaming-native? multilingual? timings?
```

`FasterWhisperBackend` first (behaviour-identical, proves the seam). Then evaluate
candidates **through the Phase-0 harness** — the harness picks the winner, not this
document:

| Candidate | Why it's interesting | What to check |
|---|---|---|
| **Moonshine** (small/base, ONNX) | designed for short streaming windows; already the researched phase-2 engine for Svara | streaming latency vs `base.en`; English-only scope; ONNX Runtime footprint |
| **NVIDIA Parakeet / FastConformer (NeMo)** | consistently near the top of open ASR leaderboards; cache-aware streaming variants exist | NeMo dependency weight vs PyInstaller packaging; **licence compatibility with AGPL-3.0**; CPU viability |
| **Kyutai streaming STT** | natively streaming rather than windowed-batch | maturity, language coverage, packaging |
| **distil-whisper / large-v3-turbo** | already supported, known quantity | batched-pipeline gains from §3.5 |

Non-negotiables for any new backend: runs fully offline, packages into a
PyInstaller build, licence compatible with AGPL-3.0, and **beats the incumbent on
the committed benchmark** — not on a paper's claim.

### 3.2 Streaming commit policy experiments

Current: LocalAgreement-2, hold back one word. Alternatives to A/B on the harness:
AlignAtt-style attention-based commit; confidence-thresholded commit; adaptive
hold-back that shortens when the model is confident. Metric: p95 commit latency at
equal or better WER. Any policy that trades stability for speed is rejected —
flickering text is worse than slightly late text.

### 3.3 Semantic endpointing

Silero VAD answers "is this speech?". It cannot answer "are they *done*?" — which
is why `auto_stop` is off by default and users must tap to finish. A small
turn-detection model (or the local LLM scoring syntactic completeness on the
committed prefix) can distinguish a thinking pause from an ended sentence. This is
the difference between hands-free dictation that works and one you fight.

Ships off by default, behind `recording.auto_stop.semantic: true`.

### 3.4 On-device personalization

Everything Wispr's cloud does with your data, done locally with a much better
privacy story:

- Per-user hotword weighting from accepted-dictionary history.
- Per-app learned tone from *your own accepted* transforms (G4 samples, harvested
  rather than hand-written).
- A local acoustic-adaptation experiment (LoRA on your own recordings) — research
  spike, gated on Phase-0 evidence that it beats hotword boosting. Explicitly
  time-boxed; kill it if the numbers don't come.

### 3.5 Latency budget as a tracked artifact

`BENCH.md` becomes a CI-visible regression gate: a PR that pushes p95 TTFW past
budget fails. This is the mechanism that keeps the §2 targets true after they're
first hit.

---

## 8. Phase 4 — Ship

- **Docs:** README performance table regenerated from real `--bench` output (fixes
  §3.6); `PRIVACY.md` covering the two new trust boundaries (caret reading,
  auto-learn) and the §1.4 "no certification needed, here's why" argument;
  `ARCHITECTURE.md` with the stage chain and injection strategies (the LLD the
  engineering standards call for).
- **Website (`web/`):** the parity story is the pitch — *"everything the cloud tool
  does, on your machine, free."* New-page/redesign work runs through
  `tasteskill:redesign-existing-projects` + `frontend-design`, with GSAP skills for
  motion, per the standing frontend protocol.
- **Release:** per `SHIP.md` — versioned `Svara-X.Y.Z.exe` asset, never a reused
  filename, asset uploaded *before* the push.

---

## 9. New configuration surface

Consolidated, so the config-review happens once rather than nine times. Every key
optional, every default preserving current behaviour.

```yaml
logging:
  debug_transcripts: false      # 🔒 true = dictated text in logs (opt-in, warned)
  max_log_mb: 10

injection:
  targets:                      # exe → strategy (G1)
    windowsterminal.exe: shift_insert
    cursor.exe: shift_insert
    wt.exe: shift_insert
  terminal_apps: [windowsterminal.exe, wt.exe, powershell.exe, cmd.exe, alacritty.exe]
  terminal_line_split: true     # never send a paragraph as one shell line
  warn_on_elevated: true        # G2

locale:
  typography: auto              # auto | off — per-language spacing rules (G6)
  english_variant: en-US        # en-US | en-GB | en-CA
  romanize: auto                # Hinglish etc. (G7)

transforms:
  slots: {...}                  # see §6/2b
  auto_after_dictation: null    # G13
  preview: on_request           # auto | on_request | off  (G5)

dictionary:
  auto_learn: false             # 🔒 G8 — watches your edits; opt-in, review queue
  auto_learn_threshold: 3

context:
  read_caret_text: false        # 🔒 G12 — reads text around the caret; opt-in
  caret_chars: 200

audio:
  device_policy: preferred      # preferred | system_default | external_first (G14)

recording:
  auto_stop:
    semantic: false             # Phase 3.3

asr:
  backend: faster-whisper       # Phase 3.1
```

The three 🔒 keys are the plan's entire privacy delta. All default off. All get a
README section. None of them ever writes what it reads to a log.

---

## 10. Module map

**New**

```
mywhisper/
  bench.py                 Phase 0 — harness, WER/latency/RTF
  session.py               Phase 1 — recording lifecycle (from app.py)
  streaming.py             Phase 1 — LocalAgreement streamer (from app.py)
  settings.py              Phase 1 — live config mutation + state (from app.py)
  pipeline/
    base.py                Stage protocol, UtteranceContext, chain runner
    fillers.py backtrack.py llm.py personalizer.py     (moved from cleanup.py)
    numbered_list.py locale.py transliterate.py app_rules.py   (new)
  injection/
    base.py resolver.py sendinput.py clipboard.py shift_insert.py
    terminal.py elevated.py
  context/
    base.py title.py uia.py elevation.py
  transforms/
    registry.py slots.py samples.py diff.py prompt_engineer.py
  asr/
    base.py faster_whisper.py  [+ candidates, Phase 3]
  scratchpad.py            Phase 2f — tabs, versions, images (SQLite)
  dictionary_io.py         Phase 2e — CSV import/export, auto-learn queue
```

**Changed:** `app.py` (→ composition root), `cleanup.py` (→ `pipeline/`, shim kept
for one release), `injector.py` (→ `injection/`, primitives retained),
`transcriber.py` (→ `asr/`), `appcontext.py` (→ `context/`), `transforms.py`
(→ package), `howto_ui.py` (dictionary table, scratchpad tabs), `tray.py`
(slots, locale, diff toggles), `config.py`, `config.yaml`.

---

## 11. Test strategy

Current: 74 tests, strong on `cleanup`/`features`/`install`, thin exactly where the
code is hardest — one live-path test for the streamer, the most intricate state
machine in the project.

| Layer | Approach | Target |
|---|---|---|
| Pipeline stages | pure string functions, table-driven per locale/rule | **≥95%** — this is the business logic |
| Injection strategies | classification tables + recorded keystroke fixtures | ≥90% branch |
| Transform registry | validation, prompt assembly snapshots, hotkey conflicts | ≥90% |
| Streamer | **new** — synthetic segment sequences replayed through the commit state machine, no audio needed | ≥85% |
| Context providers | mocked Win32/UIA | ≥80% |
| Integration | extend `test_livepath.py` — audio in, keystrokes out, per injection strategy | key paths |
| Privacy | assert no corpus transcript reaches log output at default config | **must pass** |
| Performance | `--bench` regression gate in CI | budget-enforced |

TDD for the pipeline stages specifically: the contract ("personal rules always
win", "no NNBSP in terminals") is easier to write as a test than as prose.

`README.md` gains the testing + caching strategy section the engineering standards
require: how to run tests, what the model cache is, what `keep_alive` does to the
local LLM, and how each is invalidated.

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Phase 1 refactor regresses live streaming | high — it's the flagship feature | Phase 1 is behaviour-preserving by contract: 74/74 tests green, `--bench` within noise, no config change. Land it alone, ship it alone. |
| Local 3B model too slow for 9 transform slots + samples | medium | Prompt-size budget with a warning; measure per-slot latency in `--bench`; document the model/latency tradeoff |
| Hinglish romanisation embarrasses Hindi speakers | medium | flag-gated, off by default, no ship without a native-speaker test pass |
| Auto-learn (G8) feels like surveillance | **high — it's the brand** | opt-in, review queue, never silent, never logged, README-documented. If it can't be made comfortable, it doesn't ship — this is not a feature worth the trust. |
| UIA caret reading is slow or flaky across Electron/browsers | medium | strict timeout, fail-open to title-only context, never block dictation (`appcontext.foreground()` already models this correctly) |
| New ASR backend can't be packaged or is licence-incompatible | medium | packaging + licence check as a gate *before* benchmarking, not after |
| Scratchpad SQLite migration loses notes | high — unrecoverable | migration test + backup of the old file before conversion |
| Scope: 15 gaps across 4 phases | high | each Phase-2 slice independently shippable; ship v0.5 after 2a+2b rather than holding for all of Phase 2 |

---

## 13. Sequencing

```
v0.5  "It types where you actually work"
      Phase 0 (bench + 🔒 log redaction)  →  Phase 1 (architecture)
      →  2a injection targets  →  2b transform slots
      Headline: terminal-safe injection, elevation detection, 9 transform slots.
      Gate: benchmark baseline published; zero transcripts in logs.

v0.6  "It knows how your language is written"
      2c diff preview  ·  2d locale/typography + Hinglish  ·  2e CSV + table editor
      Headline: reviewable transforms, correct French/CJK/en-GB output.

v0.7  "It learns you"
      2f scratchpad depth  ·  2g caret context + device policy  ·  2e auto-learn
      Headline: the three 🔒 features, all opt-in, all local.

v1.0  "State of the art, on your machine"
      Phase 3 (backend evaluation, commit policy, semantic endpointing)
      →  Phase 4 (docs, privacy doc, site, release)
      Headline: published numbers that beat the cloud tool, offline.
```

Phase 0 and Phase 1 are not optional and not reorderable. Everything after 2b can
be resequenced on evidence.

---

## 14. The one-line version

Svara already has Wispr's *engine*. What it lacks is the **last mile** — where the
text lands (terminals, elevated apps), how it's shaped (locale typography,
transform slots), and whether the user can see what changed (diff). Fix the
pipeline and injection seams first, close those fifteen gaps, then publish
benchmark numbers the cloud product cannot match because it has to make a network
round-trip and Svara does not.
