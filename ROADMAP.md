# Svara Roadmap — feature parity with Wispr Flow, local-first

Researched 20 Jul 2026 from wisprflow.ai, docs.wisprflow.ai, and their 2026
changelog. Wispr Flow is 100% cloud — "transcription always occurs on the
cloud", no offline mode, and their context-awareness feature ships your
screenshots, Slack messages, and cursor-adjacent text to their servers.
**Svara's pitch is the inverse: everything below runs on your machine.**

Legend — `LOCAL`: rules/OS APIs, no LLM · `sLLM`: needs a small local LLM
(Ollama/Qwen, already optional in Svara) · ✅: shipped.

## Shipped (v0.3.0)

- ✅ **Self-install + start with Windows** — the exe installs itself to
  `%LOCALAPPDATA%\Svara` on first run, registers login autostart (HKCU Run),
  Start Menu entry, migrates config/state/CUDA runtime. Dictation survives
  every reboot. Wispr treats this as table stakes; now so do we.
- ✅ **Dictionary word boosting** (`dictionary.words` → faster-whisper
  hotwords, live streaming included) — Wispr's "Dictionary" feature.
- ✅ **Replacement rules** (`dictionary.replacements`) — Wispr's "correct a
  misspelling", applied after any LLM step so user fixes always win.
- ✅ **Snippets** (`dictionary.snippets`) — say "my email", type the block.
- ✅ **Spoken punctuation** (`dictionary.spoken_punctuation`) — "period",
  "comma", "new line", "new paragraph", "question mark"…
- ✅ Already had: push-to-talk + double-tap hands-free lock (Wispr parity),
  live streaming typing, filler stripping, loudness→CAPS, optional Ollama
  cleanup, pill overlay with themes, tray, per-utterance 10-min cap.

## Shipped in v0.4.0 (the "make everything" release)

- ✅ **Crash-safe audio** — recording spills to disk on a writer thread; an
  interrupted dictation is transcribed at next launch and delivered via
  clipboard + History.
- ✅ **Transcript history + paste-last** — local SQLite log (app, time, text),
  tray ▸ History… window with search/copy/clear, `Shift+Alt+Z` paste-last,
  `Shift+Alt+X` copy-last, retention setting (forever / N hours / off).
- ✅ **Auto mic fallback** — dead device → system default → any working input,
  with a toast naming the new mic.
- ✅ **Auto-update** — background GitHub Releases check, downloads quietly,
  applies ONLY on tray ▸ "Restart to update"; upgrades carry the setup-done
  flag so users are never re-onboarded.
- ✅ **Session ceiling** — a one-minute warning toast, then auto-finish (the
  audio is typed, not dropped).
- ✅ **Context awareness (lite), locally** — foreground app + window-title
  proper nouns → per-utterance hotword boost; chat apps lose the trailing
  period. (Wispr uploads screenshots for this; Svara reads it locally.)
- ✅ **Cleanup levels** — None / Light / Medium / High dial in the tray;
  Medium adds "scratch that" backtrack rules; High engages the local LLM
  when Ollama is reachable.
- ✅ **Transforms / Polish** — `Win+Alt+P` rewrites the selected text in
  place via local LLM; original saved to History; target app's Ctrl+Z undoes.
- ✅ **Per-app styles** — `context.styles` maps exe → tone hint for the LLM.
- ✅ **Whisper mode** — tray toggle, 3× software gain for speak-softly use.
- ✅ **Scratchpad** — `Win+Alt+S` toggle note window, autosaves locally.
- ✅ **Command mode** — optional hold-and-speak key (`shortcuts.command_key`):
  "make this friendlier" applies to the selection. Off by default.
- ✅ **Hotkey picker + dictionary quick-add** in the Svara window (live
  rebind, no restart; add-word box feeding dictionary.yaml).
- ✅ **Spoken bullets** — "bullet point" → "\n- " (spoken-punctuation vocab).

## Shipped in v0.5.0 (parity closed, and measured)

