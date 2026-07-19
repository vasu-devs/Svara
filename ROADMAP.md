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

## Phase 1 — reliability & trust (all LOCAL, do next)

1. **Crash-safe audio**: buffer the recording to disk during capture; on
   crash/quit, offer "finish processing last dictation". Wispr shipped this
   because losing a long dictation is rage-inducing.
2. **Transcript history + paste-last hotkey**: SQLite log of every dictation
   (text + timestamp + app), tray "History…" window with search/copy/retry;
   `Shift+Alt+Z` paste-last. Privacy: local file, optional 24 h auto-delete,
   or off — make it a visible setting like Wispr's storage modes.
3. **Auto mic handling**: ranked mic auto-selection when the default device
   dies/unplugs (recorder.ensure_alive already revives — add device fallback
   and a specific "mic gone" toast naming the device).
4. **Auto-update**: check GitHub Releases in the background, download, swap on
   next idle/restart; defer while dictating. Wispr auto-updates silently after
   1 h idle. (Our versioned-filename release flow already supports this.)
5. **Session ceiling with auto-submit** at max_seconds (we hard-stop today —
   type what we have instead of dropping it) + warning chime a minute before.

## Phase 2 — accuracy moat (LOCAL, the big differentiator)

6. **Context awareness, locally**: read the foreground app/window title +
   UIA cursor-adjacent text; feed proper nouns into hotwords per-dictation;
   apply per-app rules (no trailing period in Slack/WhatsApp-web, lowercase
   continuation mid-sentence). Wispr sends screenshots to the cloud for this —
   we can headline "same feature, nothing leaves your machine".
7. **Auto-learned dictionary**: diff what the user edits right after an
   injection (clipboard/UIA), frequency-filter against common words, suggest
   "add ‹Svara› to your dictionary?" toast — the retention loop that makes it
   feel like it learns you.
8. **List formatting rules**: "one… two… three…" → numbered list; "bullet…"
   → dashes. Rules first; sLLM only for the messy cases.

## Phase 3 — the AI layer (sLLM via existing Ollama integration)

9. **Cleanup levels** (None/Light/Medium/High) instead of the binary LLM
   toggle — Light = fillers+punctuation (rules), High = full rewrite (LLM).
   Keep the verbatim transcript recoverable (Wispr had to ship "undo AI
   edits" after complaints — learn from that).
10. **Backtrack**: "meet at 2, actually 3" → "meet at 3" (trigger-word rules
    first, sLLM for robustness).
11. **Transforms / Polish**: select text anywhere → hotkey → rewrite in place
    (concise/clarity/tone), diff preview, up to N custom prompt slots. This is
    Wispr's flagship paid feature; ours rides free on Ollama.
12. **Per-app styles**: app → category (personal/work/email) → tone applied in
    the LLM cleanup prompt. English-only at Wispr too, so no pressure on i18n.

## Phase 4 — surface & polish

13. **Settings UI for the dictionary** (table editor in the Svara window, not
    just YAML) + hotkey capture UI ("press your shortcut") like Wispr's
    onboarding.
14. **Whisper mode**: input gain boost + VAD threshold preset for whispering
    at ~1 cm — mostly-free feature with outsized wow.
15. **Scratchpad/notes window** with dictation-aware version history —
    offline-first where Wispr requires cloud sync.
16. **Command mode** (speak an instruction, act on selection) — after
    Transforms; Styles covers most of its value.

## Non-goals for now

- Mobile (Wispr's iOS keyboard/Android bubble) — desktop is the wedge.
- Cloud sync/teams — the local-only story IS the product.
- Mid-sentence language code-switching — even Wispr punts ("entire segment in
  one language"); per-session auto-detect matches them already.
