# Benchmarks

Measured, not claimed. Every row below came out of `run.bat --bench` and is
reproducible on the machine named in it.

Regenerate with:

```bat
run.bat --bench                 :: writes bench/results/<sha>-<model>-<device>.json
```

Raw JSON — including the full latency distribution and the machine spec — lives
in [`bench/results/`](bench/results/).

---

## Baseline — v0.5.0 (`ca7af97`)

**Machine:** Windows 10 · Intel Core (20 cores) · 23.7 GB RAM · RTX 4060 Laptop
**Corpus:** 3 clips, 39 s of Windows SAPI speech (`bench/corpus/`), 2 passes each

| Metric | `base.en` · CPU · int8 | Budget | |
|---|---|---|---|
| **TTFW** (hotkey → first word) | 829 – 1402 ms | ≤ 300 ms | ✗ |
| **Partial pass** p50 | 937 – 1469 ms | | |
| **Partial pass** p95 | 1127 – 2094 ms | ≤ 500 ms | ✗ |
| **Partial pass** max | 2932 – 4841 ms | | |
| **Final pass** p50 | 987 – 1432 ms | | |
| **RTF** (compute per second of audio) | 0.146 – 0.250 | < 1.0 | ✓ |
| **WER / CER** | 8.33% / 0.87% | ≤ 6% | ✗ |
| **Peak RSS** | 408 MB | | |
| Model load + warmup | 2.3 s | | |
| GPU (`large-v3-turbo` · CUDA) | **not yet measured** — the CUDA runtime is not installed on this machine | | |

Two numbers per cell because CPU results move with machine load. The lower
figures are from a quiet machine; the higher ones from the same corpus while
other work was running. That spread is itself the result: **on CPU, latency is
a function of what else you have open.** A single number here would be a lie of
omission.

---

## What this actually says

**1. The v1.0 latency budget is not met on the CPU default, and that is now a
fact rather than a hope.** `base.en` at int8 needs ~0.8–1.5 s per streaming pass
on this laptop. The published targets (TTFW ≤ 300 ms, p95 ≤ 500 ms) stand as
targets; PLAN.md §7 — a pluggable ASR backend and commit-policy experiments — is
the work that has to close the gap, and now has a number to close it against.

**2. `streaming.interval_ms: 180` is aspirational on CPU.** A partial pass takes
5–8× the configured interval, so the streamer runs back-to-back rather than on a
timer. That is not a bug — the loop is written to absorb it
(`sleep(max(0.05, interval - elapsed))`) — but it does mean the README's "about
a second behind your voice" is the honest description of the CPU path, and the
interval setting only bites on hardware fast enough to finish inside it.

**3. RTF 0.15–0.25 means the model can keep up with speech.** The constraint is
per-pass latency, not throughput. That distinction matters for what to fix: a
faster model helps, but so does a commit policy that needs fewer passes.

**4. Memory is fine.** 408 MB peak, against the ~800 MB the source report
attributes to the cloud tool this project is an alternative to.

**5. The WER caveat.** 8.33% is measured against **synthesised** speech, which
is cleaner than any human and harder in its own way (flat prosody, no
disfluencies). It is a usable regression signal and a poor absolute number.
Replacing `bench/corpus/` with real recordings of your own dictation is the
single highest-value contribution to this file — see
[`bench/corpus/README.md`](bench/corpus/README.md).

---

## Method

- **TTFW** decodes the first `streaming.min_audio_s` of audio through the same
  `transcribe_partial` the live streamer uses. It is the latency a user feels,
  not a proxy for it.
- **Partial-pass latency** replays the streamer's growing-window behaviour at
  the configured interval, and is reported as p50 / p95 / max. The mean is
  printed too, but the p95 is what makes streaming feel smooth or not.
- **WER/CER** use standard normalisation (casefold, punctuation stripped,
  whitespace collapsed) so the score measures the recogniser rather than the
  post-processor's taste in commas.
- **Validity gate.** Silero VAD sits in front of the decoder. If it rejects
  every clip, the harness marks the run invalid and refuses to report the
  timings — otherwise a decoder that never ran would post a gorgeous 5 ms TTFW.
  `--bench` exits `3` in that case, `2` when the budget is missed, `0` when it
  is met, so it can gate a release without anyone reading the output carefully.
