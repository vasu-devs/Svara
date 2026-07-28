# Benchmark corpus

Drop matched pairs here:

```
bench/corpus/
  my-clip.wav      16 kHz mono (other rates are resampled)
  my-clip.txt      the reference transcript, verbatim
```

`run.bat --bench` measures WER, CER and dictionary-term recall against these,
and latency/RTF regardless. **With no pairs here it says WER was not measured**
rather than printing a flattering zero.

## What to record

LibriSpeech `test-clean` excerpts make results comparable with published
numbers, but they are read prose and flatter every engine. The clips that
actually predict how Svara feels are recordings of *your own dictation*:

- technical vocabulary and proper nouns (the words your dictionary boosts)
- false starts and self-corrections ("send it Tuesday — no, Wednesday")
- the acoustics you really use: your room, your mic, your speaking distance
- a range of lengths (~1 s to ~30 s), since decode cost is not linear

Twenty clips is enough to see a regression. Keep them short; this directory is
committed so results are comparable across machines and commits.