Derived from a full architectural breakdown of Wispr Flow mapped against the
v0.4.1 source — see [`PLAN.md`](PLAN.md) for the gap analysis and
[`BENCH.md`](BENCH.md) for the numbers.

- ✅ **The log leak fixed.** v0.4.1 wrote an 80-char preview of every dictation
  into `logs/mywhisper.log` — plaintext, unrotated, outliving
  `history.retention_hours`. Now it logs shape (`«redacted» 12w/68c`) plus
  stable error codes. A test runs real text through the real pipeline with
  logging captured and fails if any escapes.
- ✅ **Terminal-safe injection** — a newline at a shell prompt is the Enter key,
  so a dictated paragraph can never execute. Line-safe insertion for terminals
  and TUI agents, `Shift+Insert` for Cursor/VS Code.
- ✅ **Elevation detection** — Windows discards synthetic input aimed at an
  admin window *and reports success*, so dictation vanished with no error.
  Detected, explained once, delivered via clipboard.
- ✅ **Transform slots 1–9** with Prompt Engineer in slot 1, style-by-example
  samples, voice addressing ("apply concise"), and `auto_after_dictation`.
- ✅ **Diff preview** (`Win+Alt+O`) drawn from the active theme's own palette.
- ✅ **Locale typography** — French NNBSP, CJK spacing, en-US/GB/CA/AU/NZ/IN
  with the `-ise`/`-ize` exception list. Optional Hinglish romanisation.
- ✅ **Numbered-list detection** (roadmap #3 below — done conservatively).
- ✅ **Dictionary table editor + CSV import/export** (#4, #9).
- ✅ **Auto-learned dictionary** (#1) — suggest-only, thresholded on repetition
  *and* distinct sessions, two opt-ins, never silent.
- ✅ **UIA caret-adjacent context** (#2) — casing-aware continuation.
- ✅ **Scratchpad** with tabs and a provenance-tagged version log.
- ✅ **`--bench`** — TTFW, p50/p95, WER, RTF on your machine, exits non-zero
  when the budget is missed.
- ✅ **Semantic endpointing**, commit policies, `asr/` backend seam.
- ✅ Architecture: `pipeline/`, `injection/`, `context/`, `asr/`, `streaming.py`.
  355 tests, up from 74.

## Still open (the honest tail)

The v0.4 tail (auto-learn, caret context, numbered lists, dictionary editor,
diff + slots) all shipped in v0.5.0 above. What is genuinely left:

1. **A recogniser that doesn't pad to 30 seconds.** The benchmark's finding: a
   **7.7× larger decode window costs 8% more time**, because Whisper's encoder
   runs on a mel spectrogram padded to a fixed 30 s. Trimming and commit-policy
   tuning therefore cannot reach the latency budget, and `tiny.en` only gets
   close by paying +43% WER. The `asr/` seam exists for this; Moonshine is first
   to try, since variable-length input is its design premise. **This is the only
   remaining latency lever** — see [`BENCH.md`](BENCH.md).
2. **A GPU benchmark row.** Every published number so far is CPU `base.en`. The
   CUDA path is the single biggest change available today and is unmeasured.
3. **A real benchmark corpus.** `bench/corpus/` currently holds synthesised
   speech — a good regression signal and a poor absolute number. Recordings of
   actual dictation (technical vocabulary, false starts, your room, your mic)
   would make the WER figure mean something.
4. **Hinglish needs a native-speaker pass** before it can default to on. It is
   solid on common words and does not handle medial schwa deletion (करता →
   `karata`, not `karta`).
5. **On-device personalization** (PLAN.md §7 3.4) — per-app tone learned from
   your own accepted transforms; a local acoustic-adaptation spike, gated on
   evidence it beats hotword boosting.

## Non-goals for now

- Mobile (Wispr's iOS keyboard/Android bubble) — desktop is the wedge.
- Cloud sync/teams — the local-only story IS the product.
- Mid-sentence language code-switching — even Wispr punts ("entire segment in
  one language"); per-session auto-detect matches them already.
