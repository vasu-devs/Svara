# Benchmarks

Measured, not claimed. Every row below came out of `run.bat --bench` and is
reproducible on the machine named in it.

```bat
run.bat --bench                 :: writes bench/results/<sha>-<model>-<device>.json
```

Raw JSON — full latency distribution, window sizes, machine spec — is in
[`bench/results/`](bench/results/).

---

## Baseline — v0.5.0 (`57a258b`)

**Machine:** Windows 10 · Intel Core (20 cores) · 23.7 GB RAM · RTX 4060 Laptop
**Corpus:** 3 clips, 39 s of Windows SAPI speech (`bench/corpus/`), 2 passes each

| Metric | `base.en` CPU int8 | `tiny.en` CPU int8 | Budget | |
|---|---|---|---|---|
| **TTFW** | 754 ms | 405 ms | ≤ 300 ms | ✗ |
| **Partial pass** p50 | 818 ms | 429 ms | | |
| **Partial pass** p95 | 913 ms | 502 ms | ≤ 500 ms | ✗ |
| **Window decoded** p50 | 2.7 s | 2.6 s | | |
| **Final pass** p50 | 846 ms | 455 ms | | |
| **RTF** | 0.134 | 0.072 | < 1.0 | ✓ |
| **WER / CER** | **8.33% / 0.87%** | 11.94% / 1.91% | ≤ 6% | ✗ |
| **Peak RSS** | 406 MB | 315 MB | | |
| Load + warmup | 2.3 s | 1.4 s | | |
| GPU (`large-v3-turbo` · CUDA) | **not measured** — CUDA runtime not installed here | | | |

---

## The finding that matters

**Decode cost is almost independent of how much audio you give it.**

| | audio in the window | pass time |
|---|---|---|
| TTFW pass (`base.en`) | 0.35 s | 754 ms |
| Typical streaming pass | 2.7 s | 818 ms |

A **7.7× larger window costs 8% more time.** `tiny.en` shows the same shape
(0.35 s → 405 ms, 2.6 s → 429 ms, 6% for 7.4×).

That is Whisper's architecture, not a Svara bug: the encoder runs on a mel
spectrogram padded to a fixed 30 seconds regardless of the real input length. So
every pass pays for 30 seconds of encoder whether you have spoken 0.3 s or 25 s.

Three consequences, and they redirect the roadmap:

1. **Window trimming buys almost no latency.** It is still worth having — it
   bounds memory and stops long utterances degrading — but it cannot be the
   answer. The first cut of this harness didn't model trimming at all and
   reported ~1127 ms p95 where the app achieves ~913 ms; fixing that (both now
   share [`streaming.py`](mywhisper/streaming.py)) recovered a fifth of the
   apparent gap and revealed the real ceiling underneath.
2. **A smaller model is the only lever available inside Whisper.** `tiny.en`
   nearly reaches the budget — p95 502 ms against a 500 ms target — and pays
   **+43% WER** for it (8.33% → 11.94%). That is not a trade worth taking: the
   whole point of dictation is not having to fix the output.
3. **So the budget needs an engine that doesn't pad to 30 s.** This is exactly
   the case for PLAN.md §7's candidate list, and it now has evidence rather than
   a hunch. Moonshine is the specific one to try first: variable-length input
   with no fixed padding is its entire design premise, which is precisely the
   constraint measured above. The [`asr/`](mywhisper/asr/) seam exists so that is
   a module, not a rewrite.

**RTF 0.134 means throughput was never the problem.** The model keeps up with
speech four times over. What it cannot do is answer *quickly*, which is a
different property and the one users feel.

---

## Did v0.5 make anything faster? Unknown — and here is why

There is **no v0.4 baseline**. `--bench` did not exist before v0.5, so no
honest before/after latency number can be produced. (Do not read the earlier
1127 ms → 913 ms p95 as a win either: most of that was fixing the harness to
model window trimming, not the app getting quicker.)

So the 0.5 changes were A/B'd against each other instead, back-to-back in one
process, `base.en` CPU, 2 passes over the same 3-clip corpus:

| configuration | TTFW | p50 | p95 | final | RTF | WER |
|---|---:|---:|---:|---:|---:|---:|
| 0.4-equivalent (no batching, no cap) | 2217 | 2526 | 3124 | 2580 | 0.354 | 8.33% |
| + batched final pass | 2397 | 2520 | 2834 | 2490 | 0.369 | 8.33% |
| + window cap 30 s *(shipped)* | 1566 | 2313 | 2845 | 974 | 0.243 | 8.33% |
| + context prompt (8 words) | 2204 | 2230 | 3102 | 2619 | 0.386 | 8.33% |
| adaptive commit policy | 2040 | 2249 | 2656 | 2293 | 0.375 | 8.33% |

**The latency columns are noise.** TTFW decodes a fixed 0.35 s window; none of
these settings can possibly affect it, and it still ranged 1566–2397 ms — a 53%
spread. Isolated runs of the identical code and corpus earlier the same day
measured 754 ms. Five configurations run sequentially heat the CPU and fight
whatever else is on the machine, and that drift is larger than every effect
being measured.

Which is the finding: **on this hardware the harness cannot resolve differences
below roughly ±50% on CPU.** Quoting any of those deltas as an improvement
would be inventing a result. Treat CPU latency here as an order of magnitude,
not a measurement, and do comparative work on GPU or on a quiet machine with
many alternating repeats.

**The WER column is clean**, because decoding is deterministic — same audio,
same settings, same answer. It says two useful things:

- **Batched inference costs no accuracy** (8.33% either way), so it is a safe
  default.
- **The rolling context prompt earns nothing** on this corpus — identical WER
  for a longer prompt on every pass. `streaming.context_prompt_words` stays at
  `0`, which is what "measure before turning it on" was for.

## Method

- **TTFW** decodes the first `streaming.min_audio_s` through the same
  `transcribe_partial` the live streamer uses. The latency a user feels, not a
  proxy for it.
- **Partial-pass latency** drives the *real* commit state machine
  ([`streaming.py`](mywhisper/streaming.py)) so the window is trimmed exactly as
  it is in the app. Sharing that code is deliberate: the first version of this
  harness reimplemented the policy, got it wrong, and reported latency the app
  does not have. A measurement must not be able to disagree with the thing it
  measures.
- **Reported as p50 / p95 / max.** The mean is printed too, but published
  dictation numbers quoting a mean hide their tail, and the tail is what makes
  streaming feel like it stutters.
- **WER/CER** use standard normalisation (casefold, punctuation stripped,
  whitespace collapsed) so the score measures the recogniser, not the
  post-processor's taste in commas.
- **Validity gate.** Silero VAD sits in front of the decoder. If it rejects
  every clip, the harness marks the run invalid and refuses to report timings —
  an earlier version happily posted a 5 ms TTFW for a decoder that never ran.
  Exit codes: `0` budget met, `2` budget missed, `3` nothing measured.

### Caveat on the corpus

8.33% is measured against **synthesised** speech, which is cleaner than any
human and harder in its own way (flat prosody, no disfluencies, no room). It is
a good regression signal and a poor absolute number. Replacing
`bench/corpus/` with recordings of your own dictation is the highest-value
contribution to this file — see [`bench/corpus/README.md`](bench/corpus/README.md).

CPU results also move with machine load; an earlier run of the same corpus under
load measured 1402 ms TTFW against the 754 ms above. Quote the machine *and* its
state, or don't quote the number.
