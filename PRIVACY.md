# Privacy in Svara

**Short version:** your voice and your words never leave your machine, there is
no account, no telemetry, and no server to send anything to. Svara works with
the network cable unplugged.

This document exists because "it's local" is a claim, and claims should be
checkable. Below is exactly what Svara reads, what it writes, where, and how to
turn each of those off.

---

## What leaves your computer

Nothing that you dictate. Ever.

Svara opens exactly two kinds of network connection, both optional and both
listed here:

| Connection | When | What is sent | Turn it off |
|---|---|---|---|
| **huggingface.co** | first run only, and when you switch models | a model download request. No audio, no text. | pre-download the model, or run offline after the first launch |
| **api.github.com** | every 24 h, packaged builds only | a version check. No audio, no text, no identifier. | `update.check: false` |
| **localhost:11434 / :1234** | only if you enabled LLM cleanup | your transcript, to **your own** Ollama / LM Studio, on **your own** machine | `cleanup.level` below `high` and `cleanup.llm.enabled: false` |

The third one is not "the internet" — it is a loopback socket to a server you
started yourself. If you have not installed Ollama or LM Studio, Svara never
opens it.

There is no analytics endpoint, no crash reporter, and no account system. Not
disabled by default — **absent**.

---

## What Svara writes to your disk

All of it under `%LOCALAPPDATA%\Svara`, all of it yours to delete.

| File | Contains | Controlled by |
|---|---|---|
| `history.db` | every dictation, its timestamp, and the app it went into | `history.enabled`, `history.retention_hours` |
| `scratchpad.db` | your notes and their version log | `scratchpad.enabled` |
| `dictionary.yaml` | words, replacements, snippets you added | you |
| `learned.yaml` | pending auto-learn suggestions (only if enabled) | `dictionary.auto_learn` |
| `config.yaml`, `state.json` | settings | you |
| `logs/mywhisper.log` | **diagnostics only — no transcript content** | see below |
| `logs/recovery.raw` | audio of an *in-progress* dictation, deleted the moment it is transcribed | `recording` |

Audio is otherwise never written to disk. It lives in RAM, and outside a
recording only ~1 second of it exists at a time (the pre-roll ring buffer that
stops your first word being clipped).

### The log file

Up to v0.4.1, Svara wrote an 80-character preview of every dictation into
`logs/mywhisper.log`. That was wrong, and it is fixed in 0.5.0.

The log now records the *shape* of an utterance and never its content:

```
✓ 4.2s audio → 68 chars in 0.31s stt + 0.02s cleanup | «redacted» 12w/68c
```

Word count and timings are enough to debug "did the pipeline eat my text?"
without knowing what the text was. Errors carry stable codes (`SVARA-STT-002`,
`SVARA-INJ-003`) so you can paste a log into a GitHub issue after reading it.

`logging.debug_transcripts: true` turns transcript logging back on for
debugging. When you do, Svara logs a warning at startup telling you it is on.
There is a test (`tests/test_redact.py`) that runs real text through the real
pipeline with logging captured and fails if any of it appears.

---

## The three features that read more than your voice

Everything above is on by default because it only involves audio you chose to
dictate. These three read something else, so all three are **off by default**
and each needs a deliberate change to `config.yaml`.

### 1. `context.read_caret_text` — the text around your cursor

**What it does.** Reads up to 200 characters immediately before your caret via
UI Automation, so dictating mid-sentence isn't capitalised: with "and then we "
already typed, "Went to the shop" becomes "went to the shop".

**What it reads.** Text *you* typed, that Svara did not produce, in the field
you are focused on. Only in the focused field, only at the moment a dictation
starts, hard-capped at `context.caret_chars`.

**What happens to it.** Held in memory for the length of one utterance, then
dropped. Never logged, never written to disk, never sent anywhere.

### 2. `dictionary.auto_learn` — noticing your corrections

**What it does.** If Svara writes "cuban" where you meant "Kubernetes" and you
fix it three times across two sessions, it offers to learn the word.

**What it reads.** Requires `read_caret_text` above — it re-reads the field a
few seconds after typing into it and diffs the result. It only ever considers
single-word substitutions between similar-sounding words; a rewritten sentence
teaches it nothing and is discarded.

**It never writes to your dictionary.** Observations go into a review queue
(`learned.yaml`) and appear under tray ▸ Dictionary ▸ Suggestions. An entry
becomes real when you click accept, and not before. A dictation tool that
silently rewrote your words based on inferred intent would be worse than one
that occasionally gets a word wrong.

### 3. `context.enabled` — the focused app (on by default)

This one *is* on by default, so it is described here in full: Svara reads the
**executable name and window title** of the app you are dictating into. It uses
them to pick per-app rules (chat apps lose the trailing period; terminals get
line-safe insertion) and to mine proper nouns from the title as a per-utterance
recognition boost — "PR #142 — Svara streaming fix" boosts "Svara".

It does not read the window's contents, take screenshots, or record which apps
you use over time. The app name is stored alongside each entry in `history.db`
so you can find "that thing I dictated into Slack"; `history.enabled: false`
turns that off, and `context.enabled: false` turns the whole thing off.

For comparison: this is the same capability cloud dictation tools implement by
uploading screenshots of your screen to their servers.

---

## Why Svara has no compliance certification

SOC 2, ISO 27001 and HIPAA certify **a data processor** — an organisation that
receives your data, stores it, and must prove it handles it correctly. Zero Data
Retention agreements bind **subprocessors** who would otherwise keep your data.

Svara is not a processor and has no subprocessors, because your data never
reaches anyone. There is no server-side to audit. An audit report would be a
document attesting that an empty room is well guarded.

If your organisation's policy requires software handling sensitive speech to
either be certified or to not transmit, Svara satisfies the second condition,
and you can verify it: run it with the network disconnected, or watch it with a
firewall. That is a stronger guarantee than a certificate, because it is one you
can check yourself.

The source is AGPL-3.0 and the whole pipeline is in `mywhisper/`. Start at
`app.py` — audio in, text out, no sockets in between.

---

## Deleting everything

Close Svara from the tray, then delete `%LOCALAPPDATA%\Svara`. That is all of
it: settings, history, notes, dictionary, logs, and the app itself. The model
cache lives in the standard HuggingFace location (`~/.cache/huggingface`) and
can be deleted separately.

Tray ▸ History… ▸ Clear history wipes just the transcripts, and
`history.retention_hours: 24` makes that automatic.
