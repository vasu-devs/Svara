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

## Still open (the honest tail)

1. **Auto-learned dictionary** — detect the user's own corrections after
   injection (UIA/clipboard diffing) and suggest additions. Needs a careful
   design to avoid being creepy or wrong; deliberately not faked with a
   heuristic in v0.4.0.
2. **UIA cursor-adjacent text context** — reading the textbox around the
   caret (not just the window title) for casing-aware continuations.
3. **Numbered-list auto-detect** ("one… two… three…" → 1. 2. 3.) — the
   conservative spoken-bullet vocab shipped; the auto-detector needs sLLM
   judgment to avoid false positives.
4. **Dictionary table editor** — quick-add + YAML shipped; a full table UI
   remains cosmetic polish.
5. **Transforms diff preview & custom transform slots** — Polish + voice
   command shipped; multi-slot custom prompts with diff view are next.

## Non-goals for now

- Mobile (Wispr's iOS keyboard/Android bubble) — desktop is the wedge.
- Cloud sync/teams — the local-only story IS the product.
- Mid-sentence language code-switching — even Wispr punts ("entire segment in
  one language"); per-session auto-detect matches them already.
